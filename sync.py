"""One complete, recoverable timetable synchronization. Run with --help."""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from core import DataError, content_hash, export_ics, human_diff, ids, normalize, parse_time, reconcile
from source import CaptureSource, LoginRequired, SourceError, request_key, scrub, write_json
from prepare import build_bookmark, downloads_folder
from webcal import UploadError, publish_current

ROOT = Path(__file__).resolve().parent


def month_ranges(start, end):
    try:
        if any(not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) for day in (start, end)):
            raise ValueError
        cursor, stop = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        raise DataError("配置中的 start、end_exclusive 必须是有效日期，格式为 YYYY-MM-DD。") from None
    if not cursor < stop or (stop - cursor).days > 240:
        raise DataError("请选择不超过 240 天的一个学期。结束日期不包含在范围内。")
    while cursor < stop:
        next_month = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        chunk_end = min(next_month, stop)
        yield cursor.isoformat(), chunk_end.isoformat()
        cursor = chunk_end


def load_settings(path):
    try:
        config = json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, UnicodeError):
        raise DataError("配置文件不是有效的 UTF-8 JSON；请对照 config.example.json 检查双引号、逗号和日期。") from None
    except OSError:
        raise DataError("无法读取配置文件，请检查 --config 路径和文件权限。") from None
    if not isinstance(config, dict) or not all(key in config for key in ('semester', 'start', 'end_exclusive')):
        raise DataError("配置必须包含 semester、start、end_exclusive；请对照 config.example.json。")
    semester = config['semester']
    match = re.fullmatch(r"(\d{4})-(\d{4}):[1-9]", semester) if isinstance(semester, str) else None
    if not match or int(match[2]) != int(match[1]) + 1:
        raise DataError("semester 格式应为连续两年的学期，例如 2026-2027:1。")
    list(month_ranges(config['start'], config['end_exclusive']))
    if 'downloads_dir' in config and (not isinstance(config['downloads_dir'], str) or not config['downloads_dir'].strip()):
        raise DataError("downloads_dir 应为下载目录字符串；使用正斜杠（如 D:/Downloads），或删除该项使用默认目录。")
    return config


def capture_folder(config, config_path, override=None):
    value = override or config.get('downloads_dir') or downloads_folder()
    path = Path(os.path.expandvars(str(value))).expanduser()
    return path if path.is_absolute() else config_path.resolve().parent / path


def select_capture(folder):
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        raise SourceError("当前 Python 未安装文件选择组件；请把采集 JSON 拖到“同步课表.cmd”上导入。") from None
    window = None
    try:
        window = tk.Tk()
        window.withdraw()
        window.attributes('-topmost', True)
        selected = filedialog.askopenfilename(parent=window, title='选择已下载的完整课表 JSON',
                                             initialdir=str(folder if folder.is_dir() else Path.home()),
                                             filetypes=[('课表 JSON', '*.json')])
    except tk.TclError:
        raise SourceError("无法打开文件选择窗口；请把采集 JSON 拖到“同步课表.cmd”上导入。") from None
    finally:
        if window is not None:
            window.destroy()
    if not selected:
        raise KeyboardInterrupt
    return Path(selected)


def check_semester(title, expected):
    match = re.search(r"(\d{4}-\d{4})\s*学年\s*第\s*(\d+)\s*学期", title or "")
    if not match or f"{match[1]}:{match[2]}" != expected:
        raise DataError("教务返回的学期与配置不同，未替换当前课表。请核对当前学期与同步日期。")


