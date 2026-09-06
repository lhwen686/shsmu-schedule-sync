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
    cursor, stop = date.fromisoformat(start), date.fromisoformat(end)
    if not cursor < stop or (stop - cursor).days > 240:
        raise DataError("请选择不超过 240 天的一个学期。结束日期不包含在范围内。")
    while cursor < stop:
        next_month = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        chunk_end = min(next_month, stop)
        yield cursor.isoformat(), chunk_end.isoformat()
        cursor = chunk_end


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
        return
    pointer = json.loads((root / "data/current.json").read_text(encoding="utf-8"))
    run = root / "data/runs" / pointer["run_id"]
    atomic_write(root / "data/schedule.json", json_bytes(snapshot))
    atomic_write(root / "output/calendar.ics", export_ics(snapshot))
    for name in ("changes.json", "changes.txt"):
        atomic_write(root / "output" / name, (run / name).read_bytes())


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
        raise SourceError("下载目录不存在，请用 --downloads 指定 Chrome 的下载目录。")
    before = {p.resolve() for p in folder.glob('shsmu-capture-*.json')}
    print(f"等待 Chrome 下载的新课表：{folder}", flush=True)
    print("请在正常登录后显示本人学号的教务首页点击“同步医学院课表”书签。", flush=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        candidates = [p for p in folder.glob('shsmu-capture-*.json') if p.resolve() not in before]
        if candidates:
            return max(candidates, key=lambda p:p.stat().st_mtime_ns)
        time.sleep(1)
    raise SourceError("尚未收到新的采集文件。可重新运行，或用 --capture 指定已下载的 JSON。")


def main(argv=None):
    parser = argparse.ArgumentParser(description="上海交通大学医学院课表同步（复用已打开的 Chrome）")
    parser.add_argument("--prepare", action="store_true", help="生成 Chrome 书签安装页，不启动浏览器")
    parser.add_argument("--capture", type=Path, help="处理指定的 Chrome 采集文件")
    parser.add_argument("--downloads", type=Path, help="Chrome 的下载目录；默认读取 Windows 下载文件夹")
    parser.add_argument("--repair", action="store_true", help="从已提交快照重新生成输出，不访问学校")
    parser.add_argument("--upload-only", action="store_true", help="仅重试上传当前完整日历，不访问学校")
    parser.add_argument("--new-term", action="store_true", help="显式开始新学期；历史完整版本保留")
    parser.add_argument("--config", type=Path, default=ROOT / "config.local.json", help="本机日期配置")
    args = parser.parse_args(argv)
    try:
        with exclusive_sync(ROOT):
            if args.upload_only:
                publish_current(ROOT, required=True)
                return 0
            if args.repair:
                repair_exports(ROOT)
                print("已从完整快照恢复输出。")
                return 0
            if not args.config.exists():
                atomic_write(args.config, (ROOT / "config.example.json").read_bytes())
            config = json.loads(args.config.read_text(encoding="utf-8"))
            list(month_ranges(config["start"], config["end_exclusive"]))
            build_bookmark(ROOT, config)
            if args.prepare:
                print(f"已生成书签安装页：{ROOT / 'chrome-bookmark.html'}")
                return 0
            previous = load_current(ROOT)
            repair_exports(ROOT)
            capture_path = args.capture or wait_capture(args.downloads or Path(config.get('downloads_dir') or downloads_folder()))
            source = CaptureSource(capture_path, config)
            capture_hash = content_hash(source.capture)
            if previous and previous.get('capture_hash') == capture_hash:
                print("该文件已经处理，没有新的实时采集；当前课表与日历保持原版本。")
                publish_current(ROOT)
                return 0
            fetched_at = source.capture.get('fetched_at', '')
            fetched_time = datetime.fromisoformat(fetched_at.replace('Z','+00:00'))
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
            if previous and previous["scope"] != scope and not args.new_term:
                raise DataError("账号、学期或范围已改变，请核对配置；新学期使用 --new-term。")
            bundle = fetch_complete(source, config, run_dir)
            events = normalize(bundle["items"], config["start"], config["end_exclusive"])
            snapshot, diff = reconcile(events, None if args.new_term else previous, scope, now)
            snapshot["coverage"] = bundle["coverage"]
            snapshot["request_count"] = bundle["request_count"]
            snapshot['capture_hash'] = capture_hash
            snapshot['capture_fetched_at'] = fetched_at
            publish(ROOT, run_dir, snapshot, diff, previous)
            print(human_diff(diff))
            print(f"已发布 {len(events)} 个有效事件：data/schedule.json、output/calendar.ics")
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
