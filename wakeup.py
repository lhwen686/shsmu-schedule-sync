"""Offline WakeUp CSV export from a verified committed timetable and its details."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from core import DataError, normalize, normalize_one
from sync import ROOT, atomic_write, exclusive_sync, load_current

HEADER = ('课程名称', '星期', '开始节数', '结束节数', '老师', '地点', '周数')


def slot_times():
    """User-approved assumption; observed event endpoints are checked separately."""
    result = {}
    for number in range(1, 15):
        minutes = 8 * 60 + (number - 1) * 50 if number <= 5 else 13 * 60 + 30 + (number - 6) * 50
        result[number] = tuple(f'{m // 60:02d}:{m % 60:02d}:00' for m in (minutes, minutes + 40))
    return result


def load_slot_times(root):
    path = root / 'local/wakeup-slots.json'
    if not path.exists():
        return None
    try:
        values = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError, UnicodeError):
        raise DataError('无法读取 local/wakeup-slots.json；请对照 wakeup-slots.example.json 检查 UTF-8 JSON。') from None
    return validate_slot_times(values)


def validate_slot_times(values):
    if not isinstance(values, list) or len(values) != 14:
        raise DataError('自定义作息应依次列出 1–14 节的上课、下课时间；请对照 wakeup-slots.example.json。')
    times = {}
    previous_end = ''
    for number, pair in enumerate(values, 1):
        if (not isinstance(pair, list) or len(pair) != 2
                or any(not isinstance(v, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', v) for v in pair)
                or not previous_end <= pair[0] < pair[1]):
            raise DataError(f'自定义作息第 {number} 节无效；请使用 HH:MM，保证下课晚于上课，且与上一节不重叠。')
        times[number] = tuple(v + ':00' for v in pair)
        previous_end = pair[1]
    return times


def detail_slots(details):
    slots = set()
    if not details:
        raise DataError('缺少教师详情中的节次，未导出 WakeUp 文件。')
    for detail in details:
        value = detail.get('PKCIndex')
        if not isinstance(value, str) or not re.fullmatch(r'(?:\|[1-9]\d*\|)+', value):
            raise DataError('教师详情的 PKCIndex 缺失或格式改变，未导出 WakeUp 文件。')
        slots.update(int(n) for n in re.findall(r'\d+', value))
    ordered = sorted(slots)
    if ordered != list(range(ordered[0], ordered[-1] + 1)) or not 1 <= ordered[0] <= ordered[-1] <= 14:
        raise DataError('发现不连续或超出 1–14 节的课程，需要核对后再导出。')
    return ordered


def build_export(snapshot, bundle, times=None):
    """Validate everything before producing bytes; never alter snapshot identities."""
    scope = snapshot['scope']
    if (bundle.get('complete') is not True or bundle.get('account_key') != scope['account_key']
            or bundle.get('coverage') != snapshot.get('coverage')):
        raise DataError('原始采集不完整或与当前快照不对应，未导出 WakeUp 文件。')
    items = bundle.get('items')
    if not isinstance(items, list):
        raise DataError('当前运行缺少完整原始课程，未导出 WakeUp 文件。')
    normalized = normalize(items, scope['start'], scope['end_exclusive'])
    # source_ids describes this capture; identity_aliases also retains older IDs.
    def source_key(event):
        return json.dumps(event['source_ids'], sort_keys=True)

    active = {source_key(e): e for e in snapshot['events']}
    if not active or len(active) != len(snapshot['events']) or len(normalized) != len(active):
        raise DataError('当前有效课程数量与原始采集不一致，未导出 WakeUp 文件。')
    for event in normalized:
        saved = active.get(source_key(event))
        if (saved is None
                or not set(event['identity_aliases']).issubset(saved['identity_aliases'])
                or any(saved.get(k) != v for k, v in event.items() if k != 'identity_aliases')):
            raise DataError('当前课程内容与原始采集不一致，未导出 WakeUp 文件。')

    custom_times = times is not None
    times = slot_times() if times is None else times
    mapped = {}
    week_starts = set()
    observed_start, observed_end = set(), set()
    for item in items:
        event = normalize_one(item['event'], item['details'])
        if not scope['start'] <= event['date'] < scope['end_exclusive']:
            continue
        slots = detail_slots(item['details'])
        first, last = slots[0], slots[-1]
        if (event['date'] != event['end_date'] or event['start_time'] != times[first][0]
                or event['end_time'] != times[last][1]):
            raise DataError(f"课程起止时间与已选作息表不一致：{event['date']} 第 {first}–{last} 节，"
                            f"课程为 {event['start_time'][:5]}–{event['end_time'][:5]}，作息为 {times[first][0][:5]}–{times[last][1][:5]}。"
                            '未导出；可复制 wakeup-slots.example.json 为 local/wakeup-slots.json，按本人作息修改后重试。')
        day = date.fromisoformat(event['date'])
        weeks = set()
        for detail in item['details']:
            week = detail.get('WeekNum')
            if type(week) is not int or not 1 <= week <= 35:
                raise DataError('教师详情缺少有效教学周次，未导出 WakeUp 文件。')
            weeks.add(week)
            week_starts.add(day - timedelta(days=day.weekday() + 7 * (week - 1)))
        if len(weeks) != 1:
            raise DataError('同一次课程的详情周次冲突，未导出 WakeUp 文件。')
        row = (event['course_name'], day.isoweekday(), first, last,
               event['teacher'] or '无', event['location'] or '无', weeks.pop())
        key = source_key(event)
        if key in mapped and mapped[key] != row:
            raise DataError('相同课程的节次或周次冲突，未导出 WakeUp 文件。')
        mapped[key] = row
        observed_start.add(first)
        observed_end.add(last)
    if len(week_starts) != 1 or set(mapped) != set(active):
        raise DataError('课程周次无法对应同一个开学日期，或课程未完整转换，未导出。')
    first_monday = week_starts.pop()
    if first_monday > date.fromisoformat(scope['start']):
        raise DataError('第一周起点晚于采集范围起点，需要先核对学期设置。')
    rows = [mapped[source_key(e)] for e in normalized]
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer, lineterminator='\r\n')
    writer.writerow(HEADER)
    writer.writerows(rows)
    csv_bytes = buffer.getvalue().encode('utf-8-sig')
    report = {
        'event_count': len(rows), 'first_monday': first_monday.isoformat(),
        'semester_weeks': max(row[-1] for row in rows),
        'course_start': min(e['date'] for e in normalized),
        'course_end': max(e['date'] for e in normalized),
        'capture_fetched_at': snapshot.get('capture_fetched_at', '未记录'),
        'csv_sha256': hashlib.sha256(csv_bytes).hexdigest(),
        'observed_start_slots': sorted(observed_start), 'observed_end_slots': sorted(observed_end),
        'slot_times': times, 'custom_times': custom_times,
    }
    lines = [
        'WakeUp 课程表：iOS 手动导入说明', '',
        f"学期：{scope['semester']}；有效课程：{len(rows)} 次（CSV 每行对应一次实际课程）",
        f"学校数据采集时间（UTC）：{report['capture_fetched_at']}",
        f"本次已公布课程：{report['course_start']} 至 {report['course_end']}；以后新公布的课程以再次采集为准。",
        '本次仅从已保存的完整快照导出，没有重新访问学校。', '',
        '1. 将 wakeup.csv 保存到 iPhone 的“文件”App。',
        '2. WakeUp → 导入课表 → Excel 导入 → 选取 CSV 文件 → 导入到新课表。',
        '3. 在课表设置中设置以下日期和作息；CSV 本身不携带这些设置。',
        f"   学期开始日期：{first_monday.isoformat()}（第一周周一）",
        f"   WakeUp 课表周数：{report['semester_weeks']}（按本次课程的最大教学周计算）；一天课程节数：14；每周从周一开始。",
        '4. 按下表设置上课时间；若无法逐项修改下课时间，关闭“每节课时长相同”。',
        '5. 核对首周、晚间课程和不连续周次，再决定是否删除旧课表。', '',
        '作息表（“已确认”仅表示原始课程明确给出了该起点或终点）：',
        '节次\t上课\t上课依据\t下课\t下课依据',
    ]
    unobserved = '自定义' if custom_times else '推算'
    for number, (start, end) in times.items():
        lines.append(f"{number}\t{start[:5]}\t{'已确认' if number in observed_start else unobserved}\t"
                     f"{end[:5]}\t{'已确认' if number in observed_end else unobserved}")
    lines += [
        '', ('自定义作息来源：local/wakeup-slots.json；未被原始课程端点确认的时间标为“自定义”。' if custom_times else
             '推算规则：第 1–5 节从 08:00 起，第 6–14 节从 13:30 起；每节 40 分钟，相邻节次间隔 10 分钟。'),
        ('全部有效课程起止时间已与表中节次核对；“自定义”边界由本人配置，不代表学校已确认。' if custom_times else
         '全部有效课程的实际起止时间均已与表中对应节次核对；中间休息时间部分仍为推算，这不是学校官方作息表。'),
        '仅导出课程名称、星期、节次、教师、地点、周数；授课内容和备注不在 WakeUp 七列模板中。',
        '课程时间重叠时保留全部课程，请在 App 中检查冲突显示。', '',
        '以后更新：先完成原来的课表同步，再双击“导出 WakeUp 课表.cmd”，将新 CSV 手动导入到新课表。',
        'WakeUp 不会自动跟随该文件更新；重复导入的覆盖和删除行为尚未验证。',
        '导入后请自行核对课程与作息；本地转换校验不能代替当前设备上的实际检查。',
        'CSV 包含个人课程信息，请勿公开分享。', '',
        '官方导入教程：https://www.wakeup.fun/doc/import_from_csv.html',
        '官方课表设置：https://www.wakeup.fun/doc/settings/schedule_settings.html',
        f"本说明对应 CSV 的 SHA-256：{report['csv_sha256']}",
    ]
    return csv_bytes, ('\r\n'.join(lines) + '\r\n').encode('utf-8-sig'), report


def export_current_unlocked(root: Path):
    """Caller holds exclusive_sync; also used by the desktop import transaction."""
    snapshot = load_current(root)
    if snapshot is None:
        raise DataError('没有已提交的完整课表，请先运行“同步课表.cmd”。')
    pointer = json.loads((root / 'data/current.json').read_text(encoding='utf-8'))
    capture = root / 'data/runs' / pointer['run_id'] / 'capture.json'
    if not capture.is_file():
        raise DataError('当前完整版本缺少原始教师详情，请在保留个人数据的本地项目中导出。')
    bundle = json.loads(capture.read_text(encoding='utf-8'))
    csv_bytes, guide, report = build_export(snapshot, bundle, load_slot_times(root))
    atomic_write(root / 'output/wakeup导入说明.txt', guide)
    atomic_write(root / 'output/wakeup.csv', csv_bytes)
    return report


def export_current(root: Path):
    with exclusive_sync(root):
        return export_current_unlocked(root)


def main():
    try:
        report = export_current(ROOT)
        print(f"已导出 {report['event_count']} 次课程，全部起止时间核对一致。")
        print(f"CSV：{ROOT / 'output/wakeup.csv'}")
        print(f"手机导入与作息设置：{ROOT / 'output/wakeup导入说明.txt'}")
        print('请手动导入 WakeUp，并按配套说明核对课程和作息设置。')
        return 0
    except DataError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, TypeError):
        print('WakeUp 导出失败；请检查当前快照、原始详情及输出目录权限。未确认生成新 CSV。', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