def fetch_complete(source, config, run_dir):
    all_rows, coverage = [], []
    for start, end in month_ranges(config["start"], config["end_exclusive"]):
        raw = source.timetable(start, end)
        write_json(run_dir / "raw" / f"timetable-{start}-{end}.json", raw)
        # Verified empty months have Title:null; nonempty ranges must match.
        if raw["List"] or str(raw.get("Title") or '').strip():
            check_semester(raw.get("Title"), config["semester"])
        for branch in ("List2", "StuExam"):
            if raw.get(branch):
                raise DataError(f"教务新增了非空 {branch} 数据分支，需要先核实字段。")
        in_range = []
        for row in raw["List"]:
            day = parse_time(row.get("Start")).date()
            if day < date.fromisoformat(start) or day > date.fromisoformat(end):
                raise DataError("接口未按请求范围过滤日期，拒绝将其标记为完整学期。")
            if start <= day.isoformat() < end:
                in_range.append(row)
        all_rows.extend(in_range)
        coverage.append({"start": start, "end_exclusive": end, "source_count": len(raw["List"]), "in_range_count": len(in_range)})
        print(f"已读取 {start} 至 {end}：{len(in_range)} 个事件", flush=True)
    if not all_rows:
        raise DataError("整个学期返回空课表；为避免登录或日期异常造成批量删除，已保留上次版本。")
    items, detail_cache = [], {}
    for index, row in enumerate(all_rows, 1):
        key = request_key('/Home/GetCalendarTable', {k: str(row.get(k) or '') for k in
                          ('MCSID', 'CSID', 'CurriculumID', 'XXKMID', 'CurriculumType')})
        if key not in detail_cache:
            result = source.details(row)
            if not isinstance(result, list) or any(not isinstance(d, dict) for d in result):
                raise DataError("教学日历响应不是预期的数组。")
            if not result:
                raise DataError("教学日历详情为空，无法确认采集完整；请重新采集，旧课表保留。")
            write_json(run_dir / "raw" / f"details-{index:03d}.json", result)
            detail_cache[key] = result
        items.append({"event": row, "details": detail_cache[key]})
    print(f"已读取教师详情：{len(detail_cache)} 个事件请求", flush=True)
    bundle = {"complete": True, "coverage": coverage, "items": items,
              "account_key": source.account_key, "request_count": source.request_count}
    write_json(run_dir / "capture.json", bundle)
    return bundle


