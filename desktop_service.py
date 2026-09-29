"""Local-only desktop workflow. No browser control, uploads, or GUI dependencies."""
from __future__ import annotations

import hashlib
import json
import queue
import threading
from dataclasses import dataclass
from pathlib import Path

from core import DataError, content_hash, export_ics
from prepare import BROWSER_MODULES, build_bookmark
from source import SourceError
from sync import (SyncCancelled, atomic_write, capture_folder, check_cancelled,
                  exclusive_sync, import_capture_unlocked, json_bytes, load_current,
                  load_settings, repair_exports, validate_settings, wait_capture)
from wakeup import export_current_unlocked, load_slot_times, slot_times, validate_slot_times
from diagnostics import APP_VERSION, DiagnosticRecorder, recorded
from platform_support import default_data_root

RESOURCE_ROOT = Path(__file__).resolve().parent
HOME_URL = 'https://jwstu.shsmu.edu.cn/Home'


def term_key(config):
    return {key: config[key] for key in ('semester', 'start', 'end_exclusive')}


def student_term_config(config):
    """A verified calendar bounds collection, never a student's last class.

    The published 2026-27 SHSMU calendar has spring starting 2027-02-22.
    Include the intervening winter break, without crossing into spring.
    Other terms and explicit custom ranges need their own verified bounds.
    Source: https://www.shsmu.edu.cn/jwc/info/1066/5704.htm
    """
    result = dict(config)
    if (config.get('range_mode') != 'custom' and config['semester'] == '2026-2027:1'
            and config['start'] == '2026-09-07'
            and config['end_exclusive'] in ('2027-01-18', '2027-02-22')):
        result.update(end_exclusive='2027-02-22', range_mode='school_calendar')
    return result


@dataclass
class UserIssue:
    title: str
    next_step: str
    detail: str


def explain_error(error, *, exporting=False, apple=False):
    known = isinstance(error, (DataError, SourceError, SyncCancelled))
    detail = str(error) if known else type(error).__name__
    title, action = '本次操作未完成', '请重试，或在“帮助与排错”中选择已下载的课表。需要协助时，可导出排错日志。'
    if exporting and apple:
        title, action = '苹果日历文件未就绪', '请点击“重新生成导入文件”，使用已保存的课表重新生成。'
    elif exporting:
        title, action = 'WakeUp 文件未就绪', '请检查“设置 → 作息时间”，再重新生成导入文件。仍有问题时，查看处理详情。'
    elif isinstance(error, SyncCancelled):
        title, action = '操作已取消', '可以重新获取课表，或选择已下载的课表文件。已保存的课表不会因此删除。'
    elif '另一个同步程序' in detail:
        title, action = '另一窗口正在处理课表', '请等待另一窗口完成操作，或将其关闭后重试。'
    elif '数据目录' in detail:
        title, action = '无法访问原课表文件夹', '请在“设置 → 文件夹”中重新选择原文件夹。助手不会自动迁移或重置原记录。'
    elif '账号' in detail or '匿名校验标识' in detail:
        title, action = '登录账号与当前课表不一致', '请在浏览器登录原账号。其他同学使用时，请为其选择独立的空文件夹。'
    elif '诊断文件' in detail:
        title, action = '选中的是排错文件，不是课表', '请在教务网页完成读取，再选择 shsmu-capture- 开头的 JSON 文件。'
    elif '更旧' in detail:
        title, action = '所选文件早于当前课表', '请选择最新下载的课表文件；当前课表未回退。'
    elif '整个学期返回空课表' in detail:
        # Usually a login/account issue, not the term setting: keep this before '学期'.
        title, action = '没有读取到任何课程', '请在浏览器确认已登录本人账号，并能在“我的课表”看到课程；再核对学期日期范围后重新获取。已保存的课表没有被清空。'
    elif '数据分支' in detail:
        title, action = '学校返回了尚未支持的数据', '已停止并保留原课表。请导出排错日志发给维护者。'
    elif any(word in detail for word in ('学期', '配置文件', 'semester', 'start、end_exclusive')):
        title, action = '课表与学期设置不一致', '请在“设置 → 学期”中核对学期和日期范围，再更新浏览器书签。'
    elif '等待结束' in detail:
        title, action = '尚未收到课表文件', '已下载文件时，点击“选择已下载的课表”。尚未下载时，请检查浏览器提示或下载文件夹后重试。'
    elif '下载目录不存在' in detail:
        title, action = '找不到下载文件夹', '点击“选择下载文件夹”，选择浏览器实际保存文件的位置。'
    elif '无法读取下载文件夹' in detail:
        title, action = '无法读取下载文件夹', '请检查该文件夹的访问权限，或点“选择已下载的课表”手动选择 JSON；也可选择其他下载文件夹。'
    elif '详情为空' in detail:
        title, action = '学校返回的课程详情不完整', '请在教务首页重新读取课表。不完整结果不会替换已保存的课表。'
    elif known and ('JSON' in detail or '采集文件' in detail):
        title, action = '课表文件暂不可用', '请确认下载已完成；必要时在教务网页重新下载课表文件，再回助手选择。'
    elif '没有已提交' in detail:
        title, action = '尚未保存课表', '请先返回首页，点击“获取课表”。'
    elif not known and isinstance(error, (ValueError, KeyError)):
        # Not a downloaded capture: an unreadable saved record (e.g. JSONDecodeError).
        title, action = '已保存的课表记录无法读取', '请保留课表文件夹，导出排错日志发给维护者；不要删除或重建原记录。'
    if isinstance(error, OSError):
        if getattr(error, 'winerror', None) in (5, 32, 33) or isinstance(error, PermissionError):
            title, action = '文件正被其他程序使用或无法写入', '请关闭正在打开 wakeup.csv、calendar.ics 等文件的程序（如 Excel、WPS），再重新生成导入文件；仍失败时请检查文件夹写入权限。'
        else:
            title, action = '文件操作未完成', '请检查磁盘空间和文件夹权限后重试。不要删除原课表文件。'
    reason = _display_reason(error)
    if reason is not None:
        title, action = reason
    return UserIssue(title, action, detail)


