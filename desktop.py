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

from desktop_theme import (Theme, Card, ScrollArea, PAGE, SURFACE, SURFACE as BG, INK, TEXT,
                           ACCENT as GREEN, MUTED, LINE, SIDEBAR, TIP, walk_widgets)


def wakeup_setup_reminder(report):
    """Describe the committed export's settings, including custom terms/times."""
    first = date.fromisoformat(report['first_monday'])
    durations = {(datetime.strptime(end, '%H:%M:%S') - datetime.strptime(start, '%H:%M:%S')).seconds // 60
                 for start, end in report['slot_times'].values()}
    if len(durations) == 1:
        body = (f"学期开始日期：{first:%Y-%m-%d}；每节课时长：{next(iter(durations))} 分钟。\n"
                'CSV 不会自动设置日期和作息，请在 WakeUp 中核对。')
    else:
        body = (f"学期开始日期：{first:%Y-%m-%d}。各节课时长不同，请按作息表逐节设置。\n"
                'CSV 不会自动设置日期和作息。')
    return '导入后请核对日期和作息', body


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
        self.poll_id = None
        self.ui_after = set()
        self.page = None
        self.pictures = {}
        self.wheel_rest = 0
        self.status = tk.StringVar(value='')
        self.window.title('医学院课表助手')
        self.window.configure(bg=PAGE)
        scale = max(1, self.window.winfo_fpixels('1i') / 96)
        width = min(round(1080 * scale), self.window.winfo_screenwidth() - 64)
        height = min(round(687 * scale), self.window.winfo_screenheight() - 96)
        self.window.geometry(f'{width}x{height}')
        self.window.minsize(min(round(800 * scale), width), min(round(520 * scale), height))
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
        self._sidebar()
        # Classic frames only for the large areas; see desktop_theme.
        tk.Frame(window, bg=LINE, width=1, bd=0, highlightthickness=0).pack(side='left', fill='y')
        self.scroller = ScrollArea(window, self.theme)
        self.scroller.frame.pack(side='left', fill='both', expand=True)
        self.scrollbar = self.scroller.scrollbar
        self.content = self.scroller.content
        self.window.bind('<MouseWheel>', self._wheel)
        self.window.bind('<FocusIn>', self._focus_visible, add='+')
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

    def _sidebar(self):
        px = self.px
        self.sidebar = tk.Frame(self.window, bg=SIDEBAR, width=px(self.theme.metrics.sidebar), bd=0, highlightthickness=0)
        self.sidebar.pack(side='left', fill='y')
        self.sidebar.pack_propagate(False)
        brand = tk.Frame(self.sidebar, bg=SIDEBAR)
        brand.pack(fill='x', padx=px(22), pady=(px(28), px(24)))
        tk.Label(brand, image=self.theme.icon('calendar', 22), bg=SIDEBAR).pack(side='left', padx=(0, px(10)))
        font, colour = self.theme.text('brand')
        tk.Label(brand, text='课表助手', font=font, fg=colour, bg=SIDEBAR).pack(side='left')
        nav = self.theme.button_style('Nav', SIDEBAR)
        disabled = '#99a69e'
        self.nav_buttons = []
        for label, icon, action in [('首页', 'home', self.show_home), ('设置', 'settings', self.show_settings)]:
            button = ttk.Button(self.sidebar, text='  ' + label, image=(self.theme.icon(icon, 18), 'disabled',
                                self.theme.icon(icon, 18, disabled)), compound='left', style=nav, command=action)
            button.pack(fill='x', padx=px(12), pady=(0, px(4)))
            self.bind_button(button)
            self.nav_buttons.append(button)
        footer = tk.Frame(self.sidebar, bg=SIDEBAR)
        footer.pack(side='bottom', fill='x', padx=px(12), pady=px(18))
        help_button = ttk.Button(footer, text='  帮助与排错', image=(self.theme.icon('help', 18), 'disabled',
                                 self.theme.icon('help', 18, disabled)), compound='left', style=nav, command=self.show_help)
        help_button.pack(fill='x')
        self.bind_button(help_button)
        self.nav_buttons.append(help_button)
        font, colour = self.theme.text('side')
        tk.Label(footer, text=APP_VERSION, font=font, fg=colour, bg=SIDEBAR).pack(anchor='w', padx=px(14), pady=(px(14), 0))

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
        body = self.card()
        self.label('连接原磁盘或恢复文件夹权限后，选择原目录继续。也可以选择一个空目录新建独立课表；不会复制或重置原历史。', parent=body)
        self.button('选择原课表目录或新建独立课表', self.pick_root, primary=True, parent=body)
        self.button('导出排错日志', self.show_diagnostics, parent=body).pack_configure(pady=0)

    def _style(self):
        self.theme = Theme(self.window)
        self.px = self.theme.px
        self.font_family = self.theme.family
        self.table_font = self.theme.table_font

    def defer(self, callback):
        def run():
            self.ui_after.discard(handle)
            if not self.disposed:
                callback()
        handle = self.window.after_idle(run)
        self.ui_after.add(handle)
        return handle

    def bind_button(self, button):
        def invoke(event):
            if not button.instate(['disabled']):
                button.invoke()
            return 'break'
        button.bind('<Return>', invoke)
        button.bind('<KP_Enter>', invoke)

    def _focus_visible(self, event):
        widget = event.widget
        if not hasattr(self, 'content') or self.disposed or widget.winfo_toplevel() != self.window:
            return
        if not str(widget).startswith(str(self.content) + '.'):
            return
        self.window.update_idletasks()
        # Leave one scroll increment around keyboard focus.
        self.scroller.ensure_visible(widget, self.px(24))

    def _wheel(self, event):
        # Nested scrollable controls and native dialogs own their wheel events.
        if event.widget.winfo_toplevel() == self.window and event.widget.winfo_class() not in ('Text', 'TCombobox', 'Treeview', 'Listbox'):
            units, self.wheel_rest = scroll_units(event.delta, self.wheel_rest)
            if units:
                self.scroller.yview_scroll(units, 'units')

    def _wrap_label(self, widget, width):
        # The allocated label width already excludes every ancestor's padding.
        # Widths change only at column breakpoints, so this rarely runs.
        if width > self.px(40) and getattr(widget, 'wrap', None) != width:
            widget.wrap = width
            widget.configure(wraplength=width)

    # -- building blocks ------------------------------------------------------

    @staticmethod
    def _background(parent):
        value = getattr(parent, 'background', None)
        if value:
            return value
        return parent.cget('background') if isinstance(parent, (tk.Frame, tk.Toplevel)) else BG

    @staticmethod
    def _text_width(parent, default):
        while parent is not None:
            width = getattr(parent, 'inner_width', None)
            if width:
                return width
            parent = parent.master
        return default

    def clear(self, eyebrow, title, description='', *, step=None, page=None):
        if getattr(self,'progress',None) is not None:
            if self.progress.winfo_exists():
                self.progress.stop()
            self.progress=None
        for child in self.content.winfo_children():
            child.destroy()
        self.wrapping = []
        self.scroller.reset()
        self.page = page or ('settings' if title == '课表设置' else 'help' if title == '帮助与排错' else 'home')
        selected = 1 if self.page.startswith('settings') else 2 if self.page == 'help' else 0
        for i, button in enumerate(self.nav_buttons):
            button.state(['selected' if i == selected else '!selected'])
        if step:
            self.steps(step)
        if eyebrow:
            self.label(eyebrow, 'eyebrow', (0, 6))
        self.label(title, 'title', (0, 6 if description else 22))
        if description:
            self.label(description, 'subtitle', (0, 24))

    def steps(self, current):
        row = tk.Frame(self.content, bg=PAGE)
        row.pack(fill='x', pady=(0, self.px(28)))
        font = self.theme.font(11, 'bold')
        for i, title in enumerate(('选择学期', '获取课表', '导入手机'), 1):
            state = 'current' if i == current else 'done' if i < current else 'todo'
            tk.Label(row, image=self.theme.dot(state), text='✓' if state == 'done' else str(i), compound='center',
                     font=font, fg=SURFACE if state == 'current' else GREEN if state == 'done' else MUTED,
                     bg=PAGE, bd=0).pack(side='left')
            text_font, colour = self.theme.text('step-current' if i == current else 'step')
            tk.Label(row, text=title, font=text_font, fg=colour, bg=PAGE).pack(side='left', padx=(self.px(8), 0))
            if i < 3:
                tk.Frame(row, bg='#cdd8d1' if i >= current else GREEN, height=max(1, self.px(1)),
                         width=self.px(40)).pack(side='left', padx=self.px(14))

    def card(self, parent=None, *, tip=False, pady=(0, 16), padding=None):
        parent = parent or self.content
        fill = TIP if tip else SURFACE
        card = Card(parent, self.theme, fill=fill, border=TIP if tip else LINE,
                    outer=self._background(parent), padding=padding)
        card.pack(fill='x', pady=tuple(self.px(n) for n in pady))
        return card.body

    def row(self, parent=None, pady=(0, 0)):
        parent = parent or self.content
        frame = tk.Frame(parent, bg=self._background(parent))
        frame.background = self._background(parent)
        frame.pack(fill='x', pady=tuple(self.px(n) for n in pady))
        return frame

    def rule(self, parent=None, pady=(14, 14)):
        tk.Frame(parent or self.content, bg=LINE, height=1).pack(fill='x', pady=tuple(self.px(n) for n in pady))

    def numbered(self, parent, number, title, copy='', style='strong'):
        """One numbered step; returns the column for extra controls."""
        row = self.row(parent, (0, 16))
        tk.Label(row, image=self.theme.dot('number', self._background(parent)), text=str(number), compound='center',
                 font=self.theme.font(11, 'bold'), fg=GREEN, bg=row.background, bd=0).pack(side='left', anchor='n',
                 padx=(0, self.px(14)))
        if not copy and style != 'strong':
            # Plain instruction step: no extra column window (each costs ~1 ms).
            self.label(title, style, (2, 0), parent=row).pack_configure(side='left', expand=True)
            return row
        column = tk.Frame(row, bg=row.background)
        column.background = row.background
        column.pack(side='left', fill='x', expand=True)
        self.label(title, style, (2, 3 if copy else 0), parent=column)
        if copy:
            self.label(copy, 'small', (0, 0), parent=column)
        return column

    def footer_links(self, title, links):
        row = self.row(pady=(10, 0))
        font, colour = self.theme.text('small')
        tk.Label(row, text=title, font=font, fg=colour, bg=PAGE).pack(side='left', padx=(0, self.px(6)))
        for label, action in links:
            self.button(label, action, parent=row, link=True).pack_configure(side='left', padx=(0, self.px(12)), pady=0)

    def recovery_row(self, *, original=False):
        links = [('选择已下载的课表', self.pick_capture)]
        if original:
            links.append(('使用已有课表文件夹', self.pick_root))
        self.footer_links('已有课表文件？', links)

    def term_card(self, config, *, compact=False):
        body = self.card()
        row = self.row(body)
        tk.Label(row, image=self.theme.icon('calendar', 26), bg=SURFACE).pack(side='left', anchor='n', padx=(0, self.px(14)))
        copy = tk.Frame(row, bg=SURFACE)
        copy.pack(side='left', fill='x', expand=True)
        self.button('更改', lambda: self.show_settings_details(0), parent=row, link=True).pack_configure(
            side='right', anchor='n', pady=0)
        self.label(semester_label(config['semester']), 'section', (0, 4), parent=copy)
        if 'start' in config and 'end_exclusive' in config:
            last = date.fromisoformat(config['end_exclusive']) - timedelta(days=1)
            self.label(f"读取范围：{config['start']} 至 {last}", 'small', (0, 0), parent=copy)
        return body

    def notice(self, title, description, parent=None):
        body = self.card(parent, tip=True, padding=18)
        self.label(title, 'tip-title', (0, 4), parent=body)
        self.label(description, 'tip', (0, 0), parent=body)
        return body

    def label(self, text, style='body', pady=(0, 10), parent=None):
        parent = parent or self.content
        font, colour = self.theme.text(style)
        wrap = self._text_width(parent, self.px(600))
        widget = tk.Label(parent, text=text, font=font, fg=colour, bg=self._background(parent), justify='left',
                          anchor='w', bd=0, padx=0, pady=0, wraplength=wrap)
        widget.wrap = wrap
        widget.pack(anchor='w', fill='x', pady=tuple(self.px(n) for n in pady))
        widget.bind('<Configure>', lambda event: self._wrap_label(widget, event.width))
        self.wrapping.append(widget)
        return widget

    def button(self, text, action, *, primary=False, parent=None, enabled=True, link=False, icon=None):
        parent = parent or self.content
        style = self.theme.button_style('Primary' if primary else 'Link' if link else '', self._background(parent))
        button = ttk.Button(parent, text=text, command=action, style=style)
        if icon:
            button.configure(image=(self.theme.icon(icon, 16, 'white' if primary else GREEN),
                                    'disabled', self.theme.icon(icon, 16, '#99a69e')), compound='left')
        button.pack(anchor='w', fill='x' if primary else None, pady=(0, self.px(12)))
        self.bind_button(button)
        if not enabled:
            button.configure(state='disabled')
        return button

    def copy_text(self, text, notice='地址已复制。请在登录教务的浏览器地址栏粘贴并打开。'):
        self.window.clipboard_clear()
        self.window.clipboard_append(text)
        self.window.update_idletasks()
        self.status.set(notice)

    def status_label(self, parent=None):
        parent = parent or self.content
        font, colour = self.theme.text('small')
        wrap = self._text_width(parent, self.px(400))
        widget = tk.Label(parent, textvariable=self.status, font=font, fg=GREEN, bg=self._background(parent),
                          justify='left', anchor='w', wraplength=wrap)
        widget.wrap = wrap
        widget.pack(anchor='w', fill='x', pady=(0, self.px(10)))
        widget.bind('<Configure>', lambda event: self._wrap_label(widget, event.width))
        self.wrapping.append(widget)
        return widget

    def bookmark_picture(self, parent):
        """Inline installation picture, resized once per column width."""
        picture = tk.Label(parent, bg=self._background(parent), bd=0, cursor='hand2')
        picture.pack(anchor='w', pady=(self.px(10), self.px(6)))
        picture.bind('<Button-1>', lambda event: self.show_bookmark_details())
        def fit(width):
            width = max(self.px(160), int(width))
            if getattr(picture, 'width', None) == width:
                return
            if width not in self.pictures:
                with Image.open(self.service.resources / 'assets/bookmark-install.png') as original:
                    # The preview keeps only the annotated browser bar; the empty
                    # page below it stays in the full picture (dialog, uncropped).
                    source = original.convert('RGB').crop((0, 0, original.width, min(original.height, 430)))
                    height = max(1, round(source.height * width / source.width))
                    self.pictures[width] = ImageTk.PhotoImage(
                        source.resize((width, height), Image.Resampling.LANCZOS), master=self.window)
            picture.width = width
            picture.configure(image=self.pictures[width])
        # A preview: the full picture opens on click, so keep the steps above the fold.
        limit = self.px(560)
        fit(min(limit, self._text_width(parent, limit)))
        parent.bind('<Configure>', lambda event: fit(min(limit, event.width)) if event.width > self.px(160) else None, add='+')
        return picture

    # -- pages -----------------------------------------------------------------

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
        current = self.service.current()
        config = current['scope'] if current else self.service.config()
        if current is None:
            self.clear('首次使用', '我的课表', semester_label(config['semester']), step=2, page='ready')
            body = self.card()
            self.numbered(body, 1, '点击“获取课表”', '助手开始等待接收课表文件。')
            self.numbered(body, 2, '到教务首页点击课表书签',
                          '在安装书签的浏览器登录教务首页，确认显示本人学号后，点击“同步医学院课表”。')
            self.button('获取课表', self.start, primary=True, parent=body).pack_configure(pady=(self.px(4), self.px(8)))
            self.button('查看书签安装说明', lambda: self.show_setup(2), parent=body, link=True).pack_configure(pady=0)
            self.recovery_row()
            return
        last = date.fromisoformat(config['end_exclusive']) - timedelta(days=1)
        self.clear('', '我的课表', f"{semester_label(config['semester'])} · 读取范围 {config['start']} 至 {last}", page='home')
        body = self.card()
        self.label(f"已保存 {len(current['events'])} 次课程", 'section', (0, 6), parent=body)
        self.label('上次获取：' + readable_time(current.get('capture_fetched_at')), 'small', (0, 2), parent=body)
        days = [e['date'] for e in current['events']]
        if days:
            self.label(f'课程日期：{min(days)} 至 {max(days)}', 'small', (0, 0), parent=body)
        self.button('重新获取课表', self.start, primary=True, parent=body).pack_configure(pady=(self.px(18), self.px(2)))
        wakeup, apple = self.service.ready_export(), self.service.ready_apple_export()
        body = self.card()
        title = ('导入文件已生成' if wakeup is not None and apple is not None else
                 '部分导入文件可用' if wakeup is not None or apple is not None else '当前导入文件不可用')
        self.label(title, 'strong', (0, 4), parent=body)
        self.label('电脑文件更新后，仍需在手机重新导入。', 'small', (0, 10), parent=body)
        links = self.row(body)
        self.button('查看文件与导入步骤', self.show_files, parent=links, link=True).pack_configure(side='left', pady=0, padx=(0, self.px(18)))
        self.button('重新生成导入文件', lambda: self.start(export_only=True), parent=links, link=True).pack_configure(side='left', pady=0)
        self.footer_links('已有课表文件？', [('选择已下载的课表', self.pick_capture), ('更改学期', lambda: self.show_settings_details(0))])

    def show_files(self):
        if self.running:
            return
        if self.service.current() is None:
            self.show_home()
            return
        self.show_result({'report':self.service.ready_export(),'apple_report':self.service.ready_apple_export(),
                          'imported':None,'issue':None,'apple_issue':None}, from_saved=True)

    def show_setup(self, step):
        if step == 1:
            config = student_term_config(self.service.config())
            self.clear('', '选择学期', '确认要获取的学期，无需填写个人结课日期。', step=1, page='term')
            body = self.term_card(config)
            self.rule(body, (18, 18))
            self.button('确认学期并继续', self.confirm_term, primary=True, parent=body).pack_configure(pady=0)
            self.recovery_row(original=True)
        else:
            self.clear('', '安装课表书签', '在平时登录教务系统的浏览器中完成。', step=2, page='bookmark')
            body = self.card()
            column = self.numbered(body, 1, '复制安装页地址', '粘贴到浏览器地址栏并打开。')
            self.button('复制安装页地址', lambda: self.copy_text(self.service.bookmark_path.as_uri()),
                        parent=column, icon='copy').pack_configure(pady=(self.px(8), 0))
            column = self.numbered(body, 2, '把“同步医学院课表”拖到书签栏',
                                   f'看不到书签栏时，按 {bookmark_shortcut()}。')
            self.bookmark_picture(column)
            self.button('查看安装图示与浏览器说明', self.show_bookmark_details, parent=column, link=True).pack_configure(pady=0)
            self.numbered(body, 3, '回到这里继续')
            self.status_label(body)
            self.button('已添加书签，继续', self.confirm_bookmark, primary=True, parent=body).pack_configure(pady=(self.px(4), 0))
            self.recovery_row()

    def dialog(self, title, width=720, height=530):
        dialog = tk.Toplevel(self.window)
        dialog.title(title)
        dialog.configure(background=BG)
        self.bind_dialog_close(dialog)
        dialog.transient(self.window)
        w = min(self.px(width),self.window.winfo_screenwidth()-self.px(40))
        h = min(self.px(height),self.window.winfo_screenheight()-self.px(80))
        dialog.geometry(f'{w}x{h}')
        dialog.minsize(min(self.px(560),w),min(self.px(440),h))
        return dialog

    def show_bookmark_details(self):
        dialog = self.dialog('书签安装说明',760,590)
        footer = ttk.Frame(dialog,padding=self.px(18))
        footer.pack(side='bottom',fill='x')
        self.button('关闭',dialog.destroy,parent=footer).pack_configure(side='right',pady=0)
        body = ttk.Frame(dialog,padding=self.px(24))
        body.pack(fill='both',expand=True)
        with Image.open(self.service.resources/'assets/bookmark-install.png') as original:
            source = original.convert('RGB')
        picture = ttk.Label(body)
        picture.pack(fill='both',expand=True)
        def fit(event):
            ratio=min(max(1,event.width)/source.width,max(1,event.height)/source.height)
            size=(max(1,round(source.width*ratio)),max(1,round(source.height*ratio)))
            if getattr(picture,'size',None)==size:
                return
            picture.size=size
            picture.photo=ImageTk.PhotoImage(source.resize(size,Image.Resampling.LANCZOS),master=dialog)
            picture.configure(image=picture.photo)
        picture.bind('<Configure>',fit)
        copy=ttk.Label(body,text=f'图示以 Chrome 为例。Chrome、Edge、Firefox：按 {bookmark_shortcut()} 显示书签栏或收藏夹栏。\nSafari：选择“显示 → 显示个人收藏栏”。请在同一个浏览器中安装书签并登录教务。',style='Small.TLabel',wraplength=self.px(680))
        copy.pack(fill='x',pady=(self.px(16),0))
        body.bind('<Configure>',lambda e:copy.configure(wraplength=max(self.px(300),e.width-self.px(48))))

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
        self.status.set('正在准备接收课表…' if capture is None and not export_only else '正在准备处理课表…')
        self.show_work()
        self.job.start(capture=capture, export_only=export_only)

    def show_work(self):
        self.clear('请保持助手打开', '在浏览器获取课表' if self.browser_collection else '处理课表',
                   '读取进度请看教务网页；助手收到文件后会继续处理。' if self.browser_collection else '',
                   step=2, page='waiting' if self.browser_collection else 'processing')
        body = self.card()
        self.progress=ttk.Progressbar(body,mode='indeterminate')
        self.progress.pack(fill='x',pady=(self.px(4),self.px(14)))
        self.progress.start(24)
        self.status_label(body).pack_configure(pady=0)
        if self.browser_collection:
            tip = self.notice('下一步：在教务首页点击课表书签',
                              '看到“已准备好接收”后，登录教务首页，确认显示本人学号，再点击“同步医学院课表”。')
            self.button('复制教务首页地址', lambda: self.copy_text(HOME_URL), parent=tip, icon='copy').pack_configure(pady=(self.px(12), 0))
            if sys.platform == 'darwin':
                self.label('Safari 首次使用：先从教务首页打开“我的课表”，看到课程后回首页，再点击课表书签。', 'small')
        actions = self.row(pady=(4, 0))
        self.picker_button = self.button('选择已下载的课表', self.pick_capture, parent=actions,
                                         enabled=self.job.stage == 'waiting', icon='folder')
        self.picker_button.pack_configure(side='left', padx=(0, self.px(10)))
        self.cancel_button = self.button('取消操作', self.cancel, parent=actions,
                                         enabled=self.job.stage not in ('committing', 'exporting'))
        self.cancel_button.pack_configure(side='left', padx=(0, self.px(10)))
        self.button('查看处理详情', self.show_details, parent=actions, link=True).pack_configure(side='left')
        if self.browser_collection:
            self.label('浏览器已下载，这里仍在等待？点“选择已下载的课表”，选中刚下载的 JSON。', 'small')
        for button in self.nav_buttons:
            button.state(['disabled'])

    def cancel(self):
        self.job.cancel()
        self.status.set('正在取消操作…已保存的课表不会因此删除。')

    def poll(self):
        # One failing page render must not stop the queue: a lost 'finished'
        # would leave the window running forever and unable to close.
        try:
            while not self.disposed:
                try:
                    stage, value = self.job.events.get_nowait()
                except queue.Empty:
                    break
                try:
                    self._handle_job_event(stage, value)
                except Exception as error:
                    try:
                        self.handle_error(error, 'ui_event_failed')
                    except Exception:
                        pass
        finally:
            if not self.disposed:
                self.poll_id = self.window.after(100, self.poll)

    def _handle_job_event(self, stage, value):
        if stage == 'finished':
            self.running = False
            for button in self.nav_buttons:
                button.state(['!disabled'])
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
                    self.status.set('浏览器读取未完成，请按网页提示处理。助手仍在等待课表文件。')
                elif not self.job.cancelled.is_set():
                    self.status.set('已准备好接收。请前往浏览器读取课表。')
            elif stage != 'detail':
                self.status.set(str(value))
            if hasattr(self, 'picker_button') and self.picker_button.winfo_exists():
                self.picker_button.configure(state='normal' if self.job.stage == 'waiting' else 'disabled')
                if self.cancel_button.winfo_exists():
                    self.cancel_button.configure(state='disabled' if self.job.stage in ('committing', 'exporting') else 'normal')

    def show_result(self, result, *, from_saved=False):
        report, apple_report, imported = result['report'], result['apple_report'], result['imported']
        complete = report is not None and apple_report is not None and not result.get('output_issues')
        if complete:
            result_hint = '选择使用的 App，将文件发送到手机后手动导入。'
        elif report is not None and apple_report is not None:
            result_hint = '两种导入文件已生成，但其他输出尚未完成。请查看下方状态；已生成的文件仍可使用。'
        elif report is not None or apple_report is not None:
            result_hint = '部分导入文件未生成，请查看下方状态。已生成的文件仍可使用。'
        else:
            result_hint = '导入文件未生成，请查看下方原因后重试。'
        self.clear('', '导入文件已生成' if complete else '课表已保存', result_hint, step=3, page='results')
        self.export_choices(report, apple_report, wakeup_issue=result['issue'], apple_issue=result['apple_issue'])
        if report is not None or apple_report is not None:
            self.notice('电脑文件已生成 ≠ 手机已经更新', '两种格式都需要在手机上手动导入。再次导入前请核对新旧课表，避免重复。')
        else:
            self.notice('课表已保存，导入文件尚未生成', '请按文件状态提示处理后重新生成；手机端仍需手动导入。')
        body = None
        def summary():
            nonlocal body
            if body is None:
                body = self.card()
            return body
        summary_report = apple_report or report
        if summary_report:
            self.label('课表获取时间：' + readable_time(summary_report['capture_fetched_at']), 'small', (0, 4), parent=summary())
            if summary_report['course_start']:
                self.label(f"当前课程日期：{summary_report['course_start']} 至 {summary_report['course_end']}", 'small', (0, 4), parent=summary())
        if imported:
            summary_counts = imported.diff['summary']
            self.label(f"与上次相比：新增 {summary_counts['ADDED']} 次 · 移除 {summary_counts['REMOVED']} 次 · 修改 {summary_counts['CHANGED']} 次", 'section', (8, 4), parent=summary())
            if imported.duplicate:
                self.label('这是已处理过的课表文件；本次没有重新读取教务课表。', 'small', (0, 4), parent=summary())
            for warning in imported.diff.get('warnings', []):
                self.label('请核对：' + warning, 'body', (0, 4), parent=summary())
        elif not from_saved:
            self.label('本次使用已保存的课表生成文件，未重新读取教务课表。', 'small', (0, 4), parent=summary())
        for output_issue in result.get('output_issues', {}).values():
            self.label(output_issue.title + '。' + output_issue.next_step, 'small', (0, 4), parent=summary())
            self.details.append(output_issue.detail)
        if (report is None) != (apple_report is None):
            self.label('使用已生成的文件时，请在手机手动导入并核对。', 'small', (0, 4), parent=summary())
        actions = self.row(pady=(4, 0))
        self.button('返回首页',self.show_home,parent=actions).pack_configure(side='left',padx=(0,self.px(14)))
        self.button('重新生成导入文件',lambda:self.start(export_only=True),parent=actions,link=True).pack_configure(side='left')

    def export_choices(self, report, apple_report, *, wakeup_issue=None, apple_issue=None, allow_rebuild=True):
        grid=tk.Frame(self.content,bg=PAGE)
        grid.pack(fill='x',pady=(0,self.px(2)))
        grid.inner_width=(self._text_width(self.content,self.px(600))-self.px(14))//2
        self.result_contexts={}
        cards=[]
        state=self.service.state()
        for kind, name, ready, issue, action, guide, guide_text, filename, hash_key, state_key, icon in (
            ('wakeup','WakeUp 课表',report,wakeup_issue,self.reveal,self.show_phone,'导入与作息设置','wakeup.csv','csv_sha256','phone_confirmed_csv','book'),
            ('apple','苹果日历',apple_report,apple_issue,self.reveal_apple,self.show_apple_phone,'查看导入步骤','calendar.ics','ics_sha256','phone_confirmed_ics','calendar')):
            card=Card(grid,self.theme,outer=PAGE,padding=20)
            body=card.body
            cards.append(card)
            heading=tk.Label(body,text='  '+name,image=self.theme.icon(icon,20),compound='left',
                             font=self.theme.text('strong')[0],fg=INK,bg=SURFACE,anchor='w')
            heading.pack(anchor='w',fill='x',pady=(0,self.px(14)))
            self.result_contexts[kind]=(kind,ready[hash_key]) if ready else None
            context=self.result_contexts[kind]
            confirmed=ready is not None and state.get(state_key)==ready[hash_key]
            if ready is not None:
                self.label('电脑文件已生成','success',(0,4),parent=body)
                self.label('已记录手机导入确认' if confirmed else '手机尚未确认导入',
                           'success' if confirmed else 'pending',(0,10),parent=body)
                self.label(f"{filename} · {ready['event_count']} 次课程",'small',(0,14),parent=body)
            elif issue is not None:
                self.label(issue.title+'。'+issue.next_step,'small',(0,14),parent=body)
                self.details.append(issue.detail)
            else:
                self.label('当前文件不可用，请重新生成。' if allow_rebuild else '获取课表后生成文件。','small',(0,14),parent=body)
            manager='在 Finder 中显示' if sys.platform=='darwin' else '打开文件位置'
            self.button(manager,action,parent=body,enabled=ready is not None,icon='folder').pack_configure(fill='x',pady=(0,self.px(6)))
            self.button(guide_text,guide,parent=body,enabled=ready is not None,link=True).pack_configure(anchor='center',pady=(0,self.px(6)))
            value=tk.BooleanVar(value=confirmed)
            check=ttk.Checkbutton(body,text='我已在手机上导入并核对',variable=value,
                command=lambda k=kind,c=context,v=value:self.confirm_result_card(k,c,v))
            check.pack(anchor='w',pady=(self.px(4),0))
            check.confirm_value=value
            check.format_context=context
            if ready is None or confirmed:
                check.state(['disabled'])
        def arrange(event):
            columns=2 if event.width>=self.px(570) else 1
            if getattr(grid,'columns',None)!=columns:
                grid.columns=columns
                for i,card in enumerate(cards):
                    card.grid(row=i//columns,column=i%columns,sticky='nsew',
                              padx=(0,self.px(14) if columns==2 and i==0 else 0),pady=(0,self.px(14)))
                grid.columnconfigure(0,weight=1,uniform='formats')
                grid.columnconfigure(1,weight=1 if columns==2 else 0,uniform='formats' if columns==2 else '')
        grid.bind('<Configure>',arrange)
        for i,card in enumerate(cards):
            card.grid(row=0,column=i,sticky='nsew',padx=(0,self.px(14) if i==0 else 0),pady=(0,self.px(14)))
            grid.columnconfigure(i,weight=1,uniform='formats')

    def confirm_result_card(self, kind, context, variable):
        variable.set(False)
        if self._confirm_format(kind, context):
            self.show_files()

    def _confirm_format(self, kind, context):
        if self.running or self.job.busy or self.closing:
            return False
        apple=kind=='apple'
        report=self.service.ready_apple_export() if apple else self.service.ready_export()
        hash_key='ics_sha256' if apple else 'csv_sha256'
        if report is None or context!=(kind,report[hash_key]):
            name='苹果日历' if apple else 'WakeUp'
            self.show_issue(explain_error(DataError(f'文件已变化或不可用，请重新打开 {name} 指引并核对后再确认。'),
                                          exporting=True,apple=apple))
            return False
        self.service.save_state(**{('phone_confirmed_ics' if apple else 'phone_confirmed_csv'):report[hash_key]})
        self.service.diagnostics.event('apple_phone_confirmed' if apple else 'wakeup_phone_confirmed',success=True)
        return True

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
        body = self.card()
        self.label(str(path), 'body', (0, 14), parent=body)
        self.button('重试打开所在位置', retry, primary=True, parent=body)
        notice = ('文件路径已复制。可在 Finder 的“前往文件夹”中粘贴。' if sys.platform == 'darwin'
                  else '文件路径已复制。可在文件资源管理器的地址栏中粘贴。')
        self.button('复制文件路径', lambda: self.copy_text(str(path), notice), parent=body, icon='copy')
        self.status_label(body)
        self.button('回到首页', self.show_home, parent=body, link=True).pack_configure(pady=0)

    def show_phone(self):
        report = self.service.ready_export()
        if report is None:
            self.show_issue(explain_error(DataError('尚无对应当前课表的导入文件。'), exporting=True))
            return
        self.phone_guide = ('wakeup', report['csv_sha256'])
        self.clear('在 iPhone 上操作', '导入 WakeUp', '按顺序完成，再核对学期日期和作息。')
        body = self.card()
        for number, text in enumerate(('将 wakeup.csv 发到手机，保存到“文件”App。',
                                       '在 WakeUp 打开导入入口，选择“Excel 导入 → 选取 CSV 文件”。',
                                       '选择 wakeup.csv，导入为新课表。',
                                       '按下方信息设置学期日期、周数和作息。'), 1):
            self.numbered(body, number, text, style='body')
        self.notice(*wakeup_setup_reminder(report))
        body = self.card()
        self.label('本次课表设置', 'section', (0, 8), parent=body)
        self.label(f"学期开始日期：{report['first_monday']}（第 1 周周一）\n"
                   f"课表周数：{report['semester_weeks']} 周（按本次课程计算）\n"
                   f"当前课程截至：{report['course_end']}\n每天节数：14 节；每周从周一开始。", parent=body)
        self.label('需要逐节修改下课时间时，关闭 WakeUp 中的“每节课时长相同”。', 'small', (0, 12), parent=body)
        table = ttk.Treeview(body, columns=('slot', 'start', 'end', 'basis'), show='headings', height=14)
        for key, title, width in [('slot', '节次', 65), ('start', '上课时间', 90), ('end', '下课时间', 90), ('basis', '时间来源（上课 / 下课）', 220)]:
            table.heading(key, text=title)
            table.column(key, width=self.px(width), minwidth=self.px(60), anchor='center')
        for number in range(1, 15):
            pair = report['slot_times'].get(number) or report['slot_times'].get(str(number))
            fallback = '自定义' if report['custom_times'] else '模板推算'
            basis = ('教务课表' if number in report['observed_start_slots'] else fallback) + ' / ' + ('教务课表' if number in report['observed_end_slots'] else fallback)
            table.insert('', 'end', values=(number, pair[0][:5], pair[1][:5], basis))
        table.pack(fill='x', pady=(0, self.px(12)))
        self.label('“教务课表”表示该时间在学校课程中有明确记录；其他时间由模板或你的设置补齐，不等同于学校官方作息表。', 'small', (0, 0), parent=body)
        self.label('重点核对第 1 周、晚课和间隔周上课的课程。更新时先导入新课表，确认无误后再处理旧课表，避免重复显示。', 'body', (0, 14))
        self.button('我已导入并核对', self.confirm_phone, primary=True)
        self.label('此按钮仅记录你的确认，助手无法检测手机中的课表。', 'small')

    def confirm_phone(self):
        if not self._confirm_format('wakeup',self.phone_guide):
            return
        self.confirmed_page('已记录 WakeUp 导入确认', 'phone-wakeup')

    def confirmed_page(self, title, page):
        self.clear('手动确认', title,
                   '此记录来自你的确认，助手无法检测手机中的课表。\n教务课表更新后，请重新获取文件并在手机手动导入。',
                   step=3, page=page)
        actions = self.row()
        self.button('查看文件与导入步骤', self.show_files, primary=True, parent=actions).pack_configure(
            side='left', fill=None, padx=(0, self.px(12)))
        self.button('返回首页', self.show_home, parent=actions).pack_configure(side='left')

    def show_apple_phone(self):
        report = self.service.ready_apple_export()
        if report is None:
            self.show_issue(explain_error(DataError('尚无对应当前课表的苹果日历文件。'), exporting=True, apple=True))
            return
        self.phone_guide = ('apple', report['ics_sha256'])
        self.clear('在 iPhone 上操作', '导入苹果日历', '文件已包含课程日期、起止时间和时区，无需另设学期日期或作息。')
        body = self.card()
        for number, text in enumerate(('在 iPhone“日历”中创建一个专用课表日历。',
                                       '将 calendar.ics 作为邮件附件发给自己。',
                                       '在 iPhone 自带“邮件”中打开附件，按提示添加到该日历。',
                                       '核对课程日期、时间、地点和教师。'), 1):
            self.numbered(body, number, text, style='body')
        body = self.card()
        self.label(f"文件包含：{report['event_count']} 次课程", 'section', (0, 6), parent=body)
        self.label('课表获取时间：' + readable_time(report['capture_fetched_at']), 'small', (0, 2), parent=body)
        if report['course_start']:
            self.label(f"当前课程日期：{report['course_start']} 至 {report['course_end']}", 'small', (0, 12), parent=body)
        self.button('打开文件位置', self.reveal_apple, parent=body, icon='folder').pack_configure(pady=0)
        self.notice('课表更新后', '每次更新都需重新导入。建议导入到新的专用课表日历，核对后再隐藏或移除旧的课表日历；不要删除其他个人日历。重复导入不保证覆盖旧课程，也不保证移除已取消的课程。')
        self.label('没有看到添加课程的选项？请保留文件，并将 iOS 版本和提示截图发给维护者。能预览附件不代表已导入。', 'small', (0, 14))
        self.button('我已导入并核对', self.confirm_apple_phone, primary=True)
        self.label('此按钮仅记录你的确认，助手无法检测手机中的课表。', 'small')

    def confirm_apple_phone(self):
        if not self._confirm_format('apple',self.phone_guide):
            return
        self.confirmed_page('已记录 苹果日历 导入确认', 'phone-apple')

    def show_issue(self, issue):
        self.details.append(issue.detail)
        self.recovery_issue = self.service.recovery_issue or self.recovery_issue
        if self.recovery_issue:
            self.show_recovery()
            return
        self.clear('操作提示',issue.title,issue.next_step,page='error')
        body = self.card()
        self.button('导出排错日志', self.show_diagnostics, primary=True, parent=body)
        actions = self.row(body)
        for label, action in (('选择已下载的课表', self.pick_capture),
                              ('重新生成导入文件', lambda: self.start(export_only=True)),
                              ('打开设置', self.show_settings)):
            self.button(label, action, parent=actions).pack_configure(side='left', padx=(0, self.px(10)), pady=0)
        self.button('查看处理详情', self.show_details, parent=body, link=True).pack_configure(pady=(self.px(10), 0))

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
        dialog = self.dialog('导出排错日志',720,560)
        body = ttk.Frame(dialog,padding=self.px(24))
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='选择出问题的操作，保存日志 ZIP 后发给维护者。', wraplength=self.px(650)).pack(anchor='w', pady=(0, 12))
        status_names = {'success': '已完成', 'partial': '部分失败', 'failed': '失败', 'cancelled': '已取消',
                        'running': '进行中', 'interrupted': '意外中断'}
        kind_names = {'sync': '获取课表', 'export': '生成导入文件', 'startup': '启动助手', 'settings': '保存设置',
                      'term_settings': '确认学期', 'bookmark_confirmation': '确认书签', 'activity': '其他操作'}
        choices = [f"{readable_time(r['started_at'])} · {kind_names.get(r['kind'], '操作')} · {status_names.get(r['status'], '未知状态')} · {r['operation_id'][:8]}" for r in records]
        selection = ttk.Combobox(body, values=choices, state='readonly', width=75)
        selection.pack(fill='x', pady=(0, 14))
        default = 0 if records[0]['status'] == 'failed' else next((i for i, r in enumerate(records) if r['kind'] in ('sync', 'export')), 0)
        selection.current(default)
        ttk.Label(body, text='日志会替换姓名、学号、课程文字及标识，但仍包含日期、节次等信息。请仅发给维护者，不要公开上传。\n日志默认在本机保留 30 天，总量上限为 50 MB。', wraplength=self.px(650)).pack(anchor='w', pady=(0, 12))
        if log.storage_warning:
            ttk.Label(body, text='部分日志未能保存到磁盘。将尝试导出内存中的记录，请选择可写入的文件夹。', wraplength=self.px(650)).pack(anchor='w', pady=(0, 10))
        ttk.Label(body, text='网页排错信息（可选）\n浏览器无法下载日志时，可将“复制排错信息”得到的内容粘贴在这里。').pack(anchor='w')
        extra = tk.Text(body,height=6,wrap='word',font=self.theme.font(12),relief='solid',borderwidth=1,highlightthickness=1,highlightcolor=GREEN)
        extra.pack(fill='both', expand=True, pady=(6, 12))
        def export():
            chosen = records[selection.current()]
            target = filedialog.asksaveasfilename(parent=dialog, title='保存排错日志', defaultextension='.zip',
                initialfile='课表助手排错日志-' + chosen['operation_id'][:8] + '.zip',
                filetypes=[('排错日志（ZIP）', '*.zip')])
            if not target:
                return
            try:
                path = log.export(target, chosen['operation_id'], browser_text=extra.get('1.0', 'end'))
            except Exception as error:
                log.exception(error, stage='support_export_failed')
                self.details.append(str(error) if isinstance(error, ValueError) else type(error).__name__)
                messagebox.showerror('日志未保存', explain_error(error).next_step if isinstance(error, ValueError) else
                    '请检查磁盘空间和文件夹权限，或换一个位置重新保存。', parent=dialog)
                return
            self.locate_file(path)
            dialog.destroy()
        save = ttk.Button(body,text='保存日志并定位文件',command=export,style=self.theme.button_style('Primary'))
        self.bind_button(save)
        save.pack(side='bottom',anchor='e',before=body.winfo_children()[0])
        def fit_dialog(event):
            for child in body.winfo_children():
                if isinstance(child,ttk.Label):
                    child.configure(wraplength=max(self.px(300),event.width-self.px(48)))
        body.bind('<Configure>',fit_dialog)

    def show_details(self):
        dialog = self.dialog('处理详情',760,480)
        footer = ttk.Frame(dialog, padding=self.px(10))
        footer.pack(side='bottom', fill='x')
        self.button('关闭',dialog.destroy,parent=footer).pack_configure(side='right',pady=0)
        self.button('导出排错日志',self.show_diagnostics,parent=footer).pack_configure(side='right',padx=(0,self.px(10)),pady=0)
        area = tk.Text(dialog, wrap='word', font=self.theme.font(12),padx=self.px(16),pady=self.px(12),
                       relief='flat', highlightthickness=0, fg=TEXT)
        area.pack(fill='both', expand=True)
        area.insert('end', '\n\n'.join(self.details[-35:]) or '暂无处理记录。')
        area.configure(state='disabled')

    def show_help(self):
        self.clear('帮助与排错','帮助与排错','先找到对应的情况，再按提示继续。',page='help')
        groups=[
            ('已下载课表，但没有导入文件？',
             '点击“选择已下载的课表”，选中 shsmu-capture-…json。助手会检查并生成导入文件。\nJSON 不能直接导入 WakeUp 或苹果日历，也不要修改扩展名。取消选文件不会中断原来的等待。',
             [('选择已下载的课表',self.pick_capture),('选择下载文件夹',self.pick_downloads)]),
            ('找不到课表书签？',
             '登录失效：在安装书签的浏览器中重新登录教务首页，再点击“同步医学院课表”。\n换了浏览器：先安装课表书签，再登录教务；无需搬移已保存的课表。',
             [('查看书签安装说明',lambda:self.show_setup(2))]),
            ('电脑文件生成后，手机没有课程？',
             '电脑文件更新后，仍需在手机重新导入。确认已手动导入，并切换到新课表或勾选新的课表日历。\n已保存过课表时，可直接重新生成导入文件，无需再次读取教务。修改作息只影响 WakeUp 文件。',
             [('查看文件与导入步骤',self.show_files),('重新生成导入文件',lambda:self.start(export_only=True))])]
        body = self.card()
        for index, (title,copy,actions) in enumerate(groups):
            if index:
                self.rule(body, (14, 16))
            self.label(title,'strong',(0,6),parent=body)
            self.label(copy,'small',(0,6),parent=body)
            row=self.row(body)
            for label,action in actions:
                self.button(label,action,parent=row,link=True,enabled=not self.running).pack_configure(side='left',padx=(0,self.px(18)),pady=0)
        self.label('找不到文件：查看浏览器下载列表，再回助手选择该文件。\n读取未完成：按网页提示继续或重新读取；不完整结果不会替换已保存的课表。','small',(2,16))
        body = self.card()
        self.label('仍未解决？','strong',(0,6),parent=body)
        self.label('导出排错日志发给维护者。日志包含日期、节次等信息，请仅发给维护者，不要公开上传。','small',(0,14),parent=body)
        actions = self.row(body)
        self.button('导出排错日志',self.show_diagnostics,primary=True,parent=actions).pack_configure(side='left',fill=None,pady=0,padx=(0,self.px(14)))
        self.button('查看处理详情',self.show_details,link=True,parent=actions).pack_configure(side='left',pady=0)
        self.notice('遇到安全警告时','请先核对软件下载来源。无法判断安全警告时，将提示截图发给维护者，确认后再继续。不要关闭安全防护。')
        row = self.row(pady=(2, 0))
        tk.Label(row,image=self.theme.icon('shield',14),bg=PAGE).pack(side='left',padx=(0,self.px(8)))
        self.label('课表在本机处理；手机端需要手动导入。','small',(0,0),parent=row)

    def pick_capture(self):
        if getattr(self, 'recovery_issue', None):
            self.show_recovery()
            return
        if self.running and self.job.stage != 'waiting':
            self.status.set('正在处理课表，请完成后再选择文件。')
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
            selected = filedialog.askopenfilename(parent=self.window, title='选择已下载的课表文件',
                initialdir=initialdir,
                filetypes=[('课表文件（shsmu-capture-*.json）', 'shsmu-capture-*.json'), ('JSON 文件', '*.json')])
            if selected:
                self.service.diagnostics.event('file_picker_selected')
                if not was_waiting:
                    self.start(capture=Path(selected))
                elif self.job.submit_file(selected):
                    pass
                elif self.job.busy:
                    # The waiter moved on while the dialog was open; never drop the choice silently.
                    self.status.set('助手已开始处理其他课表文件，请完成后再选择这个文件。')
                elif self.running:
                    # The wait ended while the dialog was open. Import the choice
                    # after that job's pending 'finished' event has been handled.
                    chosen = Path(selected)
                    self.pending = lambda: self.start(capture=chosen)
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
            selected = filedialog.askdirectory(parent=self.window, title='选择浏览器下载文件夹')
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
        selected = filedialog.askdirectory(parent=self.window, title='选择已有课表文件夹或空文件夹')
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
                messagebox.showerror('这个文件夹不能用于保存课表', '所选文件夹已有其他内容，且不是助手的课表文件夹。请选择原课表文件夹，或新建一个空文件夹。', parent=self.window)
                return
            if not messagebox.askyesno('在此文件夹新建课表？', '将为此文件夹建立独立记录，不会复制、合并或覆盖其他文件夹中的课表。', parent=self.window):
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
        try:
            config=self.service.config()
        except DataError:
            self.show_settings_details()
            return
        self.clear('设置','课表设置','按你的使用习惯设置。',page='settings')
        body = self.card(padding=20)
        for index, (title,copy,button,action) in enumerate((
            ('学期与读取范围',semester_label(config['semester'])+'\n'+config['start']+' 至 '+str(date.fromisoformat(config['end_exclusive'])-timedelta(days=1)),'修改',lambda:self.show_settings_details(0)),
            ('课表保存文件夹',str(self.service.root),'更换课表文件夹',self.pick_root),
            ('WakeUp 作息设置','核对学期开始日期、周数与每节课时间。','查看设置',lambda:self.show_settings_details(1)),
            ('浏览器下载文件夹',str(capture_folder(config,self.service.config_path)),'选择下载文件夹',self.pick_downloads))):
            if index:
                self.rule(body, (16, 16))
            row=self.row(body)
            self.button(button,action,parent=row).pack_configure(side='right',padx=(self.px(14),0),pady=0)
            column=tk.Frame(row,bg=SURFACE)
            column.pack(side='left',fill='x',expand=True)
            self.label(title,'strong',(0,4),parent=column)
            self.label(copy,'small',(0,0),parent=column)
        self.notice('保留已有课表记录','选择已有课表文件夹可继续使用原记录；选择空文件夹可新建独立课表。此操作只切换位置，不搬移或合并数据。')
        self.button('学期、作息与文件夹详细设置',self.show_settings_details,link=True)

    def show_settings_details(self, selected_tab=0):
        if self.recovery_issue:
            self.show_recovery()
            return
        if self.running:
            return
        self.clear('设置','课表设置',page='settings-details')
        self.button('返回设置概览',self.show_settings,link=True,icon=None).pack_configure(pady=(0,self.px(8)))
        try:
            config = self.service.config()
        except DataError as error:
            self.record_error(error, 'settings_read_failed')
            config = load_settings(self.service.resources / 'config.example.json')
            self.label('无法读取原学期设置。下方为示例值，请核对后再保存；已保存的课表不会因此删除。')
        body = self.card(padding=12)
        notebook = ttk.Notebook(body)
        notebook.pack(fill='both', expand=True)
        term_tab, times_tab, storage_tab = [ttk.Frame(notebook, style='Card.TFrame', padding=self.px(16)) for _ in range(3)]
        for tab, text in [(term_tab, '学期'), (times_tab, '作息时间'), (storage_tab, '文件夹')]:
            notebook.add(tab, text=text)
        notebook.select(selected_tab)
        year, term = config['semester'].split(':')
        self.label('这里设置读取教务课表的日期范围，不是个人开课或结课日期。使用当前学期预设时通常无需修改。', 'small', (0, 14), parent=term_tab)
        year_var = tk.StringVar(value=year.split('-')[0])
        term_var = tk.StringVar(value=term)
        start_var = tk.StringVar(value=config['start'])
        end_var = tk.StringVar(value=str(date.fromisoformat(config['end_exclusive']) - timedelta(days=1)))
        for title, variable in [('学年开始年份（例如 2026）', year_var), ('学期（1 或 2）', term_var),
                                ('读取开始日期（年-月-日）', start_var), ('读取结束日期（包含当天）', end_var)]:
            self.label(title, 'body', (0, 6), parent=term_tab)
            ttk.Entry(term_tab, textvariable=variable, width=25).pack(anchor='w', pady=(0, self.px(14)))
        self.label('更改学期或日期范围后，请按提示更新浏览器书签。旧课表记录会保留。', 'small', (0, 0), parent=term_tab)
        slots_broken = False
        try:
            times = load_slot_times(self.service.root) or slot_times()
        except DataError as error:
            self.record_error(error, 'slots_read_failed')
            slots_broken = True
            times = slot_times()
            self.label('无法读取原作息设置。下方为模板时间，请核对后再保存。', parent=times_tab)
        original_times = [[a[:5], b[:5]] for a, b in times.values()]
        self.label('使用 24 小时制，例如 08:00。此设置用于生成 WakeUp 文件，不影响苹果日历。模板时间不代表学校官方作息；生成文件时会核对课程起止时间。', 'small', (0, 12), parent=times_tab)
        grid = tk.Frame(times_tab, bg=SURFACE)
        grid.pack(anchor='w')
        head_font, head_colour = self.theme.text('strong')
        cell_font, cell_colour = self.theme.text('body')
        for col, text in enumerate(('节次', '上课时间', '下课时间')):
            tk.Label(grid, text=text, font=head_font, fg=head_colour, bg=SURFACE).grid(row=0, column=col, padx=self.px(12), pady=self.px(4))
        fields = []
        for n, pair in enumerate(original_times, 1):
            variables = [tk.StringVar(value=v) for v in pair]
            fields.append(variables)
            tk.Label(grid, text=str(n), font=cell_font, fg=cell_colour, bg=SURFACE).grid(row=n, column=0, padx=self.px(12))
            for col, variable in enumerate(variables, 1):
                ttk.Entry(grid, textvariable=variable, width=9).grid(row=n, column=col, padx=self.px(8), pady=self.px(3))
        folder_var = tk.StringVar(value=str(capture_folder(config, self.service.config_path)))
        self.label('浏览器下载文件夹', 'section', (0, 8), parent=storage_tab)
        folder_entry = ttk.Entry(storage_tab, textvariable=folder_var, width=48)
        folder_entry.pack(fill='x', pady=(0, self.px(10)))
        def select_folder():
            selected = filedialog.askdirectory(parent=self.window, title='选择浏览器下载文件夹')
            if selected:
                folder_var.set(selected)
        self.button('选择文件夹', select_folder, parent=storage_tab, icon='folder')
        self.label('课表保存文件夹', 'section', (10, 6), parent=storage_tab)
        self.label(str(self.service.root), 'small', (0, 10), parent=storage_tab)
        self.button('更换课表文件夹', self.pick_root, parent=storage_tab)
        self.label('选择已有课表文件夹可继续使用原记录；选择空文件夹可新建独立课表。此操作只切换位置，不搬移或合并数据。', 'small', (0, 0), parent=storage_tab)
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
                current = self.service.current()
                if current and term_key(current['scope']) != term_key(updated):
                    if not messagebox.askyesno('保存新的学期或日期范围？', '之后将按新范围接收课表，旧课表记录会保留。保存后还需更新浏览器书签。', parent=self.window):
                        return
                self.service.save_settings(updated, values if slots_broken or values != original_times else None)
                self.show_home()
            except (ValueError, OverflowError) as error:
                self.record_error(error, 'settings_input_failed')
                messagebox.showerror('日期填写有误', '年份请填写四位数字；日期请使用“年-月-日”格式，例如 2026-09-07。请检查日期是否真实存在。', parent=self.window)
            except Exception as error:
                self.record_error(error, 'settings_failed')
                issue = explain_error(error)
                messagebox.showerror('设置未保存', issue.title + '\n' + issue.next_step + '\n请修改后重新保存。', parent=self.window)
        self.button('保存设置', save, primary=True)

    def close(self):
        if self.disposed:
            return
        # A finished worker cannot deliver another event; never wait for one.
        if self.running and not self.job.busy:
            self.running = False
        if self.closing and self.running:
            return
        if self.running:
            self.closing = True
            self.pending = None
            self.job.cancel()
            self.status.set('正在关闭助手；已开始的保存会完成后再退出。')
        else:
            self.dispose()

    def dispose(self):
        if self.disposed:
            return
        self.disposed = True
        if getattr(self,'progress',None) is not None and self.progress.winfo_exists():
            self.progress.stop()
        self.service.diagnostics.event('window_closed')
        for process, callback in self.reveal_checks.items():
            if callback:
                self.window.after_cancel(callback)
            self.stop_location(process)
        self.reveal_checks.clear()
        if self.poll_id:
            self.window.after_cancel(self.poll_id)
            self.poll_id = None
        for handle in tuple(self.ui_after):
            self.window.after_cancel(handle)
        self.ui_after.clear()
        self.window.update_idletasks()
        for command in self.mac_commands:
            self.window.deletecommand(command)
        self.mac_commands = []
        self.window.destroy()
        self.window.report_callback_exception = None
        self.status = None
        self.wrapping = []
        self.pictures = {}


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