def atomic_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temp.open("xb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def load_current(root):
    pointer = root / "data" / "current.json"
    if not pointer.exists():
        return None
    current = json.loads(pointer.read_text(encoding="utf-8"))
    if not re.fullmatch(r"[0-9TZ-]+_[a-f0-9]{8}", current["run_id"]):
        raise DataError("当前版本索引格式不正确。")
    run = root / "data" / "runs" / current["run_id"]
    snapshot = json.loads((run / "schedule.json").read_text(encoding="utf-8"))
    if content_hash(snapshot) != current["schedule_hash"]:
        raise DataError("当前快照校验失败，请从历史版本恢复。")
    return snapshot


def repair_exports(root):
    snapshot = load_current(root)
    if snapshot is None:
        return False
    pointer = json.loads((root / "data/current.json").read_text(encoding="utf-8"))
    run = root / "data/runs" / pointer["run_id"]
    atomic_write(root / "data/schedule.json", json_bytes(snapshot))
    atomic_write(root / "output/calendar.ics", export_ics(snapshot))
    for name in ("changes.json", "changes.txt"):
        atomic_write(root / "output" / name, (run / name).read_bytes())
    return True


def publish(root, run_dir, snapshot, diff, previous):
    calendar = export_ics(snapshot)
    # A complete immutable run is written before the single commit pointer changes.
    atomic_write(run_dir / "schedule.json", json_bytes(snapshot))
    atomic_write(run_dir / "calendar.ics", calendar)
    atomic_write(run_dir / "changes.json", json_bytes(diff))
    atomic_write(run_dir / "changes.txt", human_diff(diff).encode("utf-8"))
    atomic_write(run_dir / "manifest.json", json_bytes({"complete": True, "schedule_hash": content_hash(snapshot)}))
    if previous:
        atomic_write(root / "data/previous.json", json_bytes(previous))
    pointer = {"run_id": run_dir.name, "schedule_hash": content_hash(snapshot)}
    atomic_write(root / "data/current.json", json_bytes(pointer))
    repair_exports(root)


@contextlib.contextmanager
def exclusive_sync(root):
    path = root / "local/sync.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise DataError("另一个同步程序正在运行，请等待其完成。") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def wait_capture(folder, timeout=1800):
    if not folder.is_dir():
        raise SourceError("下载目录不存在；请修正 downloads_dir，或双击“导入已下载课表.cmd”选择已保存的 JSON。")
    def scan(pattern):
        found = {}
        for path in folder.glob(pattern):
            try:
                if path.is_file():
                    stat = path.stat()
                    found[path] = (stat.st_size, stat.st_mtime_ns)
            except OSError:
                continue  # Chrome or the user may rename/move a file during a poll.
        return found
    before = scan('shsmu-capture-*.json')
    diagnostics = scan('shsmu-diagnostic-*.json')
    print(f"等待 Chrome 下载的新课表：{folder}", flush=True)
    print("请在正常登录后显示本人学号的教务首页点击“同步医学院课表”书签。", flush=True)
    print("文件已下载或保存在别处？关闭本窗口，再双击“导入已下载课表.cmd”，或把 JSON 拖到“同步课表.cmd”上。", flush=True)
    deadline = time.monotonic() + timeout
    last_seen = {}
    while time.monotonic() < deadline:
        current = scan('shsmu-capture-*.json')
        candidates = [p for p, signature in current.items()
                      if signature != before.get(p) and signature == last_seen.get(p) and signature[0] > 0]
        if candidates:
            return max(candidates, key=lambda p: current[p][1])
        last_seen = current
        new_diagnostics = scan('shsmu-diagnostic-*.json')
        if any(signature != diagnostics.get(p) for p, signature in new_diagnostics.items()):
            print("收到失败诊断文件，尚未收到完整课表。请查看 Chrome 的错误提示；可按页面提示继续或重新采集，本窗口继续等待。", flush=True)
        diagnostics = new_diagnostics
        time.sleep(1)
    raise SourceError("等待结束，尚未收到新课表。若文件已保存，请双击“导入已下载课表.cmd”选择它，无需重新采集。")


def main(argv=None):
    parser = argparse.ArgumentParser(description="上海交通大学医学院课表同步（复用已打开的 Chrome）")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--prepare", action="store_true", help="生成 Chrome 书签安装页，不启动浏览器")
    actions.add_argument("--capture", type=Path, help="处理指定的 Chrome 采集文件")
    actions.add_argument("--select-capture", action="store_true", help="打开文件选择窗口，导入已下载的 JSON")
    parser.add_argument("capture_file", nargs='?', type=Path, help="可直接把采集 JSON 拖到“同步课表.cmd”上")
    parser.add_argument("--downloads", type=Path, help="Chrome 的下载目录；默认读取 Windows 下载文件夹")
    actions.add_argument("--repair", action="store_true", help="从已提交快照重新生成输出，不访问学校")
    actions.add_argument("--upload-only", action="store_true", help="仅重试上传当前完整日历，不访问学校")
    parser.add_argument("--new-term", action="store_true", help="显式开始新学期；历史完整版本保留")
    parser.add_argument("--config", type=Path, default=ROOT / "config.local.json", help="本机日期配置")
    args = parser.parse_args(argv)
    if args.capture_file and any((args.capture, args.select_capture, args.prepare, args.repair, args.upload_only)):
        parser.error("拖入文件不能与其他操作同时使用；请选择一种导入方式。")
    if args.new_term and any((args.prepare, args.repair, args.upload_only)):
        parser.error("--new-term 只能用于采集文件导入或等待采集。")
    try:
        with exclusive_sync(ROOT):
            if args.upload_only:
                publish_current(ROOT, required=True)
                return 0
            if args.repair:
                if not repair_exports(ROOT):
                    raise DataError("尚无完整课表可恢复；请先运行“同步课表.cmd”完成一次采集。")
                print("已从完整快照恢复输出。")
                return 0
            if not args.config.exists():
                if args.config != ROOT / 'config.local.json':
                    raise DataError("指定的配置文件不存在，请核对 --config 路径。")
                atomic_write(args.config, (ROOT / "config.example.json").read_bytes())
            config = load_settings(args.config)
            build_bookmark(ROOT, config)
            if args.prepare:
                print(f"已生成书签安装页：{ROOT / 'chrome-bookmark.html'}")
                return 0
            previous = load_current(ROOT)
            repair_exports(ROOT)
            folder = capture_folder(config, args.config, args.downloads)
            capture_path = args.capture or args.capture_file
            if capture_path is None:
                capture_path = select_capture(folder) if args.select_capture else wait_capture(folder)
            source = CaptureSource(capture_path, config)
            capture_hash = content_hash(source.capture)
            if previous and previous.get('capture_hash') == capture_hash:
                print("该文件已经处理，没有新的实时采集；当前课表与日历保持原版本。")
                publish_current(ROOT)
                return 0
            fetched_at = source.capture.get('fetched_at', '')
            try:
                fetched_time = datetime.fromisoformat(fetched_at.replace('Z','+00:00'))
            except (ValueError, AttributeError):
                raise DataError("采集文件缺少有效完成时间，请重新在教务首页采集。") from None
            if fetched_time.tzinfo is None:
                raise DataError("采集时间缺少时区。")
            if previous and previous.get('capture_fetched_at') and fetched_time < datetime.fromisoformat(previous['capture_fetched_at'].replace('Z','+00:00')):
                raise DataError("这是比当前版本更旧的采集文件，拒绝回退课表。")
            print(f"读取 Chrome 采集结果；学校数据采集时间：{fetched_at}", flush=True)
            now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            run_id = now.replace(":", "") + "_" + uuid.uuid4().hex[:8]
            run_dir = ROOT / "data/runs" / run_id
            scope = {"semester": config["semester"], "start": config["start"],
                     "end_exclusive": config["end_exclusive"], "account_key": source.account_key}
            if previous and previous['scope']['account_key'] != source.account_key:
                raise DataError("当前登录账号与已保存课表不符；请登录原账号，或为另一人使用不含个人数据和上传配置的独立项目目录。--new-term 不用于切换账号。")
            scope_changed = previous is not None and previous['scope'] != scope
            if scope_changed and not args.new_term:
                raise DataError("学期或范围已改变，请核对配置及书签；确认新学期时使用 --new-term。")
            bundle = fetch_complete(source, config, run_dir)
            events = normalize(bundle["items"], config["start"], config["end_exclusive"])
            snapshot, diff = reconcile(events, None if scope_changed else previous, scope, now)
            snapshot["coverage"] = bundle["coverage"]
            snapshot["request_count"] = bundle["request_count"]
            snapshot['capture_hash'] = capture_hash
            snapshot['capture_fetched_at'] = fetched_at
            publish(ROOT, run_dir, snapshot, diff, previous)
            print(human_diff(diff))
            print(f"本地已保存 {len(events)} 个有效事件。日历：{ROOT / 'output/calendar.ics'}")
            if diff['changes'] and (ROOT / 'output/wakeup.csv').exists():
                print("课表已变化；已有 WakeUp CSV 仍是旧文件，请再双击“导出 WakeUp 课表.cmd”。")
            publish_current(ROOT)
            return 0
    except LoginRequired as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except (DataError, SourceError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except UploadError as exc:
        print(str(exc), file=sys.stderr)
        print("已有本地完整版本保留；修正发布问题后可双击“仅上传日历.cmd”重试。", file=sys.stderr)
        return 4
    except KeyboardInterrupt:
        print("同步已中断，可重新运行；完整历史版本保留。", file=sys.stderr)
        return 130
    except Exception:
        # Never print a Playwright traceback containing authentication URL parameters.
        print("同步未完成。完整快照保留；请检查文件权限、磁盘空间及 data/runs 中的未完成记录。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
