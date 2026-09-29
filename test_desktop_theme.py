"""Real ttk layout and action contracts using only isolated synthetic schedules."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import tkinter as tk
from tkinter import ttk
from desktop import AssistantWindow
from desktop_theme import Metrics, walk_widgets
from test_desktop import write_capture, LATER, item


class MedicalThemeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='medical-ui ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.window = tk.Tk()
        self.window.withdraw()
        original_scale = float(self.window.tk.call('tk','scaling'))
        # Deterministic logical layout; native DPI is checked by the real-window run.
        self.window.tk.call('tk','scaling',96/72)
        with patch('desktop.default_data_root',return_value=self.root/'preferences'):
            self.ui = AssistantWindow(self.window,self.root/'data')
        self.addCleanup(self.ui.dispose)
        self.addCleanup(lambda: None if self.ui.disposed else self.window.tk.call('tk','scaling',original_scale))

    def saved(self):
        self.ui.service.confirm_term()
        self.ui.service.acknowledge_bookmark()
        return self.ui.service.run(capture=write_capture(self.ui.service.root,config=self.ui.service.config()))

    def button(self,text,parent=None):
        return next(w for w in walk_widgets(parent or self.ui.content)
                    if isinstance(w,ttk.Button) and str(w.cget('text'))==text)

    def checks(self):
        return [w for w in walk_widgets(self.ui.content) if isinstance(w,ttk.Checkbutton)]

    def test_theme_is_fingerprinted_and_uses_one_pixel_conversion(self):
        from build_desktop import BUILD_INPUTS, source_fingerprint
        self.assertIn('desktop_theme.py',BUILD_INPUTS)
        self.assertIn('desktop_theme.py',source_fingerprint()[0])
        self.assertEqual(Metrics(2).px(27),54)
        self.assertEqual(self.ui.theme.font(27)[1],-self.ui.px(27))
        self.assertEqual(str(ttk.Style(self.window).lookup('Title.TLabel','foreground')),'#192d27')

    def test_bordered_images_keep_minimum_size_with_large_tiled_centre(self):
        from desktop_theme import TILE_CENTER
        # ttk tiles the centre; a tiny centre stalled every repaint on Windows.
        photo = self.ui.theme.tile('#ffffff')
        self.assertGreaterEqual(photo.width() - 2*self.ui.px(11), TILE_CENTER)
        button = ttk.Button(self.ui.content, text='合成')
        self.addCleanup(button.destroy)
        self.assertLess(button.winfo_reqheight(), self.ui.px(80))
        nav = self.ui.nav_buttons[0]
        self.assertLess(nav.winfo_reqheight(), self.ui.px(80))

    def test_slim_scrollbar_is_a_light_frame_and_tracks_the_view(self):
        from desktop_theme import SlimScrollbar
        self.window.deiconify()
        self.window.geometry('900x500')
        self.window.update()
        bar = self.ui.scrollbar
        # A ttk scrollbar cost ~10 ms per window-resize step on Windows.
        self.assertIsInstance(bar, SlimScrollbar)
        self.assertLessEqual(bar.winfo_width(), self.ui.px(16))
        bar.set(.5, .75)
        self.window.update()
        top, length = bar.thumb_box()
        height = bar.winfo_height()
        self.assertLess(top, height*.6)
        self.assertGreater(top+length, height*.6)
        self.assertGreater(top, height*.2)
        self.assertLess(top+length, height*.9)
        self.assertEqual(bar.thumb.winfo_y(), top)
        bar.set(0, 1)
        self.window.update()
        self.assertIsNone(bar.thumb_box())
        self.assertFalse(bar.thumb.winfo_ismapped())

    def test_dragging_the_window_edge_keeps_the_column_width_between_breakpoints(self):
        scroller = self.ui.scroller
        widest = scroller.max_width
        for available in (widest, widest+self.ui.px(10), widest+self.ui.px(300)):
            self.assertEqual(scroller.column_width(available), widest)
        narrower = {scroller.column_width(widest-self.ui.px(n)) for n in range(1, 50, 5)}
        self.assertLessEqual(len(narrower), 2)
        self.assertGreaterEqual(min(narrower), scroller.min_width)
        self.saved()
        self.window.deiconify()
        self.window.geometry(f'{self.ui.px(1080)}x{self.ui.px(687)}')
        self.ui.show_home()
        self.window.update()
        labels = [w for w in walk_widgets(self.ui.content) if isinstance(w, tk.Label) and str(w.cget('text'))]
        before = [(w.winfo_width(), str(w.cget('wraplength'))) for w in labels]
        for step in range(1, 6):
            self.window.geometry(f'{self.ui.px(1080)+step*self.ui.px(10)}x{self.ui.px(687)}')
            self.window.update()
        self.assertEqual([(w.winfo_width(), str(w.cget('wraplength'))) for w in labels], before)

    def test_cards_round_their_corners_into_the_surrounding_background(self):
        from desktop_theme import Card, PAGE, SURFACE
        self.saved()
        self.ui.show_home()
        self.window.update_idletasks()
        cards = [w for w in walk_widgets(self.ui.content) if isinstance(w, Card)]
        self.assertGreaterEqual(len(cards), 2)
        for card in cards:
            self.assertEqual(str(card.cget('background')), PAGE)
            self.assertEqual(str(card.body.cget('background')), SURFACE)
            self.assertEqual(len(card.corner_items), 4)

    def test_scrolling_does_not_rebuild_the_scroll_region(self):
        self.saved()
        self.window.deiconify()
        self.window.geometry('1000x420')
        self.ui.show_files()
        self.window.update()
        with patch.object(self.ui, '_wrap_label') as rewrap:
            for _ in range(3):
                self.ui.scroller.yview_scroll(1, 'units')
                self.window.update()
            rewrap.assert_not_called()
        self.assertGreater(self.ui.scroller.offset, 0)

    @unittest.skipUnless(sys.platform == 'darwin', 'Aqua point scale')
    def test_mac_fonts_are_not_shrunk_below_design_size(self):
        self.window.tk.call('tk','scaling',1.0)
        self.ui._style()
        self.assertEqual(self.ui.theme.metrics.scale, 1)
        self.assertEqual(self.ui.theme.font(14)[1], -14)

    def test_platform_sidebar_palette_keeps_light_controls_readable(self):
        from desktop_theme import SIDEBAR
        expected = '#edf2ee' if sys.platform == 'darwin' else '#eef3ef'
        self.assertEqual(SIDEBAR, expected)
        self.assertEqual(str(self.ui.sidebar.cget('background')), expected)
        style = ttk.Style(self.window)
        self.assertEqual(str(style.lookup('Primary.TButton', 'foreground')), '#ffffff')
        self.assertEqual(str(style.lookup('TEntry', 'fieldbackground')), '#ffffff')

    def test_nested_scroll_controls_do_not_scroll_the_main_page(self):
        from types import SimpleNamespace
        for control in (ttk.Treeview(self.ui.content), tk.Listbox(self.ui.content),
                        tk.Text(self.ui.content), ttk.Combobox(self.ui.content)):
            with self.subTest(control=control.winfo_class()), \
                    patch.object(self.ui.scroller, 'yview_scroll') as scroll:
                self.ui._wheel(SimpleNamespace(widget=control, delta=-120))
                scroll.assert_not_called()
            control.destroy()
        with patch.object(self.ui.scroller, 'yview_scroll') as scroll:
            self.ui._wheel(SimpleNamespace(widget=self.ui.content, delta=-120))
            scroll.assert_called_once()

    def test_home_links_to_both_real_format_cards_and_regenerate_is_export_only(self):
        self.saved()
        self.ui.show_home()
        self.assertEqual(self.ui.page,'home')
        with patch.object(self.ui,'start') as start:
            self.ui.show_home()
            self.button('重新生成导入文件').invoke()
            start.assert_called_once_with(export_only=True)
        self.button('查看文件与导入步骤').invoke()
        self.assertEqual(self.ui.page,'results')
        self.assertEqual(set(self.ui.result_contexts),{'wakeup','apple'})
        self.assertEqual(len(self.checks()),2)

    def test_result_cards_keep_independent_display_hashes_and_confirmation(self):
        result=self.saved()
        self.ui.show_result(result)
        contexts=self.ui.result_contexts.copy()
        self.checks()[0].invoke()
        state=self.ui.service.state()
        self.assertEqual(state['phone_confirmed_csv'],contexts['wakeup'][1])
        self.assertNotIn('phone_confirmed_ics',state)
        self.assertTrue(self.checks()[0].instate(['disabled']))
        self.assertEqual(self.ui.result_contexts['apple'],contexts['apple'])
        self.checks()[1].invoke()
        self.assertEqual(self.ui.service.state()['phone_confirmed_ics'],contexts['apple'][1])
        self.assertEqual(self.ui.service.state()['phone_confirmed_csv'],contexts['wakeup'][1])
        self.ui.show_files()
        self.assertTrue(all(bool(w.confirm_value.get()) for w in self.checks()))

    def test_old_result_card_rejects_changed_hash_without_cross_format_confirmation(self):
        result=self.saved()
        self.ui.show_result(result)
        old_check=self.checks()[0]
        changed=item()
        changed['details'][0]['Teacher']='合成变更'
        self.ui.service.run(capture=write_capture(self.ui.service.root,[changed],fetched=LATER,config=self.ui.service.config()))
        old_check.invoke()
        self.assertEqual(self.ui.page,'error')
        self.assertNotIn('phone_confirmed_csv',self.ui.service.state())
        self.assertNotIn('phone_confirmed_ics',self.ui.service.state())

    def test_ready_file_tampering_and_busy_state_reject_card_confirmation(self):
        result=self.saved()
        self.ui.show_result(result)
        self.ui.running=True
        self.checks()[0].invoke()
        self.assertNotIn('phone_confirmed_csv',self.ui.service.state())
        self.ui.running=False
        (self.ui.service.root/'output/calendar.ics').write_bytes(b'synthetic changed file')
        self.checks()[1].invoke()
        self.assertEqual(self.ui.page,'error')
        self.assertNotIn('phone_confirmed_ics',self.ui.service.state())

    def test_result_layout_uses_two_cards_then_stacks_without_losing_controls(self):
        result=self.saved()
        self.window.deiconify()
        for width,columns in ((1080,2),(800,1),(1080,2)):
            with self.subTest(width=width):
                self.window.geometry(f'{self.ui.px(width)}x{self.ui.px(687)}')
                self.ui.show_result(result)
                self.window.update()
                cards=[w.master.master for w in self.checks()]
                self.assertEqual(cards[0].master.columns,columns,
                    (self.window.winfo_width(),self.ui.scroller.viewport.winfo_width(),self.ui.content.winfo_width(),cards[0].master.winfo_width(),self.ui.theme.metrics.scale))
                self.assertGreater(cards[0].winfo_width(),self.ui.px(230))
                self.assertTrue(all(w.winfo_ismapped() for w in self.checks()))
                if columns==2:
                    self.assertEqual(cards[0].winfo_y(),cards[1].winfo_y())
                    self.assertGreater(cards[1].winfo_x(),cards[0].winfo_x())
                else:
                    self.assertGreater(cards[1].winfo_y(),cards[0].winfo_y())
                    target=self.button('查看导入步骤')
                    target.focus_force()
                    self.window.update()
                    viewport=self.ui.scroller.viewport
                    self.assertGreaterEqual(target.winfo_rooty(),viewport.winfo_rooty())
                    self.assertLessEqual(target.winfo_rooty()+target.winfo_height(),
                        viewport.winfo_rooty()+viewport.winfo_height())

    def test_settings_overview_reaches_all_preserved_editors(self):
        self.ui.show_settings()
        self.button('修改').invoke()
        notebook=next(w for w in walk_widgets(self.ui.content) if isinstance(w,ttk.Notebook))
        self.assertEqual(notebook.index('current'),0)
        self.assertEqual(len(notebook.tabs()),3)
        self.ui.show_settings()
        self.button('查看设置').invoke()
        notebook=next(w for w in walk_widgets(self.ui.content) if isinstance(w,ttk.Notebook))
        self.assertEqual(notebook.index('current'),1)
        self.assertEqual(len([w for w in walk_widgets(notebook) if isinstance(w,ttk.Entry)]),33)
        self.assertFalse(self.button('保存设置').instate(['disabled']))

    def test_busy_navigation_duplicate_start_and_after_cleanup(self):
        self.ui.service.save_settings({**self.ui.service.config(),'downloads_dir':str(self.root/'downloads')})
        (self.root/'downloads').mkdir()
        self.ui.start()
        first=self.ui.job.thread
        self.ui.start()
        self.assertIs(self.ui.job.thread,first)
        self.assertTrue(all(b.instate(['disabled']) for b in self.ui.nav_buttons))
        self.ui.job.cancel()
        first.join(5)
        self.assertFalse(first.is_alive())
        self.window.after_cancel(self.ui.poll_id)
        self.ui.poll()
        self.assertFalse(self.ui.running)
        self.assertTrue(all(not b.instate(['disabled']) for b in self.ui.nav_buttons))
        self.ui.defer(lambda: self.fail('callback ran after disposal'))
        self.ui.dispose()
        self.assertEqual(self.ui.ui_after,set())
        self.assertIsNone(self.ui.poll_id)

    def test_details_actions_remain_visible_at_minimum_dialog_height(self):
        self.window.deiconify()
        self.window.update()
        self.ui.details = ['Synthetic detail ' * 30] * 35
        self.ui.show_details()
        dialog = next(w for w in self.window.winfo_children() if isinstance(w, tk.Toplevel))
        self.addCleanup(lambda: dialog.destroy() if dialog.winfo_exists() else None)
        for width, height in ((760, 480), (560, 440)):
            with self.subTest(size=(width, height)):
                dialog.geometry(f'{width}x{height}')
                dialog.update()
                for text in ('关闭', '导出排错日志'):
                    button = self.button(text, dialog)
                    self.assertTrue(button.winfo_ismapped())
                    self.assertGreaterEqual(button.winfo_height(), button.winfo_reqheight())
                    self.assertLessEqual(button.winfo_rooty() - dialog.winfo_rooty() +
                                         button.winfo_height(), dialog.winfo_height())

    def test_diagnostics_footer_and_privacy_fit_at_simulated_scales(self):
        self.window.deiconify()
        self.window.update()
        for factor in (1,1.25,1.5,2):
            with self.subTest(simulated_scale=factor):
                self.window.tk.call('tk','scaling',96/72*factor)
                self.ui._style()
                self.ui.show_diagnostics()
                dialog=next(w for w in self.window.winfo_children() if isinstance(w,tk.Toplevel))
                dialog.update()
                save=self.button('保存日志并定位文件',dialog)
                bottom=save.winfo_rooty()-dialog.winfo_rooty()+save.winfo_height()
                self.assertLessEqual(bottom,dialog.winfo_height())
                privacy=next(w for w in walk_widgets(dialog) if isinstance(w,ttk.Label) and '不要公开上传' in str(w.cget('text')))
                self.assertLess(privacy.winfo_rooty()+privacy.winfo_height(),save.winfo_rooty())
                self.assertTrue(save.winfo_ismapped())
                dialog.destroy()

    def test_enter_and_space_use_real_button_bindings(self):
        self.window.deiconify()
        self.window.update()
        button=self.button('确认学期并继续')
        button.focus_force()
        button.event_generate('<Return>')
        self.window.update()
        self.assertEqual(self.ui.page,'bookmark')
        button=self.button('已添加书签，继续')
        button.focus_force()
        button.event_generate('<KeyPress-space>')
        # ttk invokes on key press, so the page (and button) is already replaced.
        self.window.event_generate('<KeyRelease-space>')
        self.window.update()
        self.assertEqual(self.ui.page,'ready')

    def test_files_without_a_committed_schedule_returns_to_setup(self):
        self.ui.show_files()
        self.assertEqual(self.ui.page,'term')

    def test_total_export_failure_does_not_claim_files_generated(self):
        result=self.saved()
        self.ui.show_result({**result,'report':None,'apple_report':None})
        labels=[str(w.cget('text')) for w in walk_widgets(self.ui.content) if isinstance(w,(tk.Label,ttk.Label))]
        self.assertFalse(any('电脑文件已生成' in text for text in labels))
        self.assertTrue(all(w.instate(['disabled']) for w in self.checks()))


if __name__ == '__main__':
    unittest.main()
