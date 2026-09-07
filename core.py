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


def _periods(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:\|(?:[1-9]|1[0-4])\|)+', value):
        raise DataError('合班教学日历的节次缺失或格式改变，已停止。')
    return {int(v) for v in ids(value)}


def _positive_id(value):
    return type(value) is int and value > 0 or isinstance(value, str) and value.isdecimal() and int(value) > 0


def _event_details(row, details):
    """Select a fully covered direct schedule from an observed mixed response.

    Raw response arrays stay in the capture bundle. Only these selected rows
    contribute identities, teachers, content and WakeUp periods. Responses
    without any direct match still use the explicit combined-class proof.
    """
    if not isinstance(row, dict) or not isinstance(details, list) or any(not isinstance(d, dict) for d in details):
        raise DataError('课程或教学日历的响应结构改变。')
    slots = set(ids(row.get('MCSID')))
    linked = [(d, set(ids(d.get('CurriculumScheduleIDs')))) for d in details]
    matching = [(d, source_slots) for d, source_slots in linked if slots.intersection(source_slots)]
    if not matching or len(matching) == len(details):
        return details
    error = '混合教学日历无法按排课 ID 完整关联，或详情存在冲突；旧课表保留。'
    if (not _positive_id(row.get('CSID')) or not _positive_id(row.get('CurriculumID'))
            or type(row.get('CourseCount')) is not int or row['CourseCount'] != len(slots)):
        raise DataError(error)
    calendars, detail_ids = set(), {}
    for d, source_slots in linked:
        if (not source_slots or any(not _positive_id(d.get(k)) for k in
                ('ID', 'DetailID', 'TeachingCalendarID', 'ScheduleManagerID', 'CurriculumID'))
                or str(d['ScheduleManagerID']) != str(row['CSID'])
                or str(d['CurriculumID']) != str(row['CurriculumID'])
                or d.get('HeBanID') not in (None, '', 0, '0') or d.get('IsDel') is not False
                or not d.get('ClassTime') or parse_time(d['ClassTime']).date() != parse_time(row.get('Start')).date()):
            raise DataError(error)
        periods, taught = _periods(d.get('PKCIndex')), _periods(d.get('KCIndex'))
        if (len(periods) != len(source_slots) or not taught.issubset(periods)
                or sorted(periods) != list(range(min(periods), max(periods) + 1))):
            raise DataError(error)
        calendars.add(str(d['TeachingCalendarID']))
        signature = (str(d['ID']), frozenset(source_slots), frozenset(periods), frozenset(taught),
                     *(clean(d.get(k)) for k in ('Teacher', 'Content', 'Bz', 'WeekNum')))
        key = str(d['DetailID'])
        if key in detail_ids and detail_ids[key] != signature:
            raise DataError(error)
        detail_ids[key] = signature
    selected = [d for d, _ in matching]
    covered = set().union(*(source_slots for _, source_slots in matching))
    periods = set().union(*(_periods(d['PKCIndex']) for d in selected))
    taught = set().union(*(_periods(d['KCIndex']) for d in selected))
    if (len(calendars) != 1 or covered != slots or len(periods) != len(slots) or taught != periods
            or sorted(periods) != list(range(min(periods), max(periods) + 1))):
        raise DataError(error)
    return selected


def _combined_class(row, details):
    """Only the observed, explicitly merged cross-manager response may differ.

    CaptureSource binds the response to the exact main-event request. This is
    not a name/date lookup or permission to accept arbitrary unmatched IDs.
    """
    if not isinstance(row, dict) or not isinstance(details, list) or any(not isinstance(d, dict) for d in details):
        raise DataError('课程或教学日历的响应结构改变。')
    slots = set(ids(row.get('MCSID')))
    if not any(slots and ids(d.get('CurriculumScheduleIDs'))
               and not slots.intersection(ids(d.get('CurriculumScheduleIDs'))) for d in details):
        return False
    if (not _positive_id(row.get('CSID')) or not _positive_id(row.get('CurriculumID'))
            or type(row.get('CourseCount')) is not int or row['CourseCount'] != len(slots)):
        raise DataError('教学日历无法对应到该课程的排课 ID。')
    signatures = set()
    for d in details:
        if (any(not _positive_id(d.get(k)) for k in ('HeBanID', 'ScheduleManagerID', 'TeachingCalendarID', 'ID', 'DetailID'))
                or str(d['ScheduleManagerID']) == str(row['CSID'])
                or len(set(clean(d.get('ClassCode')).split())) < 2
                or str(d.get('CurriculumID')) != str(row['CurriculumID'])
                or not d.get('ClassTime') or parse_time(d['ClassTime']).date() != parse_time(row.get('Start')).date()
                or d.get('IsDel') is True or not ids(d.get('CurriculumScheduleIDs'))
                or slots.intersection(ids(d.get('CurriculumScheduleIDs')))):
            raise DataError('教学日历无法对应到该课程的排课 ID；合班关联证据不完整或冲突。')
        if not _periods(d.get('KCIndex')).issubset(_periods(d.get('PKCIndex'))):
            raise DataError('合班授课节次超出对应排课范围，已停止。')
        signatures.add((str(d['HeBanID']), str(d['ScheduleManagerID']), tuple(sorted(clean(d['ClassCode']).split()))))
    if len(signatures) != 1:
        raise DataError('同一次课程的合班关联互相冲突，已停止。')
    return True


