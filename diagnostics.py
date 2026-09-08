"""Bounded, local diagnostic records. Only de-identified values reach disk.

Only standard-library platform helpers are imported, so startup failures can use it.
Support material is evidence, never a timetable accepted by the import service.
"""
from __future__ import annotations

import functools
import hashlib
import hmac
import html
import json
import os
import platform
import re
import secrets
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from platform_support import default_data_root, select_data_root

APP_VERSION = '1.0.0-rc12'
MAX_DISK = 50 * 1024 * 1024
MAX_MATERIAL = 8 * 1024 * 1024
MAX_INPUT = 20_000_000
MAX_EVENTS = 2000
MAX_RECORD = 2 * 1024 * 1024
RETENTION_SECONDS = 30 * 86400
SAFE_TIME = re.compile(r'(?:\d{4}-\d{2}-\d{2}(?:(?:T| )\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:\d{2})?)?|\d{2}:\d{2}(?::\d{2})?)')
ORIGIN = 'https://jwstu.shsmu.edu.cn'
ENDPOINTS = {'/Home', '/Home/GetCurriculumTable', '/Home/GetCalendarTable'}
OWN_FILE = re.compile(r'[a-f0-9]{32}\.(?:record|material)\.(?:json|tmp)')
SECRET = re.compile(r'password|passwd|cookie|token|authorization|secret|session|csrf|ticket|student|account|tel|phone|mobile|email|worknumber|videolink', re.I)
CONTAINERS = set(('config scope responses response params items event details events cancelled_events '
    'coverage source_ids combined_class input previous committed bundle slots timetable '
    'failure request request_log diagnostics current_response checks').split())
IDENTIFIERS = set(('ID DetailID TeachingCalendarID CurriculumID CSID XXKMID ScheduleManagerID HeBanID '
    'MCSID CurriculumScheduleIDs source_id course_id schedule_manager_id detail_ids '
    'teaching_event_ids teaching_calendar_ids').split())
TEXT = set(('Curriculum CurriculumType CourseCode ClassroomAcademy Classroom Teacher Content Bz '
    'ClassCode GroupName course_name course_code course_type location teacher content notes').split())
DATES = set(('Start End ClassTime start end end_exclusive date start_time end_time end_date '
    'fetched_at started_at observed_at capture_fetched_at synced_at created_at modified_at '
    'last_seen_at cancelled_at recorded_at first_monday course_start course_end').split())
COUNTS = set(('CourseCount ClassHour WeekNum sequence schema_version request_count source_count '
    'in_range_count event_count attempt duration_ms body_length elapsed_ms index count size '
    'ADDED REMOVED CHANGED errno winerror line').split())
BOOLEANS = set(('AllDay IsDel complete duplicate custom_times truncated exists readable ready '
    'matched download_attempted download_observed new_term export_only cancelled success').split())
CODES = set(('DATA_VALIDATION EMPTY_DETAILS HOMEPAGE_REQUIRED BROWSER_UNSUPPORTED SOURCE NETWORK '
    'TIMEOUT REDIRECT RATE_LIMIT ACCESS HTTP SIZE NON_JSON VALIDATION FILE_IO UNEXPECTED_EXCEPTION '
    'CANCELLED JSON_INVALID TOO_LARGE MATERIAL_UNAVAILABLE BROWSER_TRACE_MISSING '
    'BROWSER_METADATA_INVALID DOWNLOAD_NOT_OBSERVED MATERIAL_LIMIT EVENT_LIMIT WRITE_FAILED '
    'INCOMPLETE_RECORD UNKNOWN OMITTED_FIELDS DOWNLOAD_FAILED').split())
