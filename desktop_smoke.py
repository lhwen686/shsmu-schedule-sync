"""Offline packaged-runtime check, using synthetic data and an explicit report path."""
import csv
import io
import json
import os
import sys
import tempfile
from pathlib import Path


def self_test(report_path):
    from desktop import AssistantWindow
    from desktop_service import DesktopService
    from sync import atomic_write, json_bytes, load_current, month_ranges
    import tkinter as tk
    import icalendar
    import tzdata
    report = {'status': 'FAIL', 'kind': 'synthetic packaged runtime',
              'frozen': bool(getattr(sys, 'frozen', False)), 'python_on_path': False}
    window = None
    ui = None
    try:
        import shutil
        report['python_on_path'] = shutil.which('python') is not None
        if os.name == 'nt':
            import ctypes
            report['elevated'] = bool(ctypes.windll.shell32.IsUserAnAdmin())
        with tempfile.TemporaryDirectory(prefix='课表 验收 ') as folder:
            root = Path(folder)
            service = DesktopService(root)
            config = service.initialize()
            def shown(text):
                return any('text' in child.keys() and str(child.cget('text')) == text
                           for child in ui.content.winfo_children())

            window = tk.Tk()
            window.withdraw()
            ui = AssistantWindow(window, root)
            assert shown('选择要导入的学期')
            ui.confirm_term()
            assert shown('给浏览器添加课表按钮')
            ui.confirm_bookmark()
            assert shown('首次导入 · 下一步获取课表')
            ui.dispose()
            window, ui = None, None
            window = tk.Tk()
            window.withdraw()
            ui = AssistantWindow(window, root)
            window.update_idletasks()
            assert shown('给浏览器添加课表按钮')
            assert not shown('每次更新，只走这条流程')
            ui.dispose()
            window, ui = None, None
            row = {'ID': 12, 'Curriculum': '运行验证课程', 'CurriculumID': 99,
                   'CSID': 100, 'MCSID': '11,12', 'CourseCode': 'DEMO001', 'CurriculumType': '必修课',
                   'Start': '2026-09-07T08:00:00', 'End': '2026-09-07T09:30:00',
                   'ClassroomAcademy': '示例教室', 'AllDay': False}
            detail = {'ID': 2001, 'DetailID': 1001, 'TeachingCalendarID': 3000,
                      'CurriculumID': 99, 'CurriculumScheduleIDs': '|11||12|',
                      'ClassTime': '2026-09-07T00:00:00', 'Teacher': '示例教师',
                      'Content': '', 'IsDel': False, 'PKCIndex': '|1||2|', 'WeekNum': 1}
            responses = []
            for start, end in month_ranges(config['start'], config['end_exclusive']):
                events = [row] if start <= row['Start'][:10] < end else []
                responses.append({'path': '/Home/GetCurriculumTable', 'params': {'Start': start, 'End': end},
                    'response': {'Title': '2026-2027 学年 第1 学期' if events else None, 'List': events}})
            responses.append({'path': '/Home/GetCalendarTable',
                'params': {k: str(row.get(k) or '') for k in ('MCSID', 'CSID', 'CurriculumID', 'XXKMID', 'CurriculumType')},
                'response': [detail]})
            capture = root / 'shsmu-capture-runtime.json'
            capture.write_text(json.dumps({'format': 'shsmu-capture-v1', 'complete': True,
                'origin': 'https://jwstu.shsmu.edu.cn', 'config': config, 'account_key': 'a' * 64,
                'fetched_at': '2026-09-06T00:00:00Z', 'collector_revision': '2026-09-06.8',
                'responses': responses}), encoding='utf-8')
            result = service.run(capture=capture)
            assert result['issue'] is None and result['report']['event_count'] == 1
            assert result['apple_issue'] is None and result['apple_report']['event_count'] == 1
            calendar_bytes = (root / 'output/calendar.ics').read_bytes()
            event = icalendar.Calendar.from_ical(calendar_bytes).walk('VEVENT')[0]
            assert str(event['SUMMARY']) == '运行验证课程'
            assert str(event['LOCATION']) == '示例教室'
            assert '示例教师' in str(event['DESCRIPTION'])
            assert event.decoded('DTSTART').isoformat() == '2026-09-07T08:00:00+08:00'
            assert event.decoded('DTEND').isoformat() == '2026-09-07T09:30:00+08:00'
            assert service.ready_apple_export() == result['apple_report']
            csv_rows = list(csv.reader(io.StringIO((root / 'output/wakeup.csv').read_text(encoding='utf-8-sig'))))
            assert csv_rows[1] == ['运行验证课程', '1', '1', '2', '示例教师', '示例教室', '1']
            uid = load_current(root)['events'][0]['uid']
            pointer = (root / 'data/current.json').read_bytes()
            assert service.run(capture=capture)['imported'].duplicate
            assert load_current(root)['events'][0]['uid'] == uid
            assert (root / 'data/current.json').read_bytes() == pointer
            assert (root / 'output/calendar.ics').read_bytes() == calendar_bytes
            window = tk.Tk()
            window.withdraw()
            ui = AssistantWindow(window, root)
            assert shown('每次更新，只走这条流程')
            ui.show_setup(2)
            window.update_idletasks()
            ui.show_result(result)
            window.update_idletasks()
            ui.show_phone()
            window.update_idletasks()
            ui.show_apple_phone()
            window.update_idletasks()
            ui.confirm_apple_phone()
            assert service.state()['phone_confirmed_ics'] == result['apple_report']['ics_sha256']
            assert 'phone_confirmed_csv' not in service.state()
            ui.show_settings()
            window.update_idletasks()
            ui.dispose()
            window, ui = None, None
            report.update(status='PASS', checks=['bundled resources', 'first-run and interrupted onboarding startup',
                'completed capture opens update home', 'local import and WakeUp CSV',
                'Apple ICS dates and content', 'repeat import preserves UID and ICS', 'bundled onboarding image',
                'Tk result, settings and both iPhone guides', 'independent synthetic phone confirmation'],
                data_outside_bundle=not str(root).startswith(str(getattr(sys, '_MEIPASS', '__not_frozen__'))),
                gui_os='Windows' if os.name == 'nt' else os.name)
            if getattr(sys, 'frozen', False):
                bundle = Path(sys._MEIPASS).resolve()
                report['dependency_paths_in_bundle'] = all(Path(m.__file__).resolve().is_relative_to(bundle)
                                                          for m in (icalendar, tzdata, tk))
    except Exception as error:
        report['error_type'] = type(error).__name__
    finally:
        if ui is not None:
            ui.dispose()
        elif window is not None:
            window.destroy()
        atomic_write(Path(report_path).resolve(), json_bytes(report))
    if report['status'] != 'PASS':
        raise SystemExit(1)