def _display_reason(error):
    if not isinstance(error, (DataError, SourceError)):
        return None
    detail = str(error)
    messages = {
        '上次使用的数据目录暂时找不到，请在设置中选择原项目目录；没有新建另一份课表。': ('无法访问原课表文件夹', '原课表文件夹暂时无法访问。请连接原磁盘或检查权限，再选择该文件夹。助手未另建课表。'),
        '自定义作息应依次列出 1–14 节的上课、下课时间；请对照 wakeup-slots.example.json。': ('作息设置不完整', '请填写第 1—14 节的上课和下课时间。'),
        '课程周次无法对应同一个开学日期，或课程未完整转换，未导出。': ('WakeUp 课表校验未通过', '课程未完整转换，或周次与日期无法一致对应。暂不生成 WakeUp 文件，请保留课表并导出排错日志。'),
        '缺少教师详情中的节次，未导出 WakeUp 文件。': ('缺少课程节次信息', '暂不生成 WakeUp 文件。请重新获取课表；仍有问题时导出排错日志。'),
        '教师详情的 PKCIndex 缺失或格式改变，未导出 WakeUp 文件。': ('缺少课程节次信息', '暂不生成 WakeUp 文件。请重新获取课表；仍有问题时导出排错日志。'),
        '发现不连续或超出 1–14 节的课程，需要核对后再导出。': ('课程节次暂不支持', '发现不连续或超出第 1—14 节的课程，暂不生成 WakeUp 文件。请导出排错日志供维护者核对。'),
        '教师详情缺少有效教学周次，未导出 WakeUp 文件。': ('课程周次无法确认', '暂不生成 WakeUp 文件。请重新获取课表，或导出排错日志。'),
        '同一次课程的详情周次冲突，未导出 WakeUp 文件。': ('课程周次无法确认', '暂不生成 WakeUp 文件。请重新获取课表，或导出排错日志。'),
        '原始采集不完整或与当前快照不对应，未导出 WakeUp 文件。': ('已保存课表与原始记录不一致', '暂不生成 WakeUp 文件。请保留原课表和日志，联系维护者处理。'),
        '当前运行缺少完整原始课程，未导出 WakeUp 文件。': ('已保存课表与原始记录不一致', '暂不生成 WakeUp 文件。请保留原课表和日志，联系维护者处理。'),
        '当前有效课程数量与原始采集不一致，未导出 WakeUp 文件。': ('已保存课表与原始记录不一致', '暂不生成 WakeUp 文件。请保留原课表和日志，联系维护者处理。'),
        '当前课程内容与原始采集不一致，未导出 WakeUp 文件。': ('已保存课表与原始记录不一致', '暂不生成 WakeUp 文件。请保留原课表和日志，联系维护者处理。'),
        '原数据目录缺少完整版本索引，请保留目录并恢复索引，不要新建历史。': ('原课表记录不完整', '请保留原文件夹并联系维护者恢复记录，不要在此处重建或覆盖历史。'),
        '导入文件已过期或被移动，请重新生成导入文件。': ('当前导入文件不可用', '请重新生成导入文件后再试。'),
        '苹果日历文件已过期或被移动，请重新生成导入文件。': ('当前导入文件不可用', '请重新生成导入文件后再试。'),
        '尚无对应当前课表的导入文件。': ('当前导入文件不可用', '请重新生成导入文件后再试。'),
        '尚无对应当前课表的苹果日历文件。': ('当前导入文件不可用', '请重新生成导入文件后再试。'),
        '苹果日历文件缺失或与当前课表不一致，请重新生成导入文件。': ('当前导入文件不可用', '请重新生成导入文件后再试。'),
        '文件已变化或不可用，请重新打开 WakeUp 指引并核对后再确认。': ('WakeUp 文件已变化或不可用', '请重新打开“导入与作息设置”，按当前文件完成导入和核对后再确认。'),
        '文件已变化或不可用，请重新打开苹果日历指引并核对后再确认。': ('苹果日历文件已变化或不可用', '请重新打开“查看导入步骤”，按当前文件完成导入和核对后再确认。'),
        '学期设置已经改变，请先获取当前选择学期的课表。': ('学期设置已更改', '请先获取当前所选学期的课表，再生成导入文件。'),
        '苹果日历文件保存后校验失败，请重新生成导入文件。': ('苹果日历文件校验未通过', '本次文件暂不可用，请重新生成导入文件。'),
        '配置必须包含 semester、start、end_exclusive；请对照 config.example.json。': ('学期设置无法使用', '请在“设置 → 学期”中核对学期及日期范围，再保存重试。'),
        'semester 格式应为连续两年的学期，例如 2026-2027:1。': ('学期设置无法使用', '请在“设置 → 学期”中核对学期及日期范围，再保存重试。'),
        '配置文件不是有效的 UTF-8 JSON；请对照 config.example.json 检查双引号、逗号和日期。': ('学期设置无法使用', '请在“设置 → 学期”中核对学期及日期范围，再保存重试。'),
        '无法读取配置文件，请检查 --config 路径和文件权限。': ('学期设置无法使用', '请在“设置 → 学期”中核对学期及日期范围，再保存重试。'),
        '指定的配置文件不存在，请核对 --config 路径。': ('学期设置无法使用', '请在“设置 → 学期”中核对学期及日期范围，再保存重试。'),
    }
    if detail in messages:
        return messages[detail]
    import re
    match = re.fullmatch(r'自定义作息第 (\d+) 节无效；请使用 HH:MM，保证下课晚于上课，且与上一节不重叠。', detail)
    if match:
        return (f'第 {match[1]} 节时间有误',
                '请使用 24 小时制（例如 08:00），确保下课晚于上课，且不与上一节重叠。')
    match = re.fullmatch(
        r'课程起止时间与已选作息表不一致：(\d{4}-\d{2}-\d{2}) 第 (\d+)–(\d+) 节，'
        r'课程为 (\d{2}:\d{2})–(\d{2}:\d{2})，作息为 (\d{2}:\d{2})–(\d{2}:\d{2})。'
        r'未导出；可复制 wakeup-slots\.example\.json 为 local/wakeup-slots\.json，按本人作息修改后重试。', detail)
    if match:
        return ('课程时间与作息设置不一致',
                f'{match[1]} 第 {match[2]}—{match[3]} 节：教务课表为 {match[4]}—{match[5]}，'
                f'当前设置为 {match[6]}—{match[7]}。请修改作息后重新生成 WakeUp 文件。')
    return None


