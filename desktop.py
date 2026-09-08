"""Chinese desktop front end. Browser login and bookmark installation stay manual."""
from __future__ import annotations

if __name__ == '__main__':
    from diagnostics import install_startup_hook
    install_startup_hook()

import argparse
import json
import os
import queue
import subprocess
import sys
import time
import uuid
import tkinter as tk
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont
from zoneinfo import ZoneInfo
from PIL import Image, ImageTk

from core import DataError
from desktop_service import (APP_VERSION, HOME_URL, DesktopJob, DesktopService,
                             default_data_root, explain_error, student_term_config, term_key)
from prepare import downloads_folder
from platform_support import (MAC_PACKAGE_LABEL, bookmark_shortcut, reveal_command,
                              scroll_units, ui_font_family, select_data_root)
from sync import atomic_write, capture_folder, json_bytes, load_current, load_settings
from wakeup import load_slot_times, slot_times

BG, INK, GREEN, MUTED = '#edf4f0', '#213d36', '#176b54', '#587268'


def wakeup_setup_reminder(report):
    """Describe the committed export's settings, including custom terms/times."""
    first = date.fromisoformat(report['first_monday'])
    durations = {(datetime.strptime(end, '%H:%M:%S') - datetime.strptime(start, '%H:%M:%S')).seconds // 60
                 for start, end in report['slot_times'].values()}
    duration = f'{next(iter(durations))} 分钟' if len(durations) == 1 else '逐节核对作息'
    time_action = (f'导入后请手动将上课时长改为 {duration}。' if len(durations) == 1 else
                   '本次各节时长不同，请对照设置卡逐节填写上下课时间。')
    date_action = f'学期第一天请设为 {first:%Y-%m-%d}（{first.month}.{first.day}）。'
    if first == date(2026, 9, 7):
        date_action += '不要保留 9 月 4 日（9.4）。'
    return (f'导入 WakeUp 后必改：{duration} · {first.month} 月 {first.day} 日',
            '50 分钟来自 WakeUp 当前的作息设置，CSV 不会自动修改它。' + time_action + '\n' +
            date_action + '\n打开“查看 WakeUp 导入指引与作息”，对照本次课表的设置卡完成。')


