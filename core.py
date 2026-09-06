"""Strict normalization, persistent event identity, field diffs and iCalendar."""
from __future__ import annotations

import copy
import hashlib
import html
import json
import re
import uuid
from collections import Counter
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event, Timezone

TZ = ZoneInfo("Asia/Shanghai")
NAMESPACE = uuid.UUID("5872874d-d0c4-4d4d-86f4-e8a228597678")
FIELDS = ("course_name", "course_code", "date", "start_time", "end_date", "end_time", "location", "teacher", "content", "notes", "course_type")
LABELS = {"course_name": "课程", "date": "日期", "start_time": "开始时间", "end_date": "结束日期",
          "end_time": "结束时间", "location": "地点", "teacher": "教师", "content": "授课内容",
          "notes": "备注", "course_type": "类型", "course_code": "课程编号"}


class DataError(Exception):
    pass


def clean(value):
    if value is None:
        return ""
    value = html.unescape(str(value)).replace(">>", "").replace("<<", "")
    value = re.sub(r"<br\s*/?>|</(?:p|div)>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]*>", "", value)
    return "\n".join(re.sub(r"[\t \u3000]+", " ", line).strip()
                     for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")).strip()


def ids(value):
    if value in (None, ""):
        return []
    return sorted(set(re.findall(r"\d+", str(value))), key=int)


def parse_time(value):
    if not isinstance(value, str):
        raise DataError("课程时间不是字符串。")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise DataError("课程日期格式改变，已停止发布。") from None
    # The live API supplies explicit local datetimes without an offset.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    else:
        dt = dt.astimezone(TZ)
    if not 2000 <= dt.year <= 2100:
        raise DataError("课程日期超出支持范围。")
    return dt


def joined(rows, key):
    return "；".join(sorted({clean(r.get(key)) for r in rows if clean(r.get(key))}))


def normalize_one(row, details):
    if not isinstance(row, dict) or not isinstance(details, list) or any(not isinstance(d, dict) for d in details):
        raise DataError("课程或教学日历的响应结构改变。")
    if not details:
        raise DataError("教学日历详情为空，无法确认采集完整；请重新采集，旧课表保留。")
    if row.get("AllDay"):
        raise DataError("发现全天事件，需要核对时间规则后再发布。")
    start, end = parse_time(row.get("Start")), parse_time(row.get("End"))
    if end <= start:
        raise DataError("发现结束时间不晚于开始时间的课程。")
    name = clean(row.get("Curriculum"))
    if not name:
        raise DataError("发现缺少课程名称的事件。")
    course_id = str(row.get("CurriculumID") or "")
    class_id = str(row.get("CSID") or "")
    kind = clean(row.get("CurriculumType"))
    tag = f"{kind}:{course_id}:{class_id}"
    slot_ids = ids(row.get("MCSID"))
    detail_ids = sorted({str(d["DetailID"]) for d in details if d.get("DetailID") is not None})
    teaching_ids = sorted({str(d["ID"]) for d in details if d.get("ID") is not None})
    aliases = ([f"slot:{tag}:{v}" for v in slot_ids]
               + [f"detail:{tag}:{v}" for v in detail_ids]
               + [f"teaching-event:{tag}:{v}" for v in teaching_ids])
    if row.get("ID") is not None:
        aliases.append(f"main:{tag}:{row['ID']}")
    if not aliases:
        raise DataError("事件缺少可用的源标识，拒绝使用课程名和时间冒充永久身份。")
    for d in details:
        if d.get("IsDel") is True:
            raise DataError("课表仍显示的事件在教学日历中已删除，需重新同步核实。")
        if d.get("CurriculumID") is not None and str(d["CurriculumID"]) != course_id:
            raise DataError("课程与教学日历的课程 ID 不一致。")
        linked = set(ids(d.get("CurriculumScheduleIDs")))
        if slot_ids and linked and not linked.intersection(slot_ids):
            raise DataError("教学日历无法对应到该课程的排课 ID。")
        if d.get("ClassTime") and parse_time(d["ClassTime"]).date() != start.date():
            raise DataError("课表日期与教学日历日期不一致。")
    teachers = joined(details, "Teacher") or clean(row.get("Teacher"))
    return {
        "source_id": str(row.get("ID") or ""), "course_id": course_id,
        "schedule_manager_id": class_id, "course_code": clean(row.get("CourseCode")),
        "course_name": name, "course_type": kind,
        "date": start.date().isoformat(), "start_time": start.strftime("%H:%M:%S"),
        "end_date": end.date().isoformat(), "end_time": end.strftime("%H:%M:%S"),
        "start": start.isoformat(), "end": end.isoformat(), "timezone": "Asia/Shanghai",
        "location": clean(row.get("ClassroomAcademy")) or clean(row.get("Classroom")),
        "teacher": teachers, "content": joined(details, "Content") or clean(row.get("Content")),
        "notes": joined(details, "Bz"), "source": "https://jwstu.shsmu.edu.cn/Home/GetCurriculumTable",
        "source_ids": {"MCSID": slot_ids, "ID": row.get("ID"), "CSID": row.get("CSID"),
                       "CurriculumID": row.get("CurriculumID"), "XXKMID": row.get("XXKMID"),
                       "detail_ids": detail_ids, "teaching_event_ids": teaching_ids,
                       "teaching_calendar_ids": sorted({str(d["TeachingCalendarID"]) for d in details if d.get("TeachingCalendarID") is not None})},
        "identity_aliases": sorted(set(aliases)),
        "identity_basis": "detail" if detail_ids else ("teaching-event" if teaching_ids else ("slot" if slot_ids else "main")),
    }


def semantic(event):
    return {k: event.get(k, "") for k in FIELDS}


def identity_key(alias):
    """Match legacy aliases without treating the display course type as identity.

    Keep persisted aliases and UUID anchors unchanged so existing UID history
    remains usable. Course, schedule manager, source kind and source ID still
    scope every match; any collision is rejected by reconcile.
    """
    try:
        namespace, value = alias.split(":", 1)
        _, course_id, manager_id, source_id = value.rsplit(":", 3)
    except (AttributeError, ValueError):
        raise DataError("事件身份标识格式不正确，已停止。") from None
    if namespace not in ("slot", "detail", "teaching-event", "main") or not source_id:
        raise DataError("事件身份标识格式不正确，已停止。")
    return namespace, course_id, manager_id, source_id


def normalize(items, start, end):
    lower, upper = date.fromisoformat(start), date.fromisoformat(end)
    if lower >= upper:
        raise DataError("日期范围无效。")
    normalized = []
    seen = {}
    for item in items:
        event = normalize_one(item["event"], item["details"])
        if not lower <= date.fromisoformat(event["date"]) < upper:
            continue  # Source end inclusivity does not leak events across chunk boundaries.
        key = tuple(event["identity_aliases"])
        if key in seen:
            if semantic(seen[key]) != semantic(event):
                raise DataError("相同源标识返回了互相冲突的课程内容。")
            continue
        seen[key] = event
        normalized.append(event)
    return sorted(normalized, key=lambda e: (e["start"], e["end"], e["course_name"], e["source_id"]))


def reconcile(events, previous, scope, now):
    """Match using actual source identifiers, never name+date+start as identity."""
    if previous and previous["scope"] != scope:
        raise DataError("登录账号、学期或日期范围与上次不同。请显式建立新学期，避免误报删除。")
    old_active = {e["uid"]: e for e in (previous or {}).get("events", [])}
    old_all = {**{e["uid"]: e for e in (previous or {}).get("cancelled_events", [])}, **old_active}
    alias_index = {}
    for uid, event in old_all.items():
        for alias in event["identity_aliases"]:
            key = identity_key(alias)
            if key in alias_index and alias_index[key] != uid:
                raise DataError("上一版本包含冲突身份，已停止。")
            alias_index[key] = uid
    matched = set()
    current_aliases = set()
    current, changes = [], []
    for value in events:
        event = copy.deepcopy(value)
        aliases = set(event["identity_aliases"])
        keys = {identity_key(alias) for alias in aliases}
        if current_aliases.intersection(keys):
            raise DataError("多个当前事件共用源标识，可能发生拆课或合课，需要核对。")
        current_aliases.update(keys)
        candidates = {alias_index[key] for key in keys if key in alias_index}
        if len(candidates) > 1 or candidates.intersection(matched):
            raise DataError("排课标识出现拆分或合并歧义；上次完整版本保留。")
        old = old_all[next(iter(candidates))] if candidates else None
        if old:
            uid = old["uid"]
            matched.add(uid)
            event["identity_aliases"] = sorted(aliases.union(old["identity_aliases"]))
            event.update(uid=uid, created_at=old["created_at"], modified_at=old["modified_at"], sequence=old["sequence"])
            field_diff = {k: {"before": old.get(k, ""), "after": event.get(k, "")}
                          for k in FIELDS if old.get(k, "") != event.get(k, "")}
            restored = uid not in old_active
            if field_diff or restored:
                event.update(modified_at=now, sequence=old["sequence"] + 1)
                changes.append({"type": "ADDED" if restored else "CHANGED", "uid": uid,
                                "course_name": event["course_name"], "date": event["date"],
                                "fields": field_diff, "restored": restored})
        else:
            anchor = "|".join(a for a in event["identity_aliases"] if a.startswith(event["identity_basis"] + ":"))
            identity_scope = {k: scope[k] for k in ("semester", "account_key")}
            namespace_key = json.dumps(identity_scope, ensure_ascii=True, sort_keys=True) + "|" + anchor
            uid = str(uuid.uuid5(NAMESPACE, namespace_key)) + "@shsmu-schedule.local"
            event.update(uid=uid, created_at=now, modified_at=now, sequence=0)
            changes.append({"type": "ADDED", "uid": uid, "course_name": event["course_name"], "date": event["date"], "fields": {}})
        event.update(last_seen_at=now, status="CONFIRMED")
        current.append(event)
    cancelled = []
    for uid, old in old_all.items():
        if uid in matched:
            continue
        event = copy.deepcopy(old)
        if uid in old_active:
            event.update(status="CANCELLED", cancelled_at=now, modified_at=now, sequence=old["sequence"] + 1)
            changes.append({"type": "REMOVED", "uid": uid, "course_name": old["course_name"], "date": old["date"], "fields": {}})
        cancelled.append(event)
    # No speculative time/name based remapping. Surface possible wholesale ID replacement.
    added_courses = {e["course_id"] for e in current if any(c["type"] == "ADDED" and c["uid"] == e["uid"] for c in changes)}
    removed_courses = {e["course_id"] for e in cancelled if any(c["type"] == "REMOVED" and c["uid"] == e["uid"] for c in changes)}
    warnings = []
    old_months = Counter(e['date'][:7] for e in old_active.values())
    new_months = Counter(e['date'][:7] for e in current)
    for month, count in sorted(old_months.items()):
        if not new_months[month]:
            warnings.append(f"异常提示：{month} 的课程由 {count} 次变为 0 次；请在教务页面核对，必要时重新采集。")
    removed_count = sum(c['type'] == 'REMOVED' for c in changes)
    if removed_count >= 10 and removed_count * 4 >= len(old_active):
        warnings.append(f"异常提示：本次删除 {removed_count}/{len(old_active)} 次课程（{removed_count / len(old_active):.0%}）；"
                        "请核对删除明细，必要时重新采集。")
    if added_courses & removed_courses:
        warnings.append("同一课程同时出现新标识与删除标识；可能是停课加补课，也可能是教务重建标识。未按名称或时间强行合并。")
    missing_teacher = sum(not e["teacher"] for e in current)
    missing_location = sum(not e["location"] for e in current)
    if missing_teacher:
        warnings.append(f"{missing_teacher} 个事件未提供教师。")
    if missing_location:
        warnings.append(f"{missing_location} 个事件未提供地点。")
    snapshot = {"schema_version": 1, "timezone": "Asia/Shanghai", "scope": scope,
                "synced_at": now, "events": current, "cancelled_events": cancelled, "warnings": warnings}
    return snapshot, {"synced_at": now, "summary": {t: sum(c["type"] == t for c in changes) for t in ("ADDED", "REMOVED", "CHANGED")}, "changes": changes, "warnings": warnings}


def export_ics(snapshot):
    calendar = Calendar()
    calendar.add("prodid", "-//SHSMU Schedule Sync//CN")
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("x-wr-calname", "医学院课表 " + snapshot["scope"]["semester"])
    calendar.add("x-wr-timezone", "Asia/Shanghai")
    calendar.add_component(Timezone.from_tzinfo(TZ, first_date=date(2000, 1, 1), last_date=date(2100, 1, 1)))
    all_events = snapshot["events"] + snapshot.get("cancelled_events", [])
    for row in sorted(all_events, key=lambda e: e["uid"]):
        event = Event()
        event.add("uid", row["uid"])
        event.add("dtstart", parse_time(row["start"]))
        event.add("dtend", parse_time(row["end"]))
        for field, source in (("dtstamp", "modified_at"), ("last-modified", "modified_at"), ("created", "created_at")):
            event.add(field, datetime.fromisoformat(row[source].replace("Z", "+00:00")).astimezone(timezone.utc))
        event.add("sequence", row["sequence"])
        event.add("summary", row["course_name"])
        event.add("location", row["location"])
        description = ["教师：" + (row["teacher"] or "教务未提供"), "类型：" + row["course_type"], "课程编号：" + row["course_code"]]
        for label, key in (("授课内容", "content"), ("备注", "notes")):
            if row[key]:
                description.append(label + "：" + row[key])
        description.append("来源：上海交通大学医学院本科教务系统")
        event.add("description", "\n".join(description))
        event.add("status", row["status"])
        event.add("transp", "TRANSPARENT" if row["status"] == "CANCELLED" else "OPAQUE")
        calendar.add_component(event)
    return calendar.to_ical()


def human_diff(diff):
    summary = diff["summary"]
    lines = ["同步时间：" + diff["synced_at"],
             f"新增 {summary['ADDED']}，删除 {summary['REMOVED']}，修改 {summary['CHANGED']}"]
    if not diff["changes"]:
        lines.append("无变化。")
    for change in diff["changes"]:
        lines.extend(["", f"[{change['type']}] {change['course_name']}（{change['date']}）"])
        for field, values in change["fields"].items():
            lines.append(f"{LABELS.get(field, field)}：{values['before']} → {values['after']}")
    lines.extend("提示：" + warning for warning in diff.get("warnings", []))
    return "\n".join(lines) + "\n"


def content_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
