"""Private calendar backend. Bind to loopback, behind the dedicated Caddy service."""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_BODY = 2 * 1024 * 1024


def digest(data):
    return hashlib.sha256(data).hexdigest()


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result > datetime.now(timezone.utc):
        raise ValueError("timestamp")
    return result


def calendar_datetime(prop, utc_only=False):
    """Validate this publisher's timed events, not arbitrary imported calendars."""
    params, value = prop
    if set(params) - {'TZID', 'VALUE'} or params.get('VALUE', 'DATE-TIME') != 'DATE-TIME':
        raise ValueError('datetime parameters')
    if not re.fullmatch(r'\d{8}T\d{6}Z?', value):
        raise ValueError('datetime format')
    result = datetime.strptime(value.rstrip('Z'), '%Y%m%dT%H%M%S')
    if not 2000 <= result.year <= 2100:
        raise ValueError('datetime range')
    if value.endswith('Z'):
        if 'TZID' in params:
            raise ValueError('UTC timezone parameter')
        return result.replace(tzinfo=timezone.utc)
    if utc_only or params.get('TZID') != 'Asia/Shanghai':
        raise ValueError('unsupported or missing timezone')
    return result.replace(tzinfo=timezone(timedelta(hours=8)))


def validate_calendar(text, expected_count):
    """Check the explicit-event feed produced by core.export_ics using stdlib.

    The supported profile is UTC or Asia/Shanghai timed events in 2000-2100,
    with the publisher's fixed +08:00 VTIMEZONE. Recurrence, alarms, floating
    times and other calendar profiles require explicit support before upload.
    """
    if (not text.startswith('BEGIN:VCALENDAR\r\n') or not text.endswith('END:VCALENDAR\r\n')
            or any(c in text.replace('\r\n', '') for c in ('\r', '\n', '\x00'))):
        raise ValueError('calendar lines')
    allowed = {None: {'VCALENDAR'}, 'VCALENDAR': {'VTIMEZONE', 'VEVENT'},
               'VTIMEZONE': {'STANDARD'}, 'STANDARD': set(), 'VEVENT': set()}
    stack, roots = [], []
    for line in re.sub(r'\r\n[ \t]', '', text).split('\r\n')[:-1]:
        head, separator, value = line.partition(':')
        if not separator:
            raise ValueError('content line')
        if head == 'BEGIN':
            parent = stack[-1][0] if stack else None
            if value not in allowed[parent]:
                raise ValueError('component nesting')
            node = (value, {}, [])
            (stack[-1][2] if stack else roots).append(node)
            stack.append(node)
        elif head == 'END':
            if not stack or stack.pop()[0] != value:
                raise ValueError('component end')
        else:
            if not stack:
                raise ValueError('property outside component')
            name, *parameters = head.split(';')
            if name in ('BEGIN', 'END') or not re.fullmatch(r'[A-Z][A-Z0-9-]*', name) or name in stack[-1][1]:
                raise ValueError('invalid or duplicate property')
            params = {}
            for parameter in parameters:
                key, equals, param = parameter.partition('=')
                if not equals or not param or key in params:
                    raise ValueError('property parameters')
                params[key] = param
            stack[-1][1][name] = (params, value)
    if stack or len(roots) != 1:
        raise ValueError('calendar structure')
    _, calendar, children = roots[0]
    if calendar.get('VERSION') != ({}, '2.0') or not calendar.get('PRODID', ({}, ''))[1] or 'METHOD' in calendar:
        raise ValueError('calendar properties')
    zones = [node for node in children if node[0] == 'VTIMEZONE']
    if len(zones) > 1:
        raise ValueError('duplicate timezone')
    zone_start = None
    if zones:
        _, properties, observances = zones[0]
        if properties.get('TZID') != ({}, 'Asia/Shanghai') or len(observances) != 1:
            raise ValueError('unsupported timezone')
        _, standard, _ = observances[0]
        if any(standard.get(key) != ({}, '+0800') for key in ('TZOFFSETFROM', 'TZOFFSETTO')):
            raise ValueError('timezone offset')
        params, value = standard.get('DTSTART', ({}, ''))
        if params or not re.fullmatch(r'\d{8}T\d{6}', value) or any(key in standard for key in ('RRULE', 'RDATE')):
            raise ValueError('timezone start')
        zone_start = datetime.strptime(value, '%Y%m%dT%H%M%S').replace(tzinfo=timezone(timedelta(hours=8)))
    events = [node[1] for node in children if node[0] == 'VEVENT']
    if type(expected_count) is not int or not events or len(events) != expected_count:
        raise ValueError('event count')
    uids = set()
    for event in events:
        params, uid = event.get('UID', ({}, ''))
        if params or not uid.strip() or uid in uids:
            raise ValueError('event UID')
        uids.add(uid)
        start = calendar_datetime(event['DTSTART'])
        end = calendar_datetime(event['DTEND'])
        if end <= start:
            raise ValueError('event duration')
        for field, instant in (('DTSTART', start), ('DTEND', end)):
            if event[field][0].get('TZID') == 'Asia/Shanghai' and (zone_start is None or instant < zone_start):
                raise ValueError('missing or inapplicable timezone')
        calendar_datetime(event['DTSTAMP'], utc_only=True)
        for field in ('CREATED', 'LAST-MODIFIED'):
            if field in event:
                calendar_datetime(event[field], utc_only=True)
        params, sequence = event.get('SEQUENCE', ({}, ''))
        if params or not re.fullmatch(r'\d+', sequence):
            raise ValueError('event sequence')
        if event.get('STATUS') not in (({}, 'CONFIRMED'), ({}, 'CANCELLED')):
            raise ValueError('event status')
        if any(key in event for key in ('RRULE', 'RDATE', 'EXDATE', 'DURATION', 'RECURRENCE-ID')):
            raise ValueError('unsupported recurrence')