LOCATIONS = {('core.py', '_event_details'): 'MIXED_DETAILS', ('core.py', '_combined_class'): 'COMBINED_DETAILS',
    ('core.py', '_combined_periods'): 'COMBINED_PERIODS', ('core.py', 'normalize_one'): 'NORMALIZATION',
    ('core.py', 'reconcile'): 'RECONCILE', ('source.py', '__init__'): 'CAPTURE_VALIDATION',
    ('sync.py', 'exclusive_sync'): 'SYNC_LOCKED', ('sync.py', 'load_current'): 'CURRENT_SNAPSHOT',
    ('sync.py', 'wait_capture'): 'WAIT_CAPTURE', ('sync.py', 'import_capture_unlocked'): 'IMPORT_VALIDATION',
    ('wakeup.py', 'build_export'): 'WAKEUP_VALIDATION', ('wakeup.py', 'detail_slots'): 'SLOT_VALIDATION'}
CODES.update(LOCATIONS.values())


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def notify(observer, event, **context):
    """Diagnostics can never change a transaction's outcome."""
    if observer is not None:
        try:
            observer(event, **context)
        except Exception:
            pass


class Redactor:
    def __init__(self):
        self.key = secrets.token_bytes(32)
        self.offset = secrets.randbelow(800_000_000) + 100_000_000
        self.omitted = False

    def alias(self, value):
        return hmac.new(self.key, str(value).encode('utf-8', errors='replace'), hashlib.sha256).hexdigest()

    def text(self, value):
        # Preserve the whitespace/markup used by core.clean, without retaining words.
        value = re.sub(r'[A-Za-z]:[\\/]\S+|\\\\\S+', '[路径]', str(value))
        value = html.unescape(value)
        def word(match):
            return '文' + self.alias(match[0])[:16].translate(str.maketrans('0123456789abcdef', 'abcdefghijklmnop'))
        fragments = re.split(r'(<br\s*/?>|</?(?:p|div)>|<<|>>)', value, flags=re.I)
        return ''.join(fragment if re.fullmatch(r'<br\s*/?>|</?(?:p|div)>|<<|>>', fragment, re.I)
                       else re.sub(r'\w+', word, fragment, flags=re.UNICODE) for fragment in fragments)

    def identifier(self, value):
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, list):
            return [self.identifier(v) for v in value]
        if isinstance(value, int):
            return value + self.offset if value > 0 else value
        if isinstance(value, str):
            # Keep numeric equality/order and delimiter grammar across all ID fields.
            return re.sub(r'\d+|[^\d,|\s-]+', lambda m:
                ('0' * (len(m[0]) - len(m[0].lstrip('0'))) + str(int(m[0]) + self.offset))
                if m[0].isdigit() and int(m[0]) > 0 else (m[0] if m[0].isdigit() else self.text(m[0])), value)
        return self.shape(value)

    @staticmethod
    def shape(value):
        return {'omitted_type': type(value).__name__, 'count': len(value) if isinstance(value, (str, list, dict)) else 1}

    def clean(self, value, field='', depth=0):
        if depth > 35:
            return {'omitted_type': 'depth_limit'}
        if field in IDENTIFIERS:
            return self.identifier(value)
        if field == 'account_key':
            if isinstance(value, str):
                return self.alias(value) if re.fullmatch(r'[a-f0-9]{64}', value) else self.text(value)
            return value if value is None or isinstance(value, bool) else self.shape(value)
        if field in ('uid', 'capture_hash'):
            return self.alias(value) if isinstance(value, str) else self.shape(value)
        if field == 'identity_aliases':
            result = []
            for alias in value if isinstance(value, list) else []:
                try:
                    namespace, rest = alias.split(':', 1)
                    kind, course, manager, source = rest.rsplit(':', 3)
                    if namespace not in ('slot', 'detail', 'teaching-event', 'main'):
                        raise ValueError()
                    result.append(':'.join([namespace, self.text(kind), self.identifier(course),
                                            self.identifier(manager), self.identifier(source)]))
                except (ValueError, AttributeError):
                    result.append('invalid-alias')
            return result
        if field in TEXT:
            return self.text(value) if isinstance(value, str) else (value if value is None else self.shape(value))
        if field in DATES:
            if value is None or value == '' or isinstance(value, str) and SAFE_TIME.fullmatch(value):
                return value
            return 'invalid-date' if isinstance(value, str) else self.shape(value)
        if field in ('PKCIndex', 'KCIndex'):
            return value if isinstance(value, str) and re.fullmatch(r'[0-9|, \t-]{0,200}', value) else self.shape(value)
        if field == 'periods':
            return [v if type(v) is int and 1 <= v <= 14 else self.shape(v) for v in value] if isinstance(value, list) else self.shape(value)
        if field in COUNTS:
            return value if value is None or type(value) in (bool, int, float) and abs(value) <= 100_000_000 else self.shape(value)
        if field in BOOLEANS:
            return value if value is None or isinstance(value, bool) else self.shape(value)
        if field == 'semester':
            return value if isinstance(value, str) and re.fullmatch(r'\d{4}-\d{4}:\d', value) else 'invalid-semester'
        if field == 'Title':
            if value is None or value == '':
                return value
            match = re.search(r'(\d{4}-\d{4})\s*学年\s*第\s*(\d+)\s*学期', str(value))
            return f'{match[1]} 学年 第{match[2]} 学期' if match else 'invalid-title'
        if field in ('collector_revision', 'app_version'):
            return value if isinstance(value, str) and re.fullmatch(r'[0-9.rc-]{0,40}', value) else 'unknown'
        if field in ('origin', 'source'):
            return value if isinstance(value, str) and value in {ORIGIN, ORIGIN + '/Home/GetCurriculumTable'} else 'unverified-origin'
        if field == 'path':
            return value if isinstance(value, str) and value in ENDPOINTS else 'unverified-endpoint'
        if field == 'format':
            if value == 'shsmu-capture-v1':
                return 'shsmu-support-capture-v1'
            return value if value in ('shsmu-capture-v1', 'shsmu-diagnostic-v1', 'shsmu-browser-support-v1') else 'unknown-format'
        if field in ('code', 'error_code'):
            return value if isinstance(value, str) and value in CODES else 'UNKNOWN'
        if field in ('state', 'status', 'transport', 'identity_basis', 'timezone', 'range_mode', 'browser'):
            allowed = {'start', 'success', 'failure', 'retry', 'fetch', 'xhr', 'CONFIRMED', 'CANCELLED',
                       'slot', 'detail', 'teaching-event', 'main', 'Asia/Shanghai', 'custom',
                       'school_calendar', 'Chrome', 'Edge', 'Firefox', 'Safari', 'unknown'}
            if type(value) is int and 0 <= value <= 599:
                return value
            return value if isinstance(value, str) and value in allowed else 'unknown'
        if field == 'attempt_id':
            return self.alias(value)
        if field == 'content_type':
            return value.split(';')[0] if isinstance(value, str) and value.split(';')[0] in (
                'application/json', 'text/html', 'text/plain') else 'other'
        if field == 'stage':
            return value if value in ('homepage', 'month', 'details', 'download', 'collect') else 'unknown'
        if field in ('List2', 'StuExam'):
            return [] if value == [] else (None if value is None else self.shape(value))
        if field == 'slots':
            return [[v if isinstance(v, str) and re.fullmatch(r'\d{2}:\d{2}(?::\d{2})?', v) else self.shape(v)
                     for v in pair] if isinstance(pair, list) else self.shape(pair)
                    for pair in value[:50]] if isinstance(value, list) else self.shape(value)
        if isinstance(value, list):
            if len(value) > 10000:
                self.omitted = True
            return [self.clean(v, depth=depth + 1) for v in value[:10000]]
        if not isinstance(value, dict):
            return value if value is None else self.shape(value)
        result, omitted = {}, 0
        fields = CONTAINERS | IDENTIFIERS | TEXT | DATES | COUNTS | BOOLEANS | {
            'account_key', 'uid', 'capture_hash', 'identity_aliases', 'PKCIndex', 'KCIndex', 'periods',
            'semester', 'Title', 'collector_revision', 'app_version', 'origin', 'source',
            'path', 'format', 'code', 'error_code', 'state', 'status', 'transport',
            'identity_basis', 'timezone', 'range_mode', 'browser', 'attempt_id',
            'content_type', 'stage', 'List', 'List2', 'StuExam'}
        for key, item in value.items():
            if key not in fields or SECRET.search(key) and key != 'account_key':
                omitted += 1
                continue
            result[key] = self.clean(item, key, depth + 1)
        if omitted:
            self.omitted = True
            result['omitted_fields'] = omitted
        return result