class DesktopService:
    def __init__(self, root, resources=RESOURCE_ROOT, *, recovery_issue=None, diagnostics_root=None):
        self.root = Path(root).absolute() if recovery_issue else Path(root).resolve()
        self.resources = Path(resources)
        self.recovery_issue = recovery_issue
        self._root_identity = None
        self.fallback_diagnostics_root = Path(diagnostics_root or default_data_root())
        self._bookmark_acknowledged = False
        self.diagnostics = DiagnosticRecorder(diagnostics_root or self.root)

    def require_available(self):
        if not self.recovery_issue and self._root_identity is not None:
            try:
                current = self.root.stat()
                if (current.st_dev, current.st_ino) != self._root_identity:
                    raise OSError('data directory was replaced')
            except OSError:
                self.recovery_issue = '使用中的课表目录已断开或被替换。请连接原磁盘并重新选择原目录；没有新建另一份课表。'
                self.diagnostics = DiagnosticRecorder(self.fallback_diagnostics_root,
                    memory_only=self.fallback_diagnostics_root.absolute().is_relative_to(self.root))
        if self.recovery_issue:
            raise DataError(self.recovery_issue)

    def _exclusive(self):
        self.require_available()
        return exclusive_sync(self.root)

    @property
    def config_path(self):
        return self.root / 'config.local.json'

    @property
    def bookmark_path(self):
        return self.root / 'local/desktop-bookmark.html'

    def config(self):
        self.require_available()
        return load_settings(self.config_path)

    def state(self):
        try:
            value = json.loads((self.root / 'local/desktop-state.json').read_text(encoding='utf-8'))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError, UnicodeError):
            return {}

    def save_state(self, **values):
        self.require_available()
        state = self.state()
        state.update(values)
        atomic_write(self.root / 'local/desktop-state.json', json_bytes(state))

    @recorded('startup')
    def initialize(self):
        with self._exclusive():
            if (self.root / 'data/schedule.json').exists() and not (self.root / 'data/current.json').exists():
                raise DataError('原数据目录缺少完整版本索引，请保留目录并恢复索引，不要新建历史。')
            if not self.config_path.exists():
                # Never silently create a new scope on top of an existing history.
                current = load_current(self.root)
                config = term_key(current['scope']) if current else student_term_config(
                    load_settings(self.resources / 'config.example.json'))
                atomic_write(self.config_path, json_bytes(config))
            config = self.config()
            build_bookmark(self.root, config, resources=self.resources, desktop=True,
                           output=self.bookmark_path)
            current = self.root.stat()
            self._root_identity = (current.st_dev, current.st_ino)
            return config

    @recorded('term_settings')
    def confirm_term(self):
        with self._exclusive():
            config = student_term_config(self.config())
            atomic_write(self.config_path, json_bytes(config))
            build_bookmark(self.root, config, resources=self.resources, desktop=True,
                           output=self.bookmark_path)
            self.save_state(confirmed_term=term_key(config))

    @recorded('bookmark_confirmation')
    def acknowledge_bookmark(self):
        with self._exclusive():
            self.save_state(bookmark_ack=self.bookmark_fingerprint())
        self._bookmark_acknowledged = True

    def bookmark_fingerprint(self):
        # Changes only when the actual collector or semester changes, not the UI copy.
        return content_hash({'term': term_key(self.config()), 'modules': [
            hashlib.sha256((self.resources / name).read_bytes()).hexdigest()
            for name in BROWSER_MODULES]})

    def setup_step(self):
        state = self.state()
        if term_key(student_term_config(self.config())) != term_key(self.config()):
            return 1
        if state.get('confirmed_term') != term_key(self.config()):
            return 1
        current = load_current(self.root)
        bookmark_ack = state.get('bookmark_ack')
        if bookmark_ack != self.bookmark_fingerprint():
            # Direct JSON recovery can finish before a bookmark is acknowledged.
            # Keep the acknowledgement absent: importing is not installation.
            # Recorded old fingerprints still require the collector upgrade guide.
            if (bookmark_ack is not None or current is None
                    or term_key(current['scope']) != term_key(self.config())):
                return 2
        # A saved acknowledgement alone must not skip an unfinished first run.
        # Allow collection after confirming in this session; resume the guide on
        # reopening until a complete timetable has actually been saved.
        if not self._bookmark_acknowledged and current is None:
            return 2
        return 0

    @recorded('settings')
    def save_settings(self, config, times=None, *, confirm_term=True):
        self.diagnostics.attach('settings', config)
        if times is not None:
            self.diagnostics.attach('slots', times)
        validate_settings(config)
        if times is not None:
            validate_slot_times(times)
        with self._exclusive():
            # Preserve unrelated CLI settings when editing the shared local config.
            try:
                merged = self.config()
            except DataError:
                merged = {}
            merged.update(config)
            atomic_write(self.config_path, json_bytes(merged))
            if times is not None:
                atomic_write(self.root / 'local/wakeup-slots.json', json_bytes(times))
            build_bookmark(self.root, merged, resources=self.resources, desktop=True,
                           output=self.bookmark_path)
            if confirm_term:
                self.save_state(confirmed_term=term_key(merged))

    def _slot_fingerprint(self):
        custom = load_slot_times(self.root)
        return content_hash({'times': custom if custom is not None else slot_times(), 'custom': custom is not None})

    def _export_unlocked(self):
        # A successful older CSV remains on disk, but is never offered as this result.
        self.save_state(export_ready=False)
        report = export_current_unlocked(self.root)
        pointer = json.loads((self.root / 'data/current.json').read_text(encoding='utf-8'))
        manifest = {'export_version': 2, 'run_id': pointer['run_id'], 'slot_fingerprint': self._slot_fingerprint(),
                    'report': report, 'guide_hash': hashlib.sha256(
                        (self.root / 'output/wakeup导入说明.txt').read_bytes()).hexdigest()}
        atomic_write(self.root / 'local/desktop-export.json', json_bytes(manifest))
        self.save_state(export_ready=True)
        return report

    def ready_export(self):
        """Validate the exact current files before allowing the user to send them."""
        try:
            with self._exclusive():
                if not self.state().get('export_ready'):
                    return None
                current = load_current(self.root)
                if current is None or term_key(current['scope']) != term_key(self.config()):
                    return None
                pointer = json.loads((self.root / 'data/current.json').read_text(encoding='utf-8'))
                manifest = json.loads((self.root / 'local/desktop-export.json').read_text(encoding='utf-8'))
                report = manifest['report']
                if (manifest.get('export_version') != 2
                        or manifest['run_id'] != pointer['run_id'] or manifest['slot_fingerprint'] != self._slot_fingerprint()
                        or report['csv_sha256'] != hashlib.sha256((self.root / 'output/wakeup.csv').read_bytes()).hexdigest()
                        or manifest['guide_hash'] != hashlib.sha256((self.root / 'output/wakeup导入说明.txt').read_bytes()).hexdigest()):
                    return None
                return report
        except (OSError, ValueError, KeyError, TypeError, DataError) as error:
            self.diagnostics.exception(error, stage='wakeup_readiness_failed')
            return None

    def _apple_export_unlocked(self, *, repair=False):
        """Caller holds exclusive_sync. ICS does not depend on WakeUp settings."""
        current = load_current(self.root)
        if current is None:
            raise DataError('没有已提交的完整课表，请先获取课表。')
        if term_key(current['scope']) != term_key(self.config()):
            raise DataError('学期设置已经改变，请先获取当前选择学期的课表。')
        expected = export_ics(current)
        path = self.root / 'output/calendar.ics'
        actual = path.read_bytes() if path.exists() else None
        if actual != expected:
            if not repair:
                raise DataError('苹果日历文件缺失或与当前课表不一致，请重新生成导入文件。')
            atomic_write(path, expected)
            if path.read_bytes() != expected:
                raise DataError('苹果日历文件保存后校验失败，请重新生成导入文件。')
        days = [event['date'] for event in current['events']]
        return {'event_count': len(days), 'course_start': min(days) if days else None,
                'course_end': max(days) if days else None,
                'capture_fetched_at': current.get('capture_fetched_at'),
                'ics_sha256': hashlib.sha256(expected).hexdigest()}

    def ready_apple_export(self):
        """Validate saved ICS before showing a file or accepting phone confirmation."""
        try:
            with self._exclusive():
                return self._apple_export_unlocked()
        except (OSError, ValueError, KeyError, TypeError, DataError) as error:
            self.diagnostics.exception(error, stage='apple_readiness_failed')
            return None

    @recorded('sync')
    def run(self, *, capture=None, export_only=False, cancel=None, choose=None, paused=None,
            emit=lambda stage, value: None):
        """One lock across waiting, import and export. Intentionally never uploads."""
        with self._exclusive():
            config = self.config()
            self.diagnostics.attach('settings', config)
            check_cancelled(cancel)
            self.save_state(export_ready=False)
            imported = None
            output_errors = {}
            if not export_only:
                if capture is None:
                    folder = capture_folder(config, self.config_path)
                    capture = wait_capture(folder, progress=lambda text: emit('waiting', text),
                                           cancel=cancel, choose=choose, paused=paused, observe=self.diagnostics.observe)
                check_cancelled(cancel)
                self.diagnostics.attach_file('input', capture)
                emit('processing', '正在检查课表文件…')
                imported = import_capture_unlocked(self.root, config, Path(capture),
                    new_term=self.state().get('confirmed_term') == term_key(config),
                    progress=lambda text: emit('detail', text), cancel=cancel,
                    on_commit=lambda: emit('committing', '正在保存课表，请稍候…'), observe=self.diagnostics.observe)
                output_errors.update(imported.output_errors)
                try:
                    self.save_state(collector_revision=imported.collector_revision)
                except Exception as error:
                    output_errors['local/desktop-state.json'] = error
            else:
                current = load_current(self.root)
                if current is None:
                    raise DataError('没有已提交的完整课表，请先获取课表。')
                if term_key(current['scope']) != term_key(config):
                    raise DataError('学期设置已经改变，请先获取当前选择学期的课表。')
                repair_exports(self.root, errors=output_errors)
            output_issues = {}
            for target, error in output_errors.items():
                self.diagnostics.exception(error, stage='derived_export_failed')
                # ICS is independently retried/validated below; retain the
                # original failure in diagnostics and ImportResult either way.
                if target != 'output/calendar.ics':
                    output_issues[target] = UserIssue('课表已保存，部分辅助文件未生成',
                        '请点击“重新生成导入文件”，无需重新采集。',
                        f'{target}: {type(error).__name__}')
            # Do not cancel after a successful commit: finish creating its output.
            emit('exporting', '课表已保存，正在生成导入文件…')
            self.diagnostics.capture_committed(self.root)
            report = apple_report = issue = apple_issue = None
            try:
                self.diagnostics.event('apple_export_started')
                apple_report = self._apple_export_unlocked(repair=True)
                self.diagnostics.event('apple_export_finished', success=True, event_count=apple_report['event_count'])
            except Exception as error:
                self.diagnostics.exception(error, stage='apple_export_failed')
                apple_issue = explain_error(error, exporting=True, apple=True)
            try:
                self.diagnostics.event('wakeup_export_started')
                report = self._export_unlocked()
                self.diagnostics.event('wakeup_export_finished', success=True, event_count=report['event_count'])
            except Exception as error:
                self.diagnostics.exception(error, stage='wakeup_export_failed')
                issue = explain_error(error, exporting=True)
            return {'imported': imported, 'report': report, 'issue': issue,
                    'apple_report': apple_report, 'apple_issue': apple_issue,
                    'committed': True, 'output_issues': output_issues}