def readable_time(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y年%m月%d日 %H:%M')
    except (ValueError, AttributeError):
        return '未记录'


def semester_label(value):
    years, term = value.split(':')
    return f'{years} 学年 · 第 {term} 学期'


def reveal_file(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise DataError('导入文件已经移动，请重新生成导入文件。')
    # Argument list, no shell, no CSV association (which might open a spreadsheet).
    return subprocess.Popen(reveal_command(path))


class AssistantWindow:
    def __init__(self, window, data_root=None):
        self.window = window
        self.base = default_data_root()
        self.preference_path = self.base / 'preferences.json'
        selected, self.recovery_issue = select_data_root(self.base, data_root)
        self.service = DesktopService(selected, recovery_issue=self.recovery_issue,
                                      diagnostics_root=self.base if self.recovery_issue else None)
        self.job = DesktopJob(self.service)
        self.running = False
        self.closing = False
        self.disposed = False
        self.reveal_checks = {}
        self.mac_commands = []
        self.pending = None
        self.details = []
        self.last_result = None
        self.phone_guide = None
        self.browser_collection = False
        self.startup_notice_pending = True
        self.poll_id = None
        self.status = tk.StringVar(value='')
        self.window.title('医学院课表助手')
        self.window.configure(bg=BG)
        scale = max(1, self.window.winfo_fpixels('1i') / 96)
        width = min(round(900 * scale), self.window.winfo_screenwidth() - 64)
        height = min(round(760 * scale), self.window.winfo_screenheight() - 96)
        self.window.geometry(f'{width}x{height}')
        self.window.minsize(min(round(720 * scale), width), min(round(520 * scale), height))
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        if sys.platform == 'darwin':
            for name, callback in (('Quit', self.close), ('ReopenApplication', self.reopen),
                                   ('ShowPreferences', self.show_settings), ('ShowHelp', self.show_help)):
                command = '::tk::mac::' + name
                self.window.createcommand(command, callback)
                self.mac_commands.append(command)
            self.window.createcommand('tkAboutDialog', lambda: messagebox.showinfo(
                '关于医学院课表助手', APP_VERSION + ' · ' + MAC_PACKAGE_LABEL + '\n本地课表与两种文件导出。', parent=self.window))
            self.mac_commands.append('tkAboutDialog')
            # Bind per toplevel: native file dialogs keep their own key handling.
            self.window.bind('<Command-w>', lambda event: self.close_window(event.widget.winfo_toplevel()))
        self.window.report_callback_exception = lambda kind, error, tb: self.handle_error(error, 'ui_callback_failed')
        self._style()
        header = ttk.Frame(window, padding=(28, 18))
        header.pack(fill='x')
        ttk.Label(header, text='医学院课表助手', style='Brand.TLabel').pack(side='left')
        ttk.Label(header, text=f'{APP_VERSION} · WakeUp / 苹果日历', style='Muted.TLabel').pack(side='right')
        nav = ttk.Frame(window, padding=(28, 0, 28, 14))
        nav.pack(fill='x')
        self.nav_buttons = []
        for label, action in [('首页', self.show_home), ('设置', self.show_settings), ('遇到问题', self.show_help)]:
            button = ttk.Button(nav, text=label, command=action)
            button.pack(side='left', padx=(0, 8))
            self.nav_buttons.append(button)
        holder = ttk.Frame(window)
        holder.pack(fill='both', expand=True, padx=28, pady=(0, 20))
        self.canvas = tk.Canvas(holder, bg='white', highlightthickness=0)
        scrollbar = ttk.Scrollbar(holder, orient='vertical', command=self.canvas.yview)
        scrollbar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.content = ttk.Frame(self.canvas, style='Card.TFrame', padding=26)
        self.canvas_item = self.canvas.create_window(0, 0, anchor='nw', window=self.content)
        self.reset_scroll = True
        self.content.bind('<Configure>', self._content_configured)
        self.canvas.bind('<Configure>', self._resize)
        self.window.bind('<MouseWheel>', self._wheel)
        self.wrapping = []
        try:
            self.service.initialize()
            self.show_home()
        except Exception as error:
            if isinstance(error, OSError):
                self.recovery_issue = '课表目录暂时不可用。请检查磁盘空间与文件夹权限，然后重新选择原目录。'
                self.service.recovery_issue = self.recovery_issue
            if self.recovery_issue:
                from diagnostics import DiagnosticRecorder
                self.service.diagnostics = DiagnosticRecorder(self.base)
            self.handle_error(error, 'startup_failed')
        self.poll_id = self.window.after(100, self.poll)

    def reopen(self):
        if not self.disposed and not self.closing:
            self.window.deiconify()
            self.window.lift()

    def close_window(self, window):
        if window == self.window:
            self.close()
        else:
            window.destroy()
        return 'break'

    def bind_dialog_close(self, dialog):
        if sys.platform == 'darwin':
            dialog.bind('<Command-w>', lambda event: self.close_window(dialog))

    def show_recovery(self):
        self.clear('恢复保存位置', '请先找回原课表目录', self.recovery_issue)
        self.label('连接原磁盘或恢复文件夹权限后，选择原目录继续。也可以明确选择一个空目录新建独立课表；不会复制或重置原历史。')
        self.button('选择原课表目录或新建独立课表', self.pick_root, primary=True)
        self.button('导出排错日志', self.show_diagnostics)

    def _style(self):
        style = ttk.Style(self.window)
        style.theme_use('clam')
        self.font_family = ui_font_family(tkfont.families(self.window),
            tkfont.nametofont('TkDefaultFont', root=self.window).actual('family'))
        style.configure('.', font=(self.font_family, 11))
        style.configure('TFrame', background=BG)
        style.configure('TLabel', background=BG, foreground=INK)
        style.configure('Brand.TLabel', font=(self.font_family, 16, 'bold'))
        style.configure('Muted.TLabel', foreground=MUTED)
        style.configure('Card.TFrame', background='white')
        style.configure('Body.TLabel', background='white', foreground=INK)
        style.configure('Small.TLabel', background='white', foreground=MUTED, font=(self.font_family, 10))
        style.configure('Title.TLabel', background='white', foreground=INK, font=(self.font_family, 23, 'bold'))
        style.configure('Section.TLabel', background='white', foreground=INK, font=(self.font_family, 14, 'bold'))
        style.configure('Notice.TFrame', background='#edf6f0')
        style.configure('NoticeTitle.TLabel', background='#edf6f0', foreground=GREEN, font=(self.font_family, 14, 'bold'))
        style.configure('NoticeBody.TLabel', background='#edf6f0', foreground=INK, font=(self.font_family, 10))
        style.configure('TButton', padding=(14, 9), background='#e6eee9', foreground=INK)
        style.configure('Primary.TButton', background=GREEN, foreground='white', padding=(20, 12), font=(self.font_family, 12, 'bold'))
        style.map('Primary.TButton', background=[('disabled', '#d8e4dc'), ('active', '#12563f')], foreground=[('disabled', MUTED)])
        style.configure('TEntry', padding=6)
        style.configure('TNotebook', background='white')
        style.configure('TNotebook.Tab', padding=(16, 8))
        self.table_font = tkfont.Font(root=self.window, family=self.font_family, size=11)
        style.configure('Treeview', font=self.table_font, rowheight=self.table_font.metrics('linespace') + 10)

    def _wheel(self, event):
        # Leave comboboxes, text fields and native dialogs their normal scroll behavior.
        if event.widget.winfo_toplevel() == self.window and event.widget.winfo_class() not in ('Text', 'TCombobox'):
            self.canvas.yview_scroll(scroll_units(event.delta), 'units')

    def _resize(self, event):
        self.canvas.itemconfigure(self.canvas_item, width=event.width)
        for widget in self.wrapping:
            if widget.winfo_exists():
                widget.configure(wraplength=max(240, event.width - 64 - getattr(widget, 'wrap_inset', 0)))

    def _content_configured(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))
        if self.reset_scroll:
            self.canvas.yview_moveto(0)
            self.reset_scroll = False

    def _scroll_top(self):
        # Run after Tk has laid out the replacement page, including hidden windows.
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))
        self.canvas.yview_moveto(0)

    def clear(self, eyebrow, title, description=''):
        for child in self.content.winfo_children():
            child.destroy()
        self.wrapping = []
        self.reset_scroll = True
        self.window.after_idle(self._scroll_top)
        self.label(eyebrow, 'Small.TLabel')
        self.label(title, 'Title.TLabel', (4, 14))
        if description:
            self.label(description, pady=(0, 18))
        if self.startup_notice_pending:
            self.startup_notice_pending = False
            self.notice('安全软件提示',
                        '杀毒软件有时会把正常软件当成病毒。请使用作者发的软件或下载链接。'
                        '如果出现提醒、拿不准该点什么，把提示截图发给作者，确认后再继续打开。')

    def notice(self, title, description):
        band = tk.Frame(self.content, background=GREEN)
        band.pack(fill='x', pady=(0, 16))
        body = ttk.Frame(band, style='Notice.TFrame', padding=(14, 12))
        body.pack(fill='x', padx=(5, 0))
        for text, style, spacing in ((title, 'NoticeTitle.TLabel', (0, 6)),
                                     (description, 'NoticeBody.TLabel', (0, 0))):
            label = self.label(text, style, spacing, parent=body)
            label.wrap_inset = 34
            label.configure(wraplength=max(240, self.canvas.winfo_width() - 98))
        return band

    def label(self, text, style='Body.TLabel', pady=(0, 10), parent=None):
        widget = ttk.Label(parent or self.content, text=text, style=style,
                           wraplength=max(400, self.canvas.winfo_width() - 64), justify='left')
        widget.pack(anchor='w', fill='x', pady=pady)
        self.wrapping.append(widget)
        return widget

    def button(self, text, action, *, primary=False, parent=None, enabled=True):
        button = ttk.Button(parent or self.content, text=text, command=action,
                            style='Primary.TButton' if primary else 'TButton')
        button.pack(anchor='w', pady=(0, 12))
        if not enabled:
            button.configure(state='disabled')
        return button

    def copy_text(self, text, notice='已复制。请在平时登录教务的浏览器地址栏粘贴并回车。'):
        self.window.clipboard_clear()
        self.window.clipboard_append(text)
        self.window.update_idletasks()
        self.status.set(notice)

    def status_label(self):
        widget = ttk.Label(self.content, textvariable=self.status, style='Small.TLabel',
                           wraplength=max(400, self.canvas.winfo_width() - 64))
        widget.pack(anchor='w', fill='x', pady=(0, 12))
        self.wrapping.append(widget)

    def show_home(self):
        if self.recovery_issue:
            self.show_recovery()
            return
        if self.running:
            self.show_work()
            return
        step = self.service.setup_step()
        if step:
            self.show_setup(step)
            return
        current = load_current(self.service.root)
        self.clear('每次更新，只走这条流程' if current else '首次导入 · 下一步获取课表', '把课表装进手机',
                   '获取课表  →  自动生成文件  →  发给自己  →  在 iPhone 导入')
        if current:
            self.label(f"已保存 {len(current['events'])} 次课程 · {semester_label(current['scope']['semester'])}", 'Section.TLabel')
            self.label('上次学校采集：' + readable_time(current.get('capture_fetched_at')), 'Small.TLabel')
            days = [e['date'] for e in current['events']]
            if days:
                self.label(f'本次已公布课程：{min(days)} 至 {max(days)}', 'Small.TLabel')
        else:
            self.label('接下来获取你的第一份课表。还没添加好课表按钮，可重新查看安装引导。')
        self.button('获取我的课表', self.start, primary=True)
        self.label('助手会先准备好接收，再提示你去浏览器登录教务首页。', 'Small.TLabel')
        if current is None:
            self.button('重新查看书签安装引导', lambda: self.show_setup(2))
        self.export_choices(self.service.ready_export(), self.service.ready_apple_export(),
                            allow_rebuild=current is not None)
        self.label('只下载到 JSON？选择它生成手机文件', 'Section.TLabel', (16, 10))
        self.button('文件已经下载', self.pick_capture)
        self.label('选择浏览器下载的 shsmu-capture-…json，助手会检查并生成 wakeup.csv 和 calendar.ics。', 'Small.TLabel')
        self.label('两种文件都需要在手机手动导入，不会自动跟随电脑更新。', 'Small.TLabel', (18, 0))

    def show_setup(self, step):
        if step == 1:
            config = student_term_config(self.service.config())
            self.clear('首次准备 · 1 / 2', '选择要导入的学期', '不需要填写哪天结课，助手会根据教务课表显示实际有课的日期。')
            self.label(semester_label(config['semester']), 'Section.TLabel')
            if config.get('range_mode') == 'school_calendar':
                self.label('已按学校校历准备好范围，包含寒假，读取到下学期开学前。')
                self.label('提前结课不会多出课程；这期间有晚结课或补课，也会读取。只有教务实际返回的课程才会导入。', 'Small.TLabel')
            else:
                self.label('使用已设置的采集范围；具体范围可在“设置”中查看。', 'Small.TLabel')
            self.button('就用这个学期，下一步', self.confirm_term, primary=True)
            self.button('选择其他学期或特殊安排', self.show_settings)
            self.button('以前用过？选择原项目目录', self.pick_root)
        else:
            self.clear('首次准备 · 2 / 2', '给浏览器添加课表按钮',
                       '① 复制安装页地址。\n② 在平时登录教务的浏览器地址栏粘贴、回车。\n③ 按安装页图示，把绿色按钮拖到书签或收藏夹栏。')
            self.label('已经下载到 JSON？从这里继续', 'Section.TLabel')
            self.label('选择浏览器下载的 shsmu-capture-…json，助手会检查并生成 wakeup.csv 和 calendar.ics，无需重新采集。', 'Small.TLabel')
            self.button('文件已经下载', self.pick_capture)
            self.label('还没获取课表？继续添加浏览器按钮', 'Section.TLabel')
            self.button('复制安装页地址', lambda: self.copy_text(self.service.bookmark_path.as_uri()), primary=True)
            self.status_label()
            with Image.open(self.service.resources / 'assets/bookmark-install.png') as source:
                illustration = source.convert('RGB')
            sketch = tk.Canvas(self.content, width=1, height=1, background='white', highlightthickness=0)
            sketch.pack(fill='x', pady=(0, 8))
            image_item = sketch.create_image(0, 0, anchor='nw')

            def fit_illustration(event):
                if event.width <= 1:
                    return
                width = max(1, min(event.width, illustration.width))
                size = (width, max(1, round(illustration.height * width / illustration.width)))
                if getattr(sketch, 'image_size', None) == size:
                    return
                first_render = not hasattr(sketch, 'image_size')
                # Scale only the displayed image; the bundled original stays intact.
                sketch.photo = ImageTk.PhotoImage(illustration.resize(size, Image.Resampling.LANCZOS), master=self.window)
                sketch.image_size = size
                sketch.itemconfigure(image_item, image=sketch.photo)
                sketch.configure(height=size[1])
                if first_render:
                    self.window.after_idle(self._scroll_top)

            sketch.bind('<Configure>', fit_illustration)
            self.label('图中以 Chrome 为例；Safari、Edge、Firefox 的对应栏位见下方说明。', 'Small.TLabel')
            self.label(f'Edge 叫“收藏夹栏”，Chrome 叫“书签栏”，Firefox 叫“书签工具栏”。按 {bookmark_shortcut()} 显示。Safari 选“显示 → 显示个人收藏栏”，把按钮拖入该栏。安装和登录请使用同一个浏览器。', 'Small.TLabel')
            self.button('我已添加课表按钮，进入助手', self.confirm_bookmark)
            self.label('此按钮只记录你的确认；实际采集成功后才算验证书签可用。', 'Small.TLabel')

    def confirm_term(self):
        self.service.confirm_term()
        self.status.set('')
        self.show_setup(2)

    def confirm_bookmark(self):
        self.service.acknowledge_bookmark()
        self.show_home()

    def start(self, capture=None, export_only=False):
        if self.recovery_issue:
            self.show_recovery()
            return
        if self.closing or self.disposed:
            return
        if self.running or self.job.busy:
            return
        # Dispose unreachable Tk objects on their owning thread before the worker
        # allocates diagnostic JSON; CPython's cyclic GC may run in that worker.
        import gc
        gc.collect()
        self.details = []
        self.last_result = None
        self.running = True
        self.browser_collection = capture is None and not export_only
        self.status.set('正在准备接收…' if capture is None and not export_only else '正在准备处理…')
        self.show_work()
        self.job.start(capture=capture, export_only=export_only)

    def show_work(self):
        self.clear('电脑正在处理 · 请保持助手打开', '获取你的课表',
                   '这里会显示接收和处理结果。浏览器中的学校页面显示实际采集进度。')
        self.status_label()
        if self.browser_collection:
            self.notice('下一步：请点击浏览器书签“同步医学院课表”',
                        '等助手显示“已准备好接收”后，在添加书签的同一个浏览器登录教务首页。\n'
                        '看到本人学号后，点击书签栏 / 收藏夹栏中的“同步医学院课表”，才会开始采集。')
            self.button('复制教务首页地址', lambda: self.copy_text(HOME_URL))
            self.label('点击书签后，保持学校页面和助手打开；实际采集进度请看教务网页。', 'Small.TLabel')
            self.label('Safari 首次使用：先从教务首页打开“我的课表”，看到课程后回首页，再点击课表书签。', 'Small.TLabel')
        self.picker_button = self.button('文件已经下载', self.pick_capture, enabled=self.job.stage == 'waiting')
        if self.browser_collection:
            self.label('浏览器只会下载 shsmu-capture-…json。若这里仍在等待，点“文件已经下载”选择它，继续生成 WakeUp 和苹果日历文件。', 'Small.TLabel')
        self.cancel_button = self.button('取消本次操作', self.cancel, enabled=self.job.stage not in ('committing', 'exporting'))
        self.button('查看处理详情', self.show_details)
        self.nav_buttons[1].configure(state='disabled')

    def cancel(self):
        self.job.cancel()
        self.status.set('正在结束本次操作；完整课表保留。')

    def poll(self):
        try:
            while True:
                stage, value = self.job.events.get_nowait()
                if stage == 'finished':
                    self.running = False
                    self.nav_buttons[1].configure(state='normal')
                    if self.closing:
                        self.dispose()
                        return
                    if self.pending:
                        action, self.pending = self.pending, None
                        self.window.after(50, action)
                elif stage == 'result':
                    self.last_result = value
                    self.show_result(value)
                elif stage == 'error':
                    self.show_issue(value)
                else:
                    if self.browser_collection and stage in ('processing', 'committing', 'exporting'):
                        self.browser_collection = False
                        self.show_work()
                    self.details.append(str(value))
                    if stage == 'waiting':
                        if '失败诊断' in value:
                            self.status.set('收到错误报告，请查看浏览器页面提示；助手继续等待完整课表。')
                        elif not self.job.cancelled.is_set():
                            self.status.set('已准备好接收。现在请到浏览器登录教务首页，点击课表按钮。')
                    elif stage != 'detail':
                        self.status.set(str(value))
                    if hasattr(self, 'picker_button') and self.picker_button.winfo_exists():
                        self.picker_button.configure(state='normal' if self.job.stage == 'waiting' else 'disabled')
                        self.cancel_button.configure(state='disabled' if self.job.stage in ('committing', 'exporting') else 'normal')
        except queue.Empty:
            pass
        self.poll_id = self.window.after(100, self.poll)

    def show_result(self, result):
        report, apple_report, imported = result['report'], result['apple_report'], result['imported']
        complete = report is not None and apple_report is not None
        self.clear('电脑处理结果 · 手机仍需手动导入', '课表准备好了' if complete else '课表已保存',
                   '按你使用的 App 选择文件。' if complete else '请查看每种文件的状态，可用的文件可以继续导入。')
        summary_report = apple_report or report
        if summary_report:
            self.label('学校采集时间：' + readable_time(summary_report['capture_fetched_at']), 'Small.TLabel')
            if summary_report['course_start']:
                self.label(f"本次已公布课程：{summary_report['course_start']} 至 {summary_report['course_end']}", 'Small.TLabel')
        if imported:
            summary = imported.diff['summary']
            self.label(f"新增 {summary['ADDED']}  ·  删除 {summary['REMOVED']}  ·  修改 {summary['CHANGED']}", 'Section.TLabel')
            if imported.duplicate:
                self.label('使用的是已处理过的同一文件，没有重新访问学校。', 'Small.TLabel')
            for warning in imported.diff.get('warnings', []):
                self.label('请核对：' + warning)
        else:
            self.label('本次由已保存课表重新生成，没有重新访问学校。', 'Small.TLabel')
        self.export_choices(report, apple_report, wakeup_issue=result['issue'], apple_issue=result['apple_issue'])
        self.label('电脑文件生成成功后，手机仍需手动导入并核对。', 'Small.TLabel')

    def export_choices(self, report, apple_report, *, wakeup_issue=None, apple_issue=None, allow_rebuild=True):
        for name, ready, issue, action, guide, guide_text, delivery in (
                ('WakeUp', report, wakeup_issue, self.reveal, self.show_phone,
                 '查看 WakeUp 导入指引与作息', 'wakeup.csv · 可通过微信或 QQ 发给自己。'),
                ('苹果日历', apple_report, apple_issue, self.reveal_apple, self.show_apple_phone,
                 '查看苹果日历导入指引', 'calendar.ics · 作为邮件附件发给自己，在 iPhone 自带“邮件”中打开。')):
            self.label(name, 'Section.TLabel', (10, 8))
            if ready is not None:
                self.label(f"文件已就绪 · {ready['event_count']} 次课程。{delivery}", 'Small.TLabel')
                if name == 'WakeUp':
                    self.notice(*wakeup_setup_reminder(ready))
            elif issue is not None:
                self.label(issue.title + '。' + issue.next_step, 'Small.TLabel')
                self.details.append(issue.detail)
            else:
                self.label('文件暂不可用，请重新生成。' if allow_rebuild else '获取完整课表后，这里会提供文件。', 'Small.TLabel')
            actions = ttk.Frame(self.content)
            actions.pack(anchor='w', fill='x')
            for text, callback in ((('导出 WakeUp 文件' if name == 'WakeUp' else '导出苹果日历'), action),
                                   (guide_text, guide)):
                button = self.button(text, callback, parent=actions, enabled=ready is not None)
                button.pack_configure(side='left', padx=(0, 12))
        if allow_rebuild and (report is None or apple_report is None):
            self.button('重新生成导入文件', lambda: self.start(export_only=True))

    def reveal(self):
        if self.service.ready_export() is None:
            self.show_issue(explain_error(DataError('导入文件已过期或被移动，请重新生成导入文件。'), exporting=True))
            return
        self.locate_file(self.service.root / 'output/wakeup.csv', retry=self.reveal)

    def reveal_apple(self):
        if self.service.ready_apple_export() is None:
            self.show_issue(explain_error(DataError('苹果日历文件已过期或被移动，请重新生成导入文件。'),
                                          exporting=True, apple=True))
            return
        self.locate_file(self.service.root / 'output/calendar.ics', retry=self.reveal_apple)

    def locate_file(self, path, retry=None):
        if self.disposed:
            return
        path = Path(path)
        retry = retry or (lambda: self.locate_file(path))
        try:
            process = reveal_file(path)
        except (OSError, DataError) as error:
            self.record_error(error, 'file_location_failed')
            self.show_location_issue(path, retry)
            return
        if sys.platform == 'darwin':
            self.reveal_checks[process] = None
            self.check_location(process, path, retry, time.monotonic() + 5)

    def check_location(self, process, path, retry, deadline):
        if self.disposed:
            return
        result = process.poll()
        if result is None and time.monotonic() < deadline:
            self.reveal_checks[process] = self.window.after(100,
                lambda: self.check_location(process, path, retry, deadline))
            return
        self.reveal_checks.pop(process, None)
        if result is None:
            self.stop_location(process)
        if result != 0:
            self.service.diagnostics.event('file_location_failed', code='FILE_IO', timed_out=result is None)
            self.show_location_issue(path, retry)

    @staticmethod
    def stop_location(process):
        if process.poll() is None:
            try:
                process.kill()
                process.wait(timeout=0.1)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def show_location_issue(self, path, retry):
        manager = 'Finder' if sys.platform == 'darwin' else '文件资源管理器'
        self.clear('文件位置', '文件已生成，未能打开所在位置',
                   f'已有文件保留，无需重新采集。可以重试，或按下方路径在 {manager} 中查找文件。')
        self.label(str(path))
        self.button('重试打开所在位置', retry, primary=True)
        notice = ('文件路径已复制。可在 Finder 的“前往文件夹”中粘贴。' if sys.platform == 'darwin'
                  else '文件路径已复制。可在文件资源管理器的地址栏中粘贴。')
        self.button('复制文件路径', lambda: self.copy_text(str(path), notice))
        self.status_label()
        self.button('回到首页', self.show_home)

    def show_phone(self):
        report = self.service.ready_export()
        if report is None:
            self.show_issue(explain_error(DataError('尚无对应当前课表的导入文件。'), exporting=True))
            return
        self.phone_guide = ('wakeup', report['csv_sha256'])
        self.clear('最后一步 · 在 iPhone 上操作', '把文件导入 WakeUp',
                   '1. 在手机微信 / QQ 接收 wakeup.csv，保存到“文件”App。\n'
                   '2. WakeUp → 导入课表 → Excel 导入 → 选取 CSV 文件。\n'
                   '3. 选择刚才的文件，导入到一个新课表。\n'
                   '4. 按下面的设置卡检查日期和上课时间。')
        self.notice(*wakeup_setup_reminder(report))
        self.label('本次课表的设置卡', 'Section.TLabel')
        self.label(f"学期开始日期：{report['first_monday']}（第一周周一）\n"
                   f"WakeUp 课表周数：{report['semester_weeks']}（按本次课程自动计算）\n"
                   f"已公布课程到：{report['course_end']}    一天课程节数：14    每周从周一开始")
        self.label('若无法分别修改下课时间，在 WakeUp 关闭“每节课时长相同”。', 'Small.TLabel')
        table = ttk.Treeview(self.content, columns=('slot', 'start', 'end', 'basis'), show='headings', height=14)
        for key, title, width in [('slot', '节次', 65), ('start', '上课', 90), ('end', '下课', 90), ('basis', '依据（上课 / 下课）', 220)]:
            table.heading(key, text=title)
            table.column(key, width=width, minwidth=60, anchor='center')
        for number in range(1, 15):
            pair = report['slot_times'].get(number) or report['slot_times'].get(str(number))
            fallback = '自定义' if report['custom_times'] else '模板推算'
            basis = ('课程确认' if number in report['observed_start_slots'] else fallback) + ' / ' + ('课程确认' if number in report['observed_end_slots'] else fallback)
            table.insert('', 'end', values=(number, pair[0][:5], pair[1][:5], basis))
        table.pack(fill='x', pady=(0, 14))
        self.label('“课程确认”表示学校课程给出了该端点；其余由模板或本人设置补齐，不代表学校官方作息。', 'Small.TLabel')
        self.label('检查第一周、晚课和不连续周次。以后更新也先导入新课表，核对后再自行处理旧课表，避免重复显示。')
        self.button('我已在手机导入并核对', self.confirm_phone, primary=True)
        self.label('这是你的手工确认；电脑无法检测手机里的实际状态。', 'Small.TLabel')

    def confirm_phone(self):
        report = self.service.ready_export()
        if report is None or self.phone_guide != ('wakeup', report['csv_sha256']):
            self.show_issue(explain_error(DataError('文件已变化或不可用，请重新打开 WakeUp 指引并核对后再确认。'), exporting=True))
            return
        self.service.save_state(phone_confirmed_csv=report['csv_sha256'])
        self.service.diagnostics.event('wakeup_phone_confirmed', success=True)
        self.clear('你的手工确认', '已记录 WakeUp 手机核对', '以后学校课表有更新，再打开助手获取新课表，并重新在 WakeUp 导入。')
        self.button('回到首页', self.show_home, primary=True)

    def show_apple_phone(self):
        report = self.service.ready_apple_export()
        if report is None:
            self.show_issue(explain_error(DataError('尚无对应当前课表的苹果日历文件。'), exporting=True, apple=True))
            return
        self.phone_guide = ('apple', report['ics_sha256'])
        self.clear('最后一步 · 在 iPhone 上操作', '把文件导入苹果日历',
                   '1. 在 iPhone“日历”中建立专用的“医学院课表”日历。\n'
                   '2. 在电脑邮件中附加 calendar.ics，由你发送到自己的邮箱。\n'
                   '3. 在 iPhone 自带“邮件”中打开附件，按提示导入专用课表日历。\n'
                   '4. 核对课程日期、上课时间、地点和教师。')
        self.label(f"当前有效课程：{report['event_count']} 次\n学校采集时间：" + readable_time(report['capture_fetched_at']), 'Section.TLabel')
        if report['course_start']:
            self.label(f"本次已公布课程：{report['course_start']} 至 {report['course_end']}")
        self.label('文件已携带每次课的日期、起止时间和上海时区，无需填写开学日期或节次作息。')
        self.button('导出苹果日历', self.reveal_apple)
        self.label('以后更新怎么处理', 'Section.TLabel', (10, 10))
        self.label('这是一次性文件导入，手机不会自动跟随电脑更新。以后先导入新的专用课表日历，核对后再由你隐藏或移除旧课表日历，避免重复显示。不要删除其他个人日历。')
        self.label('重复导入是否覆盖原课程、如何处理取消课程，取决于手机的实际导入行为，不能保证自动更新或删除。请特别核对发生变化的课程。', 'Small.TLabel')
        self.label('若“邮件”中没有导入选项，请保留文件，记录 iOS 版本和所见提示；不要将文件预览当作导入成功。', 'Small.TLabel')
        self.button('我已在苹果日历导入并核对', self.confirm_apple_phone, primary=True)
        self.label('这是你的手工确认；电脑无法检测手机里的实际状态。', 'Small.TLabel')

    def confirm_apple_phone(self):
        report = self.service.ready_apple_export()
        if report is None or self.phone_guide != ('apple', report['ics_sha256']):
            self.show_issue(explain_error(DataError('文件已变化或不可用，请重新打开苹果日历指引并核对后再确认。'),
                                          exporting=True, apple=True))
            return
        self.service.save_state(phone_confirmed_ics=report['ics_sha256'])
        self.service.diagnostics.event('apple_phone_confirmed', success=True)
        self.clear('你的手工确认', '已记录苹果日历手机核对', '以后学校课表有更新，再获取新课表，并通过邮件附件重新导入新的专用课表日历。')
        self.button('回到首页', self.show_home, primary=True)

    def show_issue(self, issue):
        self.details.append(issue.detail)
        self.recovery_issue = self.service.recovery_issue or self.recovery_issue
        if self.recovery_issue:
            self.show_recovery()
            return
        self.clear('处理提示', issue.title, issue.next_step)
        self.button('文件已经下载', self.pick_capture)
        self.button('重新生成导入文件', lambda: self.start(export_only=True))
        self.button('打开设置', self.show_settings)
        self.button('查看技术详情', self.show_details)
        self.button('导出排错日志', self.show_diagnostics, primary=True)

    def record_error(self, error, stage):
        log = self.service.diagnostics
        separate = not self.job.busy and (not log.record or log.record['status'] not in ('running', 'failed'))
        if separate:
            log.begin('activity')
        log.exception(error, stage=stage)
        if separate:
            log.capture_committed(self.service.root)
            log.finish('failed')

    def handle_thread_error(self, error):
        self.record_error(error, 'unhandled_thread_failed')
        self.job.events.put(('error', explain_error(error)))

    def handle_error(self, error, stage):
        self.record_error(error, stage)
        self.show_issue(explain_error(error))

    def show_diagnostics(self):
        log = self.service.diagnostics
        records = log.records()
        if not records:
            log.begin('activity')
            records = log.records()
        dialog = tk.Toplevel(self.window)
        self.bind_dialog_close(dialog)
        dialog.title('导出排错日志')
        dialog.geometry('720x480')
        dialog.minsize(640, 450)
        body = ttk.Frame(dialog, padding=18)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='选择出问题的那次操作，导出后把 ZIP 文件发给维护者。', wraplength=650).pack(anchor='w', pady=(0, 12))
        status_names = {'success': '完成', 'partial': '部分失败', 'failed': '失败', 'cancelled': '取消',
                        'running': '进行中', 'interrupted': '意外中断'}
        kind_names = {'sync': '获取课表', 'export': '重新导出', 'startup': '启动', 'settings': '设置',
                      'term_settings': '学期设置', 'bookmark_confirmation': '书签确认', 'activity': '操作记录'}
        choices = [f"{readable_time(r['started_at'])} · {kind_names.get(r['kind'], '操作')} · {status_names.get(r['status'], '未知')} · {r['operation_id'][:8]}" for r in records]
        selection = ttk.Combobox(body, values=choices, state='readonly', width=75)
        selection.pack(fill='x', pady=(0, 14))
        default = 0 if records[0]['status'] == 'failed' else next((i for i, r in enumerate(records) if r['kind'] in ('sync', 'export')), 0)
        selection.current(default)
        ttk.Label(body, text='已替换姓名、学号、课程文字及标识，仍包含日期、节次等排错信息；请仅发给维护者。\n日志默认在本机保留 30 天，最多 50 MB。', wraplength=650).pack(anchor='w', pady=(0, 12))
        if log.storage_warning:
            ttk.Label(body, text='部分记录未能保存到磁盘。本窗口会尝试从内存导出，请选择可写的位置。', wraplength=650).pack(anchor='w', pady=(0, 10))
        ttk.Label(body, text='可选：粘贴网页“复制排错信息”中的 JSON（浏览器无法下载时使用）').pack(anchor='w')
        extra = tk.Text(body, height=6, wrap='word')
        extra.pack(fill='both', expand=True, pady=(6, 12))
        def export():
            chosen = records[selection.current()]
            target = filedialog.asksaveasfilename(parent=dialog, title='保存排错日志', defaultextension='.zip',
                initialfile='课表助手排错日志-' + chosen['operation_id'][:8] + '.zip',
                filetypes=[('排错日志 ZIP', '*.zip')])
            if not target:
                return
            try:
                path = log.export(target, chosen['operation_id'], browser_text=extra.get('1.0', 'end'))
            except Exception as error:
                log.exception(error, stage='support_export_failed')
                messagebox.showerror('排错日志尚未导出', str(error) if isinstance(error, ValueError) else
                    '文件没有保存成功。请检查磁盘空间和文件夹权限，换一个位置重试。', parent=dialog)
                return
            self.locate_file(path)
            dialog.destroy()
        ttk.Button(body, text='保存 ZIP 并打开所在位置', command=export).pack(anchor='w')

    def show_details(self):
        dialog = tk.Toplevel(self.window)
        self.bind_dialog_close(dialog)
        dialog.title('处理详情')
        dialog.geometry('760x440')
        area = tk.Text(dialog, wrap='word', font=(self.font_family, 10), padx=16, pady=12)
        area.pack(fill='both', expand=True)
        area.insert('end', '\n\n'.join(self.details[-35:]) or '暂时没有处理记录。')
        area.configure(state='disabled')
        ttk.Button(dialog, text='关闭', command=dialog.destroy).pack(pady=10)
        ttk.Button(dialog, text='导出排错日志', command=self.show_diagnostics).pack(pady=(0, 10))

    def show_help(self):
        self.clear('遇到问题时，从这里继续', '不用从头再来')
        self.label('只有 JSON，没有 WakeUp 或日历文件？', 'Section.TLabel')
        self.button('文件已经下载', self.pick_capture)
        self.label('选择浏览器下载的 shsmu-capture-…json，助手会检查并生成 wakeup.csv 和 calendar.ics。JSON 是中间文件，不能直接导入手机，也不要改扩展名。取消选择会继续原来的等待。', 'Small.TLabel')
        self.button('选择下载文件夹', self.pick_downloads)
        self.button('重新生成导入文件', lambda: self.start(export_only=True), enabled=not self.running)
        self.label('从已保存的完整课表重新生成 WakeUp 和苹果日历文件，无需重新采集。作息设置只影响 WakeUp。', 'Small.TLabel')
        self.button('重新查看书签安装引导', lambda: self.show_setup(2), enabled=not self.running)
        self.button('查看技术详情', self.show_details)
        self.button('导出排错日志', self.show_diagnostics, primary=True)
        self.label('登录过期：在添加了课表按钮的浏览器中正常打开教务首页并登录，然后点击课表按钮。\n'
                   '换了浏览器：在新浏览器重新添加课表按钮并正常登录；已保存的课表不用搬动。\n'
                   '文件在别处：从浏览器下载列表查看位置，然后选择已下载文件。\n'
                   '页面读取失败：按页面提示继续或重新采集；已保存的完整课表不会被不完整结果替换。\n'
                   '手机没有课程：先确认已手动导入，并切换到新导入的课表。')

    def pick_capture(self):
        if getattr(self, 'recovery_issue', None):
            self.show_recovery()
            return
        if self.running and self.job.stage != 'waiting':
            self.status.set('正在核对或保存课表，请等待本次处理结束。')
            return
        was_waiting = self.running
        self.job.picker_open.set()
        try:
            folder = capture_folder(self.service.config(), self.service.config_path)
            try:
                initialdir = str(folder if folder.is_dir() else downloads_folder())
            except OSError:
                # A denied folder must not prevent choosing a readable JSON elsewhere.
                initialdir = None
            selected = filedialog.askopenfilename(parent=self.window, title='选择已下载的课表 JSON，生成 WakeUp 和苹果日历文件',
                initialdir=initialdir,
                filetypes=[('完整课表文件', 'shsmu-capture-*.json'), ('JSON 文件', '*.json')])
            if selected:
                self.service.diagnostics.event('file_picker_selected')
                if was_waiting:
                    self.job.submit_file(selected)
                else:
                    self.start(capture=Path(selected))
        finally:
            self.job.picker_open.clear()

    def pick_downloads(self):
        if self.recovery_issue:
            self.show_recovery()
            return
        if self.running and self.job.stage != 'waiting':
            return
        self.job.picker_open.set()
        try:
            selected = filedialog.askdirectory(parent=self.window, title='选择浏览器保存课表的下载文件夹')
        finally:
            self.job.picker_open.clear()
        if not selected:
            return
        def save():
            config = self.service.config()
            config['downloads_dir'] = selected
            self.service.save_settings(config, confirm_term=False)
            self.show_home()
        if self.running:
            self.pending = save
            self.cancel()
        else:
            save()

    def pick_root(self):
        if self.running:
            return
        selected = filedialog.askdirectory(parent=self.window, title='选择原项目目录，或为另一人选择空目录')
        if not selected:
            return
        candidate = DesktopService(selected)
        # Validate before initialize() can create configuration or diagnostics.
        if (candidate.root / 'data/schedule.json').exists() and not (candidate.root / 'data/current.json').is_file():
            raise DataError('原数据目录缺少完整版本索引，请保留目录并恢复索引，不要新建历史。')
        load_current(candidate.root)
        if candidate.config_path.is_file():
            candidate.config()
        if not candidate.config_path.is_file() and not (candidate.root / 'data/current.json').is_file():
            if any(candidate.root.iterdir()):
                log = self.service.diagnostics
                log.begin('settings')
                log.event('data_directory_rejected', code='VALIDATION')
                log.finish('failed')
                messagebox.showerror('请选择课表目录或空目录', '这个非空目录不是已有课表项目。请选原项目目录，或新建一个空文件夹。', parent=self.window)
                return
            if not messagebox.askyesno('新建独立课表', '为这个目录新建独立课表？不会复制其他人的课表或上传配置。', parent=self.window):
                return
        candidate.initialize()
        # Validate history before switching; never migrate it or reset identities.
        load_current(candidate.root)
        if self.recovery_issue:
            try:
                original = self.preference_path.read_bytes()
            except FileNotFoundError:
                original = None
            if original is not None:
                backup = self.preference_path.with_name('preferences.recovery-' + uuid.uuid4().hex + '.json')
                atomic_write(backup, original)
        atomic_write(self.preference_path, json_bytes({'data_root': str(candidate.root)}))
        self.service.diagnostics.event('data_directory_left')
        candidate.diagnostics.event('data_directory_selected')
        self.service, self.job = candidate, DesktopJob(candidate)
        self.recovery_issue = None
        self.last_result = None
        self.show_home()

    def show_settings(self):
        if self.recovery_issue:
            self.show_recovery()
            return
        if self.running:
            return
        self.clear('设置 · 不需要修改配置文件', '学期、作息和保存位置')
        try:
            config = self.service.config()
        except DataError as error:
            self.record_error(error, 'settings_read_failed')
            config = load_settings(self.service.resources / 'config.example.json')
            self.label('原学期设置无法读取，下面显示示例值。请核对后保存；历史课表保留。')
        notebook = ttk.Notebook(self.content)
        notebook.pack(fill='both', expand=True, pady=(0, 18))
        term_tab, times_tab, storage_tab = [ttk.Frame(notebook, style='Card.TFrame', padding=16) for _ in range(3)]
        for tab, text in [(term_tab, '学期'), (times_tab, '作息时间'), (storage_tab, '保存位置')]:
            notebook.add(tab, text=text)
        year, term = config['semester'].split(':')
        self.label('下面是采集覆盖范围，不是本人的开课或结课日期。普通秋季课表无需修改；只有其他学期、实习或跨学期安排才使用自定义范围。', 'Small.TLabel', parent=term_tab)
        year_var = tk.StringVar(value=year.split('-')[0])
        term_var = tk.StringVar(value=term)
        start_var = tk.StringVar(value=config['start'])
        end_var = tk.StringVar(value=str(date.fromisoformat(config['end_exclusive']) - timedelta(days=1)))
        for title, variable in [('学年开始年份（如 2026）', year_var), ('第几学期（如 1）', term_var),
                                ('采集起始日（年-月-日）', start_var), ('采集覆盖到（包含这一天）', end_var)]:
            self.label(title, parent=term_tab)
            ttk.Entry(term_tab, textvariable=variable, width=25).pack(anchor='w', pady=(0, 14))
        self.label('改变学期后，需要按引导更新浏览器中的课表按钮。旧学期的完整版本仍保留。', 'Small.TLabel', parent=term_tab)
        slots_broken = False
        try:
            times = load_slot_times(self.service.root) or slot_times()
        except DataError as error:
            self.record_error(error, 'slots_read_failed')
            slots_broken = True
            times = slot_times()
            self.label('原作息无法读取，下面显示模板。请核对本人作息后保存。', parent=times_tab)
        original_times = [[a[:5], b[:5]] for a, b in times.values()]
        self.label('请输入 24 小时制时间，例如 08:00。模板不是学校官方作息；导出时会核对全部课程端点。', 'Small.TLabel', parent=times_tab)
        grid = ttk.Frame(times_tab, style='Card.TFrame')
        grid.pack(anchor='w')
        for col, text in enumerate(('节次', '上课', '下课')):
            ttk.Label(grid, text=text, style='Body.TLabel').grid(row=0, column=col, padx=12, pady=4)
        fields = []
        for n, pair in enumerate(original_times, 1):
            variables = [tk.StringVar(value=v) for v in pair]
            fields.append(variables)
            ttk.Label(grid, text=str(n), style='Body.TLabel').grid(row=n, column=0, padx=12)
            for col, variable in enumerate(variables, 1):
                ttk.Entry(grid, textvariable=variable, width=9).grid(row=n, column=col, padx=8, pady=3)
        folder_var = tk.StringVar(value=str(capture_folder(config, self.service.config_path)))
        self.label('浏览器下载文件夹', 'Section.TLabel', parent=storage_tab)
        folder_entry = ttk.Entry(storage_tab, textvariable=folder_var, width=48)
        folder_entry.pack(fill='x', pady=(0, 10))
        def select_folder():
            selected = filedialog.askdirectory(parent=self.window, title='选择下载文件夹')
            if selected:
                folder_var.set(selected)
        self.button('选择文件夹', select_folder, parent=storage_tab)
        self.label('课表和历史保存在：\n' + str(self.service.root), 'Small.TLabel', parent=storage_tab)
        self.button('选择原项目 / 独立数据目录', self.pick_root, parent=storage_tab)
        self.label('这里只切换目录，不复制课表、上传设置或其他人的数据。', 'Small.TLabel', parent=storage_tab)
        def save():
            try:
                year_num = int(year_var.get().strip())
                last = date.fromisoformat(end_var.get().strip())
                updated = {**config, 'semester': f'{year_num}-{year_num + 1}:{term_var.get().strip()}',
                           'start': start_var.get().strip(), 'end_exclusive': str(last + timedelta(days=1)),
                           'downloads_dir': folder_var.get().strip()}
                if term_key(updated) != term_key(config):
                    updated['range_mode'] = 'custom'
                values = [[v.get().strip() for v in pair] for pair in fields]
                current = load_current(self.service.root)
                if current and term_key(current['scope']) != term_key(updated):
                    if not messagebox.askyesno('确认新的学期范围', '今后将接收这里选择的日期范围。旧完整课表仍保留；请同时更新书签。继续保存？', parent=self.window):
                        return
                self.service.save_settings(updated, values if slots_broken or values != original_times else None)
                self.show_home()
            except (ValueError, OverflowError) as error:
                self.record_error(error, 'settings_input_failed')
                messagebox.showerror('请检查日期', '年份使用四位数字，日期使用有效的年-月-日，例如 2026-09-07。', parent=self.window)
            except Exception as error:
                self.record_error(error, 'settings_failed')
                issue = explain_error(error)
                messagebox.showerror('设置尚未保存', issue.detail, parent=self.window)
        self.button('保存设置', save, primary=True)

    def close(self):
        if self.disposed or self.closing:
            return
        if self.running:
            self.closing = True
            self.pending = None
            self.job.cancel()
            self.status.set('正在安全结束；保存已经开始时会等待它完成。')
        else:
            self.dispose()

    def dispose(self):
        if self.disposed:
            return
        self.disposed = True
        self.service.diagnostics.event('window_closed')
        for process, callback in self.reveal_checks.items():
            if callback:
                self.window.after_cancel(callback)
            self.stop_location(process)
        self.reveal_checks.clear()
        if self.poll_id:
            self.window.after_cancel(self.poll_id)
            self.poll_id = None
        self.window.update_idletasks()
        for command in self.mac_commands:
            self.window.deletecommand(command)
        self.mac_commands = []
        self.window.destroy()
        self.window.report_callback_exception = None
        self.status = None
        self.wrapping = []


def main():
    parser = argparse.ArgumentParser(description='医学院课表助手')
    parser.add_argument('--data-root', type=Path, help='显式选择数据目录（维护与验收使用）')
    parser.add_argument('--self-test', type=Path, metavar='REPORT', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.self_test:
        from desktop_smoke import self_test
        self_test(args.self_test)
        return
    if os.name == 'nt':
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    window = tk.Tk()
    ui = AssistantWindow(window, args.data_root)
    import sys
    import threading
    sys.excepthook = lambda kind, error, tb: ui.handle_error(error, 'unhandled_exception')
    threading.excepthook = lambda args: ui.handle_thread_error(args.exc_value)
    window.mainloop()


if __name__ == '__main__':
    main()
