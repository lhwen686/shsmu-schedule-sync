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
            assert shown('文件已经下载')
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
            committed_operation = service.diagnostics.record['operation_id']
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
            # A same-day extra schedule must not enter either exported format.
            import copy
            mixed = json.loads(capture.read_text(encoding='utf-8'))
            for record in mixed['responses']:
                if record['path'] == '/Home/GetCurriculumTable' and record['response']['List']:
                    record['response']['List'][0]['CourseCount'] = 2
                elif record['path'] == '/Home/GetCalendarTable':
                    direct = record['response'][0]
                    direct.update(ScheduleManagerID=100, KCIndex='|1||2|')
                    extra = copy.deepcopy(direct)
                    extra.update(ID=9001, DetailID=8001, CurriculumScheduleIDs='|51||52||53|',
                                 PKCIndex='|1||2||3|', KCIndex='|1||2||3|', Teacher='其他排课教师')
                    record['response'].append(extra)
            mixed_path = root / 'mixed-runtime-capture.json'
            mixed_path.write_text(json.dumps(mixed), encoding='utf-8')
            mixed_service = DesktopService(root / 'mixed-runtime')
            mixed_service.initialize()
            mixed_result = mixed_service.run(capture=mixed_path)
            assert mixed_result['issue'] is None and mixed_result['apple_issue'] is None
            assert mixed_result['report']['event_count'] == mixed_result['apple_report']['event_count'] == 1
            mixed_csv = list(csv.reader(io.StringIO((mixed_service.root / 'output/wakeup.csv').read_text(encoding='utf-8-sig'))))
            assert mixed_csv[1][2:5] == ['1', '2', '示例教师']
            assert load_current(mixed_service.root)['events'][0]['teacher'] == '示例教师'
            mixed_ics = icalendar.Calendar.from_ical((mixed_service.root / 'output/calendar.ics').read_bytes()).walk('VEVENT')
            assert len(mixed_ics) == 1 and '其他排课教师' not in str(mixed_ics[0]['DESCRIPTION'])
            report['mixed_details_exports'] = True
            # Keep a merged/split fixture in the frozen runtime acceptance too.
            # A second explicit data directory cannot switch the first account.
            shared = copy.deepcopy(detail)
            shared.update(ScheduleManagerID=200, HeBanID=400, ClassCode='DEMO-A DEMO-B',
                          CurriculumScheduleIDs='|51||52|', KCIndex='|1|', Teacher='第一节教师')
            shared_second = copy.deepcopy(shared)
            shared_second.update(DetailID=1002, KCIndex='|2|', Teacher='第二节教师')
            first_row = dict(row, ID=11, MCSID='11', CourseCount=1, End='2026-09-07T08:40:00')
            second_row = dict(row, ID=12, MCSID='12', CourseCount=1, Start='2026-09-07T08:50:00')
            merged = json.loads(capture.read_text(encoding='utf-8'))
            merged['responses'] = copy.deepcopy(responses[:len(list(month_ranges(config['start'], config['end_exclusive'])))])
            for record in merged['responses']:
                if record['response']['List']:
                    record['response']['List'] = [first_row, second_row]
            for main_row in (first_row, second_row):
                merged['responses'].append({'path': '/Home/GetCalendarTable',
                    'params': {k: str(main_row.get(k) or '') for k in ('MCSID', 'CSID', 'CurriculumID', 'XXKMID', 'CurriculumType')},
                    'response': [shared, shared_second]})
            merged_path = root / 'merged-runtime-capture.json'
            merged_path.write_text(json.dumps(merged), encoding='utf-8')
            merged_service = DesktopService(root / 'merged-runtime')
            merged_service.initialize()
            merged_result = merged_service.run(capture=merged_path)
            assert merged_result['issue'] is None and merged_result['apple_issue'] is None
            assert merged_result['report']['event_count'] == merged_result['apple_report']['event_count'] == 2
            merged_csv = list(csv.reader(io.StringIO((merged_service.root / 'output/wakeup.csv').read_text(encoding='utf-8-sig'))))
            assert [r[2:5] for r in merged_csv[1:]] == [['1', '1', '第一节教师'], ['2', '2', '第二节教师']]
            assert len({e['uid'] for e in load_current(merged_service.root)['events']}) == 2
            report['combined_split_exports'] = True
            import zipfile
            support = root / 'support-smoke.zip'
            service.diagnostics.export(support, operation_id=committed_operation)
            with zipfile.ZipFile(support) as archive:
                assert archive.testzip() is None
                assert json.loads(archive.read('manifest.json'))['format'] == 'shsmu-support-v1'
                assert json.loads(archive.read('repro.json'))['format'] == 'shsmu-support-v1'
                assert 'commit_finished' in archive.read('events.jsonl').decode('utf-8')
                shared_bytes = b'\n'.join(archive.read(name) for name in archive.namelist())
                assert all(value.encode('utf-8') not in shared_bytes
                           for value in ('运行验证课程', '示例教师', '示例教室', str(root)))
            report['diagnostic_package'] = True
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
            ui.show_diagnostics()
            window.update_idletasks()
            ui.dispose()
            window, ui = None, None
            report.update(status='PASS', checks=['bundled resources', 'first-run and interrupted onboarding startup',
                'existing JSON recovery offered on reopened setup',
                'completed capture opens update home', 'local import and WakeUp CSV',
                'Apple ICS dates and content', 'repeat import preserves UID and ICS', 'bundled onboarding image',
                'Tk result, settings and both iPhone guides', 'independent synthetic phone confirmation',
                'redacted support ZIP and diagnostic dialog'],
                data_outside_bundle=not str(root).startswith(str(getattr(sys, '_MEIPASS', '__not_frozen__'))),
                gui_os='Windows' if os.name == 'nt' else os.name)
            if getattr(sys, 'frozen', False):
                bundle = Path(sys._MEIPASS).resolve()
                report['dependency_paths_in_bundle'] = all(Path(m.__file__).resolve().is_relative_to(bundle)
                                                          for m in (icalendar, tzdata, tk))
    except Exception as error:
        report['error_type'] = type(error).__name__
        import traceback
        report['error_frames'] = [{'file': Path(frame.filename).name, 'function': frame.name, 'line': frame.lineno}
                                  for frame in traceback.extract_tb(error.__traceback__)]
    finally:
        if ui is not None:
            ui.dispose()
        elif window is not None:
            window.destroy()
        atomic_write(Path(report_path).resolve(), json_bytes(report))
    if report['status'] != 'PASS':
        raise SystemExit(1)