def recorded(kind):
    def decorate(method):
        @functools.wraps(method)
        def call(self, *args, **kwargs):
            # A disconnected data root must not be recreated by logging before
            # the operation's own availability check has selected fallback logs.
            guard = getattr(self, 'require_available', None)
            try:
                if guard is not None:
                    guard()
            except Exception as error:
                self.diagnostics.begin(kind)
                self.diagnostics.exception(error)
                self.diagnostics.finish('failed')
                raise
            log = self.diagnostics
            log.begin('export' if kwargs.get('export_only') else kind)
            try:
                result = method(self, *args, **kwargs)
            except Exception as error:
                log.exception(error)
                log.finish('cancelled' if type(error).__name__ == 'SyncCancelled' else 'failed')
                raise
            log.finish('partial' if isinstance(result, dict) and (result.get('issue') or result.get('apple_issue')) else 'success')
            return result
        return call
    return decorate


class DiagnosticRecorder:
    def __init__(self, root, *, max_disk=MAX_DISK, memory_only=False):
        self.directory = Path(root) / 'local/diagnostics'
        self.memory_only = memory_only
        self.max_disk = max_disk
        self.lock = threading.RLock()
        self.record = None
        self.material = {}
        self.redactor = Redactor()
        self.storage_warning = False
        self.started = time.monotonic()

    def begin(self, kind):
        try:
            with self.lock:
                self.redactor = Redactor()
                self.material = {}
                self.started = time.monotonic()
                self.record = {'format': 'shsmu-support-v1', 'schema_version': 1,
                    'operation_id': uuid.uuid4().hex, 'app_version': APP_VERSION,
                    'kind': kind, 'started_at': utc_now(), 'status': 'running',
                    'environment': {'os': platform.system(), 'os_release': platform.release(),
                                    'os_version': platform.version(), 'architecture': platform.machine(),
                                    'python': platform.python_version(), 'frozen': bool(getattr(__import__('sys'), 'frozen', False))},
                    'events': [], 'limitations': []}
                self.prune()
                self.event('operation_started')
        except Exception:
            self.storage_warning = True

    def _write(self, suffix, value):
        if self.memory_only:
            raise OSError('Diagnostic storage is unavailable')
        self.directory.mkdir(parents=True, exist_ok=True)
        destination = self.directory / (self.record['operation_id'] + suffix)
        # No arbitrary path or temporary files are included in a support export.
        temporary = destination.with_suffix('.tmp')
        data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
        try:
            with temporary.open('wb') as handle:
                handle.write(data)
                handle.flush()
            os.replace(temporary, destination)
        finally:
            try:
                if temporary.is_file():
                    temporary.unlink()
            except OSError:
                pass

    def _persist(self, material=False):
        try:
            if material:
                self._write('.material.json', self.material)
            self._write('.record.json', self.record)
            self.prune()
        except Exception:
            self.storage_warning = True
            if self.record and 'WRITE_FAILED' not in self.record['limitations']:
                self.record['limitations'].append('WRITE_FAILED')

    def event(self, name, **context):
        try:
            with self.lock:
                if self.record is None:
                    self.begin('activity')
                if len(self.record['events']) >= MAX_EVENTS:
                    if 'EVENT_LIMIT' not in self.record['limitations']:
                        self.record['limitations'].append('EVENT_LIMIT')
                    self._persist()
                    if name == 'operation_finished' or 'failed' in name or name == 'exception':
                        self.record['events'].pop()
                    else:
                        return
                # Names originate in program call sites, never in school responses.
                cleaned = self.redactor.clean(context)
                if len(json.dumps(cleaned, ensure_ascii=False)) > 64000:
                    cleaned = {'code': 'EVENT_LIMIT', 'truncated': True}
                if len(json.dumps(self.record, ensure_ascii=False).encode('utf-8')) > MAX_RECORD - 256000:
                    if 'EVENT_LIMIT' not in self.record['limitations']:
                        self.record['limitations'].append('EVENT_LIMIT')
                    self._persist()
                    return
                self.record['events'].append({'recorded_at': utc_now(), 'event': name,
                    'elapsed_ms': round((time.monotonic() - self.started) * 1000),
                    'context': cleaned})
                self._persist()
        except Exception:
            self.storage_warning = True

    def exception(self, error, *, stage=None):
        try:
            code = ('CANCELLED' if type(error).__name__ == 'SyncCancelled' else
                    'VALIDATION' if type(error).__name__ in ('DataError', 'SourceError', 'LoginRequired') else
                    'FILE_IO' if isinstance(error, OSError) else 'UNEXPECTED_EXCEPTION')
            frames, tb = [], error.__traceback__
            while tb is not None:
                module = Path(tb.tb_frame.f_code.co_filename).name
                frames.append({'file': module, 'function': tb.tb_frame.f_code.co_name, 'line': tb.tb_lineno})
                tb = tb.tb_next
            if frames and code == 'VALIDATION':
                code = LOCATIONS.get((frames[-1]['file'], frames[-1]['function']), code)
            with self.lock:
                self.event(stage or 'exception', error_code=code, errno=getattr(error, 'errno', None),
                           winerror=getattr(error, 'winerror', None), index=getattr(error, 'diagnostic_index', None),
                           checks=getattr(error, 'diagnostic_checks', None))
                self.record['events'][-1]['exception'] = {'type': type(error).__name__,
                    'code': code, 'frames': frames[-24:]}
                self._persist()
        except Exception:
            self.storage_warning = True

    def finish(self, status):
        try:
            with self.lock:
                self.record.update(status=status, finished_at=utc_now())
                self.event('operation_finished')
                self._persist()
                self.prune()
        except Exception:
            self.storage_warning = True

    def attach(self, name, value):
        try:
            with self.lock:
                cleaned = self.redactor.clean(value, 'slots' if name == 'slots' else '')
                proposed = {**self.material, name: cleaned}
                if len(json.dumps(proposed, ensure_ascii=False).encode('utf-8')) > MAX_MATERIAL:
                    self.event('material_omitted', code='MATERIAL_LIMIT')
                    if 'MATERIAL_LIMIT' not in self.record['limitations']:
                        self.record['limitations'].append('MATERIAL_LIMIT')
                else:
                    self.material = proposed
                if self.redactor.omitted and 'OMITTED_FIELDS' not in self.record['limitations']:
                    self.record['limitations'].append('OMITTED_FIELDS')
                self._persist(material=True)
                self.prune()
        except Exception:
            self.storage_warning = True

    def attach_file(self, name, path):
        reason = 'MATERIAL_UNAVAILABLE'
        try:
            path = Path(path)
            size = path.stat().st_size
            self.event('file_observed', size=size)
            if size > MAX_INPUT:
                reason = 'TOO_LARGE'
                raise ValueError()
            try:
                value = json.loads(path.read_text(encoding='utf-8-sig'))
            except (ValueError, UnicodeError):
                reason = 'JSON_INVALID'
                raise
            self.attach(name, value)
            if name == 'input':
                code = ('BROWSER_TRACE_MISSING' if not isinstance(value, dict) or 'diagnostics' not in value else
                        'BROWSER_METADATA_INVALID' if not isinstance(value['diagnostics'], dict) else None)
                if code:
                    self.record['limitations'].append(code)
                    self.event('browser_metadata_missing', code=code)
                else:
                    self.event('browser_metadata_received')
        except Exception as error:
            with self.lock:
                if self.record is None:
                    self.begin('activity')
                if reason not in self.record['limitations']:
                    self.record['limitations'].append(reason)
                self.event('material_unavailable', code=reason)
                self.exception(error, stage='material_read_failed')

    def observe(self, event, **context):
        if event == 'browser_diagnostic_file':
            self.attach_file('browser', context.pop('diagnostic_path'))
        for name in ('previous', 'input', 'bundle'):
            if name in context:
                self.attach(name, context.pop(name))
        self.event(event, **context)

    def capture_committed(self, root):
        try:
            pointer = json.loads((Path(root) / 'data/current.json').read_text(encoding='utf-8'))
            run_id = pointer['run_id']
            if not isinstance(run_id, str) or not re.fullmatch(r'[0-9TZ-]+_[a-f0-9]{8}', run_id):
                raise ValueError()
            self.attach_file('committed', Path(root) / 'data/runs' / run_id / 'schedule.json')
            self.attach_file('bundle', Path(root) / 'data/runs' / run_id / 'capture.json')
            slot_path = Path(root) / 'local/wakeup-slots.json'
            if slot_path.is_file():
                self.attach_file('slots', slot_path)
        except Exception as error:
            if self.record and 'MATERIAL_UNAVAILABLE' not in self.record['limitations']:
                self.record['limitations'].append('MATERIAL_UNAVAILABLE')
            self.exception(error, stage='committed_material_unavailable')

    def accept_browser_text(self, text):
        if len(text.encode('utf-8')) > MAX_INPUT:
            raise ValueError('诊断文本过大，请选择较小的诊断文件。')
        try:
            value = json.loads(text)
        except (ValueError, UnicodeError):
            raise ValueError('请粘贴网页“复制排错信息”显示的完整 JSON。') from None
        if not isinstance(value, dict) or value.get('format') not in ('shsmu-diagnostic-v1', 'shsmu-browser-support-v1'):
            raise ValueError('这不是浏览器排错信息。')
        self.event('browser_diagnostic_attached')
        self.attach('browser', value)

    def _owned(self):
        if self.memory_only:
            return []
        try:
            if not self.directory.is_dir():
                return []
            return [p for p in self.directory.iterdir() if OWN_FILE.fullmatch(p.name)
                    and p.is_file() and not p.is_symlink() and p.resolve().parent == self.directory.resolve()]
        except OSError:
            self.storage_warning = True
            return []

    def prune(self):
        try:
            owned = sorted(self._owned(), key=lambda p: p.stat().st_mtime)
            total = sum(p.stat().st_size for p in owned)
            current = self.record['operation_id'] if self.record else ''
            for path in owned:
                if current and path.name.startswith(current):
                    continue
                stat = path.stat()
                if total > self.max_disk or time.time() - stat.st_mtime > RETENTION_SECONDS:
                    total -= stat.st_size
                    path.unlink()  # One verified, logger-owned file at a time.
        except OSError:
            self.storage_warning = True

    def records(self):
        with self.lock:
            result = {}
            for path in self._owned():
                if not path.name.endswith('.record.json'):
                    continue
                try:
                    if path.stat().st_size > MAX_RECORD:
                        continue
                    value = json.loads(path.read_text(encoding='utf-8'))
                    if (not isinstance(value, dict) or not isinstance(value.get('operation_id'), str)
                            or value['operation_id'] + '.record.json' != path.name or value.get('format') != 'shsmu-support-v1'
                            or not all(isinstance(value.get(k), str) for k in ('started_at', 'status', 'app_version', 'kind'))
                            or not all(isinstance(value.get(k), list) for k in ('events', 'limitations'))):
                        continue
                    if value.get('status') == 'running':
                        value['status'] = 'interrupted'
                    result[value['operation_id']] = value
                except (ValueError, OSError, TypeError):
                    continue
            if self.record:
                result[self.record['operation_id']] = json.loads(json.dumps(self.record))
            return sorted(result.values(), key=lambda v: v.get('started_at', ''), reverse=True)

    def export(self, destination, operation_id=None, *, browser_text=''):
        """Only owned, already-redacted records; never copy a directory/archive."""
        destination = Path(destination)
        with self.lock:
            records = self.records()
            if not records:
                raise ValueError('暂时没有排错记录，请先进行一次操作。')
            selected = next((v for v in records if v['operation_id'] == operation_id), None) if operation_id else records[0]
            if selected is None:
                raise ValueError('这条记录已轮换，请选择仍可用的记录。')
            selected = json.loads(json.dumps(selected))
            if self.record and selected['operation_id'] == self.record['operation_id']:
                material = json.loads(json.dumps(self.material))
            else:
                path = self.directory / (selected['operation_id'] + '.material.json')
                try:
                    material = json.loads(path.read_text(encoding='utf-8')) if path in self._owned() and path.stat().st_size <= MAX_MATERIAL else {}
                    if not isinstance(material, dict):
                        material = {}
                except (OSError, ValueError):
                    material = {}
            if not material:
                selected['limitations'].append('MATERIAL_UNAVAILABLE')
            if browser_text.strip():
                if len(browser_text.encode('utf-8')) > MAX_INPUT:
                    raise ValueError('补充诊断信息过大。')
                try:
                    extra = json.loads(browser_text)
                except ValueError:
                    raise ValueError('补充信息不是完整 JSON，请重新复制网页排错信息。') from None
                if not isinstance(extra, dict) or extra.get('format') not in ('shsmu-diagnostic-v1', 'shsmu-browser-support-v1'):
                    raise ValueError('补充信息不是浏览器排错信息。')
                supplement_redactor = Redactor()
                supplement = supplement_redactor.clean(extra)
                proposed = {**material, 'browser_supplement': supplement}
                if len(json.dumps(proposed, ensure_ascii=False).encode('utf-8')) > MAX_MATERIAL:
                    selected['limitations'].append('MATERIAL_LIMIT')
                else:
                    material = proposed
                if supplement_redactor.omitted:
                    selected['limitations'].append('OMITTED_FIELDS')
            if selected['status'] in ('running', 'interrupted'):
                selected['limitations'].append('INCOMPLETE_RECORD')
            summary = '\n'.join(['医学院课表助手排错日志', '版本：' + selected['app_version'],
                '操作编号：' + selected['operation_id'], '开始时间：' + selected['started_at'],
                '操作：' + selected['kind'], '结果：' + selected['status'],
                '材料限制：' + (', '.join(sorted(set(selected['limitations']))) or '无已知缺失'),
                '', '姓名、学号、课程文字及标识已经替换，仍含日期和节次；请仅发给维护者。',
                '材料用于排错，不能导入手机或替换个人课表。异常位置不是对根因的自动判定。',
                '浏览器下载发起不代表文件已落盘；电脑导出不代表手机导入成功。', ''])
            manifest = {k: v for k, v in selected.items() if k != 'events'}
            payloads = {'summary.txt': summary.encode('utf-8-sig'),
                'manifest.json': json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8'),
                'events.jsonl': ('\n'.join(json.dumps(v, ensure_ascii=False) for v in selected['events']) + '\n').encode('utf-8'),
                'repro.json': json.dumps({'format': 'shsmu-support-v1', 'material': material}, ensure_ascii=False).encode('utf-8')}
        temporary = destination.with_name(destination.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with zipfile.ZipFile(temporary, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
                for name, data in payloads.items():
                    archive.writestr(name, data)
            with zipfile.ZipFile(temporary) as archive:
                if archive.testzip() is not None or any(archive.read(k) != v for k, v in payloads.items()):
                    raise OSError('排错包写入后校验失败。')
            os.replace(temporary, destination)
        finally:
            if temporary.is_file():
                temporary.unlink()
        return destination


def install_startup_hook():
    """Only called by the executable/script entry, before optional imports."""
    import sys
    base = default_data_root()
    explicit = None
    try:
        if '--data-root' in sys.argv:
            explicit = sys.argv[sys.argv.index('--data-root') + 1]
    except IndexError:
        pass
    root, issue = select_data_root(base, explicit)
    log = DiagnosticRecorder(base if issue else root)
    def handle(kind, error, tb):
        log.begin('startup')
        log.exception(error)
        log.finish('failed')
        try:
            from tkinter import messagebox
            messagebox.showerror('助手未能启动', '启动错误已尽力记录。重新打开助手后可在“遇到问题”导出排错日志。\n日志目录：' + str(log.directory))
        except Exception:
            pass
    sys.excepthook = handle
    threading.excepthook = lambda args: handle(args.exc_type, args.exc_value, args.exc_traceback)
