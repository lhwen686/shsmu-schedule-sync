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

from core import DataError, normalize, normalize_with_details
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
    for event, details in normalize_with_details(items):
        if not scope['start'] <= event['date'] < scope['end_exclusive']:
            continue
        combined = event['source_ids'].get('combined_class')
        slots = combined['periods'] if combined else detail_slots(details)
        first, last = slots[0], slots[-1]
        if (event['date'] != event['end_date'] or event['start_time'] != times[first][0]
                or event['end_time'] != times[last][1]):
            raise DataError(f"课程起止时间与已选作息表不一致：{event['date']} 第 {first}–{last} 节，"
                            f"课程为 {event['start_time'][:5]}–{event['end_time'][:5]}，作息为 {times[first][0][:5]}–{times[last][1][:5]}。"
                            '未导出；可复制 wakeup-slots.example.json 为 local/wakeup-slots.json，按本人作息修改后重试。')
        day = date.fromisoformat(event['date'])
        weeks = set()
        for detail in details:
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
    years, term = scope['semester'].split(':')
    timetable = []
    unobserved = '自定义' if custom_times else '模板推算'
    for number, (start, end) in times.items():
        timetable.append(f"{number}\t{start[:5]}\t{'教务课表' if number in observed_start else unobserved}\t"
                         f"{end[:5]}\t{'教务课表' if number in observed_end else unobserved}")
    time_source = ('时间来自你的自定义设置；未在学校课程中明确出现的时间标为“自定义”。' if custom_times else
                   '未在学校课程中明确出现的时间标为“模板推算”，请结合本人实际作息核对。')
    guide = 'WakeUp 导入与作息设置（iPhone）\n\n学期：{semester_label}\n文件包含：{event_count} 次课程\n课表获取时间（UTC）：{capture_fetched_at}\n当前课程日期：{course_start} 至 {course_end}\n\n本文件由已保存的课表生成。教务新增或调整课程后，需要重新获取课表。\n\n一、导入课表\n1. 将 wakeup.csv 发到 iPhone，保存到“文件”App。\n2. 在 WakeUp 打开导入入口，选择“Excel 导入 → 选取 CSV 文件”。\n3. 选择 wakeup.csv，导入为新课表。\n4. 按下方信息设置日期、周数和作息，再核对课程。\n\n二、课表设置\n学期开始日期：{first_monday}（第 1 周周一）\n课表周数：{semester_weeks} 周（按本次课程计算）\n每天节数：14 节\n每周开始：周一\n\nCSV 不会自动设置学期日期和作息。需要逐节修改下课时间时，关闭“每节课时长相同”。\n\n三、作息时间\n节次\t上课时间\t上课时间来源\t下课时间\t下课时间来源\n{timetable}\n\n“教务课表”表示该时间在学校课程中有明确记录；其他时间由模板或你的设置补齐。\n所有实际课程的起止时间均已按对应节次核对，但此表不等同于学校官方作息表。\n{time_source}\n\n四、导入后核对\n重点核对第 1 周、晚课和间隔周上课的课程，并检查时间重叠的课程是否正常显示。\n本文件包含课程名称、星期、节次、教师、地点和周数；不包含授课内容和备注。\n\n五、之后如何更新\n在助手中重新获取课表，将新生成的 wakeup.csv 导入为新课表。\n核对无误后再处理旧课表，避免重复显示。手机不会自动跟随电脑文件更新。\n重复导入不保证覆盖或删除旧课程；请以手机实际显示为准。\n命令行版仍可运行“导出 WakeUp 课表.cmd”生成文件。\n\n文件包含个人课表信息，请勿公开分享。\n\n官方 CSV 导入说明：https://www.wakeup.fun/doc/import_from_csv.html\n官方课表设置说明：https://www.wakeup.fun/doc/settings/schedule_settings.html\n对应 CSV 的 SHA-256：{csv_sha256}'
    lines = guide.format(
        semester_label=f'{years} 学年 · 第 {term} 学期',
        timetable='\n'.join(timetable), time_source=time_source, **report).split('\n')
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
