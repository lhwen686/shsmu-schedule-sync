"""Chinese Windows front end. Browser login and bookmark installation stay manual."""
from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
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
from sync import atomic_write, capture_folder, json_bytes, load_current, load_settings
from wakeup import load_slot_times, slot_times

BG, INK, GREEN, MUTED = '#edf4f0', '#213d36', '#176b54', '#587268'


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
    subprocess.Popen(['explorer.exe', '/select,', str(path)])


class AssistantWindow:
    def __init__(self, window, data_root=None):
        self.window = window
        self.base = default_data_root()
        self.preference_path = self.base / 'preferences.json'
        selected = data_root
        missing_saved_root = False
        if selected is None:
            try:
                prefs = json.loads(self.preference_path.read_text(encoding='utf-8'))
                candidate = prefs.get('data_root')
                if isinstance(candidate, str) and Path(candidate).is_absolute():
                    selected = candidate
                    missing_saved_root = not Path(candidate).is_dir()
            except (OSError, ValueError, AttributeError):
                pass
        self.service = DesktopService(selected or self.base)
        self.job = DesktopJob(self.service)
        self.running = False
        self.closing = False
        self.pending = None
        self.details = []
        self.last_result = None
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
        self.window.report_callback_exception = lambda kind, error, tb: self.show_issue(explain_error(error))
        self._style()
        header = ttk.Frame(window, padding=(28, 18))
        header.pack(fill='x')
        ttk.Label(header, text='医学院课表助手', style='Brand.TLabel').pack(side='left')
        ttk.Label(header, text=f'{APP_VERSION} · iPhone / WakeUp', style='Muted.TLabel').pack(side='right')
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
            if missing_saved_root:
                raise DataError('上次使用的数据目录暂时找不到，请在设置中选择原项目目录；没有新建另一份课表。')
            self.service.initialize()
            self.show_home()
        except Exception as error:
            self.show_issue(explain_error(error))
        self.poll_id = self.window.after(100, self.poll)

    def _style(self):
        style = ttk.Style(self.window)
        style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 11))
        style.configure('TFrame', background=BG)
        style.configure('TLabel', background=BG, foreground=INK)
        style.configure('Brand.TLabel', font=('Microsoft YaHei UI', 16, 'bold'))
        style.configure('Muted.TLabel', foreground=MUTED)
        style.configure('Card.TFrame', background='white')
        style.configure('Body.TLabel', background='white', foreground=INK)
        style.configure('Small.TLabel', background='white', foreground=MUTED, font=('Microsoft YaHei UI', 10))
        style.configure('Title.TLabel', background='white', foreground=INK, font=('Microsoft YaHei UI', 23, 'bold'))
        style.configure('Section.TLabel', background='white', foreground=INK, font=('Microsoft YaHei UI', 14, 'bold'))
        style.configure('TButton', padding=(14, 9), background='#e6eee9', foreground=INK)
        style.configure('Primary.TButton', background=GREEN, foreground='white', padding=(20, 12), font=('Microsoft YaHei UI', 12, 'bold'))
        style.map('Primary.TButton', background=[('disabled', '#d8e4dc'), ('active', '#12563f')], foreground=[('disabled', MUTED)])
        style.configure('TEntry', padding=6)
        style.configure('TNotebook', background='white')
        style.configure('TNotebook.Tab', padding=(16, 8))
        self.table_font = tkfont.Font(root=self.window, family='Microsoft YaHei UI', size=11)
        style.configure('Treeview', font=self.table_font, rowheight=self.table_font.metrics('linespace') + 10)

    def _wheel(self, event):
        # Leave comboboxes, text fields and native dialogs their normal scroll behavior.
        if event.widget.winfo_toplevel() == self.window and event.widget.winfo_class() not in ('Text', 'TCombobox'):
            self.canvas.yview_scroll(-int(event.delta / 120), 'units')

    def _resize(self, event):
        self.canvas.itemconfigure(self.canvas_item, width=event.width)
        for widget in self.wrapping:
            if widget.winfo_exists():
                widget.configure(wraplength=max(400, event.width - 64))

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

    def copy_text(self, text):
        self.window.clipboard_clear()
        self.window.clipboard_append(text)
        self.window.update_idletasks()
        self.status.set('已复制。请在平时登录教务的浏览器地址栏粘贴并回车。')

    def status_label(self):
        widget = ttk.Label(self.content, textvariable=self.status, style='Small.TLabel',
                           wraplength=max(400, self.canvas.winfo_width() - 64))
        widget.pack(anchor='w', fill='x', pady=(0, 12))
        self.wrapping.append(widget)

    def show_home(self):
        if self.running:
            self.show_work()
            return
        step = self.service.setup_step()
        if step:
            self.show_setup(step)
            return
        current = load_current(self.service.root)
        self.clear('每次更新，只走这条流程', '把课表装进手机',
                   '获取课表  →  自动生成文件  →  发给自己  →  在 iPhone 导入')
        if current:
            self.label(f"已保存 {len(current['events'])} 次课程 · {semester_label(current['scope']['semester'])}", 'Section.TLabel')
            self.label('上次学校采集：' + readable_time(current.get('capture_fetched_at')), 'Small.TLabel')
            days = [e['date'] for e in current['events']]
            if days:
                self.label(f'本次已公布课程：{min(days)} 至 {max(days)}', 'Small.TLabel')
        else:
            self.label('第一次使用？下面的按钮会带你完成一次完整导入。')
        self.button('获取我的课表', self.start, primary=True)
        self.label('助手会先准备好接收，再提示你去浏览器登录教务首页。', 'Small.TLabel')
        report = self.service.ready_export()
        if report:
            self.button('找到要发到手机的文件', self.reveal)
            self.button('查看 iPhone 导入指引与作息', self.show_phone)
        elif current:
            self.label('需要再次生成手机文件？到“遇到问题”点击“重新生成导入文件”。', 'Small.TLabel')
        self.label('已经先下载了课表？', 'Section.TLabel', (16, 10))
        self.button('文件已经下载', self.pick_capture)
        self.label('文件生成后，手机仍需要手动导入；WakeUp 不会自动跟随电脑更新。', 'Small.TLabel', (18, 0))

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
            self.label('图中以 Chrome 为例；Edge、Firefox 的对应栏位见下方说明。', 'Small.TLabel')
            self.label('Edge 叫“收藏夹栏”，Chrome 叫“书签栏”，Firefox 叫“书签工具栏”。按 Ctrl + Shift + B 显示。安装和登录请使用同一个浏览器。', 'Small.TLabel')
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
        if self.running or self.job.busy:
            return
        self.details = []
        self.last_result = None
        self.running = True
        self.status.set('正在准备接收…' if capture is None and not export_only else '正在准备处理…')
        self.show_work()
        self.job.start(capture=capture, export_only=export_only)

    def show_work(self):
        self.clear('电脑正在处理 · 请保持助手打开', '获取你的课表',
                   '这里会显示接收和处理结果。浏览器中的学校页面显示实际采集进度。')
        self.status_label()
        self.button('复制教务首页地址', lambda: self.copy_text(HOME_URL))
        self.label('准备好接收后，在添加了课表按钮的同一个浏览器正常登录教务首页，看到本人学号后点击“同步医学院课表”。', 'Body.TLabel')
        self.label('请保持学校页面打开。完整读取通常需要几分钟；以网页实际进度为准。', 'Small.TLabel')
        self.picker_button = self.button('文件已经下载', self.pick_capture, enabled=self.job.stage == 'waiting')
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
        if result['issue']:
            self.show_issue(result['issue'])
            return
        report, imported = result['report'], result['imported']
        self.clear('电脑上的文件已生成 · 下一步在手机导入', '课表准备好了',
                   f"已生成 {report['event_count']} 次课程的 WakeUp 文件。")
        self.label('学校采集时间：' + readable_time(report['capture_fetched_at']), 'Small.TLabel')
        self.label(f"本次已公布课程：{report['course_start']} 至 {report['course_end']}", 'Small.TLabel')
        if imported:
            summary = imported.diff['summary']
            self.label(f"新增 {summary['ADDED']}  ·  删除 {summary['REMOVED']}  ·  修改 {summary['CHANGED']}", 'Section.TLabel')
            if imported.duplicate:
                self.label('使用的是已处理过的同一文件，没有重新访问学校。', 'Small.TLabel')
            for warning in imported.diff.get('warnings', []):
                self.label('请核对：' + warning)
        else:
            self.label('本次由已保存课表重新生成，没有重新访问学校。', 'Small.TLabel')
        self.button('找到要发到手机的文件', self.reveal, primary=True)
        self.label('在打开的文件夹里，将选中的 wakeup.csv 拖到微信“文件传输助手”或 QQ“我的手机”，由你点击发送。')
        self.button('下一步：iPhone 怎么导入', self.show_phone)
        self.label('手机尚未由助手确认导入。不要把电脑生成成功理解为手机已更新。', 'Small.TLabel')

    def reveal(self):
        if self.service.ready_export() is None:
            self.show_issue(explain_error(DataError('导入文件已过期或被移动，请重新生成导入文件。'), exporting=True))
            return
        reveal_file(self.service.root / 'output/wakeup.csv')

    def show_phone(self):
        report = self.service.ready_export()
        if report is None:
            self.show_issue(explain_error(DataError('尚无对应当前课表的导入文件。'), exporting=True))
            return
        self.clear('最后一步 · 在 iPhone 上操作', '把文件导入 WakeUp',
                   '1. 在手机微信 / QQ 接收 wakeup.csv，保存到“文件”App。\n'
                   '2. WakeUp → 导入课表 → Excel 导入 → 选取 CSV 文件。\n'
                   '3. 选择刚才的文件，导入到一个新课表。\n'
                   '4. 按下面的设置卡检查日期和上课时间。')
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
        if report is not None:
            self.service.save_state(phone_confirmed_csv=report['csv_sha256'])
            self.clear('本次流程已走完', '已记录你的手机核对', '以后学校课表有更新，再打开助手获取新课表，并重新在 WakeUp 导入。')
            self.button('回到首页', self.show_home, primary=True)

    def show_issue(self, issue):
        self.details.append(issue.detail)
        self.clear('处理提示', issue.title, issue.next_step)
        self.button('文件已经下载', self.pick_capture)
        self.button('重新生成导入文件', lambda: self.start(export_only=True))
        self.button('打开设置', self.show_settings)
        self.button('查看技术详情', self.show_details)

    def show_details(self):
        dialog = tk.Toplevel(self.window)
        dialog.title('处理详情（仅保留在本窗口）')
        dialog.geometry('760x440')
        area = tk.Text(dialog, wrap='word', font=('Microsoft YaHei UI', 10), padx=16, pady=12)
        area.pack(fill='both', expand=True)
        area.insert('end', '\n\n'.join(self.details[-35:]) or '暂时没有处理记录。')
        area.configure(state='disabled')
        ttk.Button(dialog, text='关闭', command=dialog.destroy).pack(pady=10)

    def show_help(self):
        self.clear('遇到问题时，从这里继续', '不用从头再来')
        self.button('文件已经下载', self.pick_capture)
        self.label('选择完整课表文件。取消选择会继续原来的等待。', 'Small.TLabel')
        self.button('选择下载文件夹', self.pick_downloads)
        self.button('重新生成导入文件', lambda: self.start(export_only=True), enabled=not self.running)
        self.label('使用已保存课表，不再请求学校。课表已变化或作息已修改时，可重新生成。', 'Small.TLabel')
        self.button('重新查看书签安装引导', lambda: self.show_setup(2), enabled=not self.running)
        self.button('查看技术详情', self.show_details)
        self.label('登录过期：在添加了课表按钮的浏览器中正常打开教务首页并登录，然后点击课表按钮。\n'
                   '换了浏览器：在新浏览器重新添加课表按钮并正常登录；已保存的课表不用搬动。\n'
                   '文件在别处：从浏览器下载列表查看位置，然后选择已下载文件。\n'
                   '页面读取失败：按页面提示继续或重新采集；已保存的完整课表不会被不完整结果替换。\n'
                   '手机没有课程：先确认已手动导入，并切换到新导入的课表。')

    def pick_capture(self):
        if self.running and self.job.stage != 'waiting':
            self.status.set('正在核对或保存课表，请等待本次处理结束。')
            return
        was_waiting = self.running
        self.job.picker_open.set()
        try:
            folder = capture_folder(self.service.config(), self.service.config_path)
            selected = filedialog.askopenfilename(parent=self.window, title='选择从浏览器下载的完整课表',
                initialdir=str(folder if folder.is_dir() else downloads_folder()),
                filetypes=[('完整课表文件', 'shsmu-capture-*.json'), ('JSON 文件', '*.json')])
            if selected:
                if was_waiting:
                    self.job.submit_file(selected)
                else:
                    self.start(capture=Path(selected))
        finally:
            self.job.picker_open.clear()

    def pick_downloads(self):
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
        if not candidate.config_path.is_file() and not (candidate.root / 'data/current.json').is_file():
            if any(candidate.root.iterdir()):
                messagebox.showerror('请选择课表目录或空目录', '这个非空目录不是已有课表项目。请选原项目目录，或新建一个空文件夹。', parent=self.window)
                return
            if not messagebox.askyesno('新建独立课表', '为这个目录新建独立课表？不会复制其他人的课表或上传配置。', parent=self.window):
                return
        candidate.initialize()
        # Validate history before switching; never migrate it or reset identities.
        load_current(candidate.root)
        atomic_write(self.preference_path, json_bytes({'data_root': str(candidate.root)}))
        self.service, self.job = candidate, DesktopJob(candidate)
        self.last_result = None
        self.show_home()

    def show_settings(self):
        if self.running:
            return
        self.clear('设置 · 不需要修改配置文件', '学期、作息和保存位置')
        try:
            config = self.service.config()
        except DataError:
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
        except DataError:
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
            except (ValueError, OverflowError):
                messagebox.showerror('请检查日期', '年份使用四位数字，日期使用有效的年-月-日，例如 2026-09-07。', parent=self.window)
            except Exception as error:
                issue = explain_error(error)
                messagebox.showerror('设置尚未保存', issue.detail, parent=self.window)
        self.button('保存设置', save, primary=True)

    def close(self):
        if self.running:
            self.closing = True
            self.job.cancel()
            self.status.set('正在安全结束；保存已经开始时会等待它完成。')
        else:
            self.dispose()

    def dispose(self):
        if self.poll_id:
            self.window.after_cancel(self.poll_id)
            self.poll_id = None
        self.window.update_idletasks()
        self.window.destroy()


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
    AssistantWindow(window, args.data_root)
    window.mainloop()


if __name__ == '__main__':
    main()