class DesktopJob:
    """Small thread/queue boundary; the Tk main thread is the only UI owner."""
    def __init__(self, service):
        self.service = service
        self.events = queue.Queue()
        self.manual = queue.Queue()
        self.cancelled = threading.Event()
        self.picker_open = threading.Event()
        self.thread = None
        self.stage = 'idle'

    @property
    def busy(self):
        return self.thread is not None and self.thread.is_alive()

    def emit(self, stage, value):
        if stage != 'detail':
            self.stage = stage
        self.events.put((stage, value))

    def choose(self):
        try:
            return self.manual.get_nowait()
        except queue.Empty:
            return None

    def start(self, **options):
        if self.busy:
            return False
        self.cancelled.clear()
        self.picker_open.clear()
        self.manual = queue.Queue()
        self.stage = 'preparing'
        def work():
            try:
                result = self.service.run(cancel=self.cancelled, choose=self.choose,
                                          paused=self.picker_open, emit=self.emit, **options)
                self.emit('result', result)
            except Exception as error:
                self.service.diagnostics.exception(error, stage='worker_failed')
                self.emit('error', explain_error(error))
            finally:
                self.events.put(('finished', None))
        self.thread = threading.Thread(target=work, name='schedule-local-worker', daemon=False)
        self.thread.start()
        return True

    def cancel(self):
        self.service.diagnostics.event('cancel_requested', cancelled=self.stage not in ('committing', 'exporting', 'result'))
        if self.stage not in ('committing', 'exporting', 'result'):
            self.cancelled.set()

    def submit_file(self, path):
        if path is not None and self.busy and self.stage == 'waiting':
            self.manual.put(Path(path))
            return True
        return False