def _combined_periods(items):
    """Partition a shared source calendar by complete, ordered main slot IDs.

    Dates and times remain the explicit main-event values. No default WakeUp
    clock, numeric ID offset, or invented persistent event ID is used here.
    """
    groups, result = {}, {}
    fields = ('ID', 'DetailID', 'TeachingCalendarID', 'HeBanID', 'ScheduleManagerID',
              'CurriculumScheduleIDs', 'PKCIndex', 'KCIndex', 'GroupName', 'WeekNum',
              'Teacher', 'Content', 'Bz')
    for index, item in enumerate(items):
        row, details = item['event'], item['details']
        if not _combined_class(row, details):
            continue
        signature = tuple(sorted(json.dumps({k: clean(d.get(k)) for k in fields}, sort_keys=True) for d in details))
        key = (str(row['CSID']), str(row['CurriculumID']), parse_time(row['Start']).date(), signature)
        groups.setdefault(key, []).append((index, row, details))
    for group in groups.values():
        details = group[0][2]
        periods = sorted(set().union(*(_periods(d['PKCIndex']) for d in details)))
        taught = set().union(*(_periods(d['KCIndex']) for d in details))
        if periods != list(range(periods[0], periods[-1] + 1)) or taught != set(periods):
            raise DataError('合班教学日历的排课或授课节次未完整覆盖，已停止。')
        unique = {}
        for index, row, _ in group:
            identity = (str(row.get('ID')), tuple(ids(row['MCSID'])))
            if identity in unique and unique[identity][0] != row:
                raise DataError('同一合班主事件返回互相冲突的内容，已停止。')
            unique.setdefault(identity, (row, []))[1].append(index)
        ordered = sorted(unique.values(), key=lambda value: parse_time(value[0]['Start']))
        offset, seen_slots, last_end = 0, set(), None
        for row, indices in ordered:
            start, end = parse_time(row['Start']), parse_time(row['End'])
            slots = set(ids(row['MCSID']))
            if (start.date() != end.date() or start >= end or last_end is not None and start < last_end
                    or seen_slots.intersection(slots)):
                raise DataError('合班分段主课表的时间或源标识有歧义，已停止。')
            assigned = periods[offset:offset + len(slots)]
            if len(assigned) != len(slots):
                raise DataError('合班主课表节数超出教学详情，已停止。')
            for index in indices:
                result[index] = assigned
            offset += len(slots)
            seen_slots.update(slots)
            last_end = end
        if offset != len(periods):
            raise DataError('合班分段主课表未完整覆盖教学详情的节次，已停止。')
    return result


def normalize_with_details(items):
    selected = []
    for index, item in enumerate(items, 1):
        try:
            selected.append({'event': item['event'], 'details': _event_details(item['event'], item['details'])})
        except Exception as error:
            error.diagnostic_index = index
            error.diagnostic_checks = item
            raise
    items = selected
    periods = _combined_periods(items)
    result = []
    for index, item in enumerate(items):
        try:
            result.append((normalize_one(item['event'], item['details'], combined_periods=periods.get(index)), item['details']))
        except Exception as error:
            error.diagnostic_index = index + 1
            error.diagnostic_checks = item
            raise
    return result


def normalize_one(row, details, *, combined_periods=None):
    details = _event_details(row, details)
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
    combined = _combined_class(row, details)
    if combined and combined_periods is None:
        combined_periods = _combined_periods([{'event': row, 'details': details}])[0]
    detail_ids = sorted({str(d["DetailID"]) for d in details if d.get("DetailID") is not None})
    teaching_ids = sorted({str(d["ID"]) for d in details if d.get("ID") is not None})
    aliases = ([f"slot:{tag}:{v}" for v in slot_ids]
               + ([] if combined else [f"detail:{tag}:{v}" for v in detail_ids]
                  + [f"teaching-event:{tag}:{v}" for v in teaching_ids]))
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
        if slot_ids and linked and not linked.intersection(slot_ids) and not combined:
            raise DataError("教学日历无法对应到该课程的排课 ID。")
        if d.get("ClassTime") and parse_time(d["ClassTime"]).date() != start.date():
            raise DataError("课表日期与教学日历日期不一致。")
    relevant = ([d for d in details if _periods(d['KCIndex']).intersection(combined_periods)]
                if combined else details)
    teachers = joined(relevant, "Teacher") or clean(row.get("Teacher"))
    event = {
        "source_id": str(row.get("ID") or ""), "course_id": course_id,
        "schedule_manager_id": class_id, "course_code": clean(row.get("CourseCode")),
        "course_name": name, "course_type": kind,
        "date": start.date().isoformat(), "start_time": start.strftime("%H:%M:%S"),
        "end_date": end.date().isoformat(), "end_time": end.strftime("%H:%M:%S"),
        "start": start.isoformat(), "end": end.isoformat(), "timezone": "Asia/Shanghai",
        "location": clean(row.get("ClassroomAcademy")) or clean(row.get("Classroom")),
        "teacher": teachers, "content": joined(relevant, "Content") or clean(row.get("Content")),
        "notes": joined(relevant, "Bz"), "source": "https://jwstu.shsmu.edu.cn/Home/GetCurriculumTable",
        "source_ids": {"MCSID": slot_ids, "ID": row.get("ID"), "CSID": row.get("CSID"),
                       "CurriculumID": row.get("CurriculumID"), "XXKMID": row.get("XXKMID"),
                       "detail_ids": detail_ids, "teaching_event_ids": teaching_ids,
                       "teaching_calendar_ids": sorted({str(d["TeachingCalendarID"]) for d in details if d.get("TeachingCalendarID") is not None})},
        "identity_aliases": sorted(set(aliases)),
        "identity_basis": 'slot' if combined else ("detail" if detail_ids else ("teaching-event" if teaching_ids else ("slot" if slot_ids else "main"))),
    }
    if combined:
        event['source_ids']['combined_class'] = {'HeBanID': str(details[0]['HeBanID']),
            'ScheduleManagerID': str(details[0]['ScheduleManagerID']), 'periods': list(combined_periods)}
    return event


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
    for event, _ in normalize_with_details(items):
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