def validate(payload):
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        raise ValueError("schema")
    timestamp(payload.get("source_fetched_at"))
    if not re.fullmatch(r"[0-9TZ-]+_[a-f0-9]{8}", payload.get("run_id", "")):
        raise ValueError("run")
    content = base64.b64decode(payload["ics_base64"], validate=True)
    if not content or len(content) > MAX_BODY or digest(content) != payload["sha256"]:
        raise ValueError("content")
    validate_calendar(content.decode('utf-8'), payload.get('event_count'))
    return {k: payload[k] for k in (
        "schema", "run_id", "source_fetched_at", "sha256", "event_count", "ics_base64")}


def atomic_json(path, obj):
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("x", encoding="utf-8") as out:
            json.dump(obj, out, separators=(",", ":"))
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def read(self):
        path = self.directory / "current.json"
        if not path.exists():
            return None
        return validate(json.loads(path.read_text(encoding="utf-8")))

    def commit(self, incoming):
        new = validate(incoming)
        with self.lock:
            old = self.read()
            if old:
                earlier = timestamp(new["source_fetched_at"]) < timestamp(old["source_fetched_at"])
                same_time = timestamp(new["source_fetched_at"]) == timestamp(old["source_fetched_at"])
                if earlier or (same_time and new["sha256"] != old["sha256"]):
                    return 409, old
                if new == old:
                    return 200, old
                atomic_json(self.directory / "previous.json", old)
            atomic_json(self.directory / "current.json", new)
            return 200, new


def metadata(state):
    return {key: value for key, value in state.items() if key != "ics_base64"}


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, config, store):
        self.config, self.store = config, store
        super().__init__(address, Handler)

    def handle_error(self, request, client_address):
        # Neither paths (read capability) nor headers (write capability) go to logs.
        print("calendar request failed", flush=True)


class Handler(BaseHTTPRequestHandler):
    server_version = "Calendar"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def log_message(self, *args):
        pass

    def authorized(self, token, field):
        expected = self.server.config[field]
        return bool(token) and hmac.compare_digest(digest(token.encode()), expected)

    def writer(self):
        auth = self.headers.get("Authorization", "")
        return auth.startswith("Bearer ") and self.authorized(auth[7:], "write_sha256")

    def reply(self, status, data=b"", content_type="application/json; charset=utf-8", etag=None):
        if isinstance(data, dict):
            data = json.dumps(data, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "private, no-cache, max-age=0")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", str(len(data)))
        if etag:
            self.send_header("ETag", etag)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def do_GET(self):
        status_route = self.path == "/status" and self.writer()
        match = re.fullmatch(r"/([A-Za-z0-9_-]{43})/calendar\.ics", self.path)
        reader = bool(match) and self.authorized(match[1], "read_sha256")
        if not (status_route or reader):
            self.reply(404)
            return
        try:
            state = self.server.store.read()
            if state is None:
                self.reply(503, {"error": "not_published"})
                return
            if status_route:
                self.reply(200, metadata(state))
                return
            etag = '"' + state["sha256"] + '"'
            if self.headers.get("If-None-Match") == etag:
                self.reply(304, etag=etag)
            else:
                self.reply(200, base64.b64decode(state["ics_base64"]), "text/calendar; charset=utf-8", etag)
        except Exception:
            self.reply(503, {"error": "storage_unavailable"})

    do_HEAD = do_GET

    def do_PUT(self):
        if self.path != "/upload" or not self.writer():
            # Drain bounded rejected bodies so the response is not lost to a TCP reset.
            try:
                rejected_length = int(self.headers.get("Content-Length", "0"))
                if 0 < rejected_length <= MAX_BODY:
                    self.rfile.read(rejected_length)
            except (ValueError, OSError):
                pass
            self.reply(404)
            return
        if self.headers.get("Transfer-Encoding"):
            self.reply(400)
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            length = -1
        if not 0 < length <= MAX_BODY:
            self.reply(413)
            return
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            self.reply(415)
            return
        try:
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("incomplete")
            payload = validate(json.loads(body))
        except Exception:
            self.reply(400, {"error": "invalid_calendar"})
            return
        try:
            status, state = self.server.store.commit(payload)
            self.reply(status, metadata(state))
        except Exception:
            self.reply(503, {"error": "storage_unavailable"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    for field in ("read_sha256", "write_sha256"):
        if not re.fullmatch(r"[a-f0-9]{64}", config.get(field, "")):
            raise SystemExit("invalid credential hash")
    if config["read_sha256"] == config["write_sha256"]:
        raise SystemExit("read and write credentials must differ")
    server = Server(("127.0.0.1", 18443), config, Store(args.data))
    print("calendar backend ready on loopback", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
