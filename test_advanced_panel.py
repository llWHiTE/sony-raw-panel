from pathlib import Path
import unittest
from unittest.mock import patch

import test_panel_widgets as widgets
import windows_integration as win


class AdvancedPanelTests(unittest.TestCase):
    setUp=widgets.PanelWidgetTests.setUp
    tearDown=widgets.PanelWidgetTests.tearDown
    pump=widgets.PanelWidgetTests.pump

    def test_quiet_scrollbar_and_adobe_buttons_have_no_bright_bevel(self):
        style=widgets.ttk.Style()
        self.assertEqual(str(self.panel.scrollbar.cget('style')),'Quiet.Vertical.TScrollbar')
        self.assertEqual(str(style.lookup('Quiet.Vertical.TScrollbar','width')),'8')
        self.assertNotIn('uparrow',str(style.layout('Quiet.Vertical.TScrollbar')))
        self.assertNotIn('downarrow',str(style.layout('Quiet.Vertical.TScrollbar')))
        self.assertEqual(style.lookup('Sony.TButton','lightcolor'),'#363636')
        self.assertEqual(style.lookup('Sony.TButton','bordercolor'),'#505050')
        self.assertEqual(style.lookup('Sony.TButton','bordercolor',('focus',)),'#83baff')

    def test_compact_roundtrip_preserves_visual_order_and_size(self):
        p=self.panel
        before=p.content_frame.pack_slaves();geometry=self.root.geometry()
        p.compact.set(True);p.layout_compact();self.root.update_idletasks()
        self.assertFalse(p.adobe_profile_choice.master.winfo_manager())
        self.assertTrue(p.open_button.winfo_manager())
        p.compact.set(False);p.layout_compact();self.root.update_idletasks()
        self.assertEqual(p.content_frame.pack_slaves(),before)
        self.assertEqual(self.root.geometry(),geometry)

    def test_context_visibility_and_manual_hide_are_distinct(self):
        p=self.panel;p.context_only.set(True)
        with patch.object(p.foreground,'kind',return_value='other'):p.advanced_tick()
        self.assertEqual(self.root.state(),'withdrawn')
        with patch.object(p.foreground,'kind',return_value='photoshop'):p.advanced_tick()
        self.assertEqual(self.root.state(),'normal')
        p.global_action('toggle')
        self.assertTrue(p.manual_hidden)
        with patch.object(p.foreground,'kind',return_value='photoshop'):p.advanced_tick()
        self.assertEqual(self.root.state(),'withdrawn')
        p.global_action('toggle');self.assertEqual(self.root.state(),'normal')

    def test_busy_file_receipt_queues_without_replacing_current_work(self):
        p=self.panel;raw=self.folder/'photo.ARW';raw.write_bytes(b'raw')
        p.busy=True
        with patch.object(p,'stage_source') as stage:
            p.receive_files([raw]);stage.assert_not_called()
        self.assertEqual(len(p.raw_queue.items),1)
        p.busy=False

    def test_queue_navigation_is_blocked_by_pending_edit(self):
        p=self.panel;files=[self.folder/name for name in ('a.ARW','b.ARW')]
        for f in files:f.write_bytes(b'raw')
        p.raw_queue.add(files);old=p.raw_queue.current
        p.controller.pending={'project':'a'*32}
        with patch.object(p,'stage_source') as stage:
            p.queue_step(1);stage.assert_not_called()
        self.assertEqual(p.raw_queue.current,old)

    def test_global_apply_only_with_known_pending_and_matching_foreground(self):
        p=self.panel;p.controller.pending={'project':'a'*32}
        with patch.object(p,'apply') as apply:
            with patch.object(p.foreground,'kind',return_value='other'):p.global_action('apply')
            apply.assert_not_called()
            with patch.object(p.foreground,'kind',return_value='sony'):p.global_action('apply')
            apply.assert_called_once()

    def test_global_edit_refreshes_target_instead_of_using_stale_selection(self):
        p=self.panel;p.selected={'project':'old','layer':1}
        target={'project':'new','layer':22}
        with patch.object(p.foreground,'kind',return_value='photoshop'),patch.object(p.controller,'status',return_value={'targets':[target],'selectedLayer':22}),patch.object(p.controller,'edit',return_value={}) as edit:
            p.global_action('edit');self.pump()
            edit.assert_called_once_with(target)

    def test_profiles_readonly_in_ready_comparison(self):
        p=self.panel;p.set_catalog(widgets.PanelWidgetTests.catalog(self))
        p.controller.comparison=dict(percent=50,shown='sony',view={'width':3000,'height':2000})
        p.buttons()
        self.assertEqual(str(p.adobe_profile_choice.cget('state')),'readonly')
        self.assertEqual(str(p.sony_profile_choice.cget('state')),'readonly')

    def test_disabled_cache_does_not_render_unusable_next_preview(self):
        p=self.panel;files=[self.folder/name for name in ('a.ARW','b.ARW')]
        for f in files:f.write_bytes(b'raw')
        rows=p.raw_queue.add(files);rows[1]['status']='copy_ready'
        p.next_preview.set(True);p.cache_limit=0
        with patch.object(p.jobs,'put') as put:
            p.schedule_background();put.assert_not_called()
        self.assertFalse(p.background_jobs)

    def test_background_completion_updates_its_own_item_not_new_next(self):
        p=self.panel;files=[self.folder/name for name in ('a.ARW','b.ARW','c.ARW')]
        for f in files:f.write_bytes(b'raw')
        rows=p.raw_queue.add(files);p.raw_queue.move(rows[2]['id'],-1)
        p.advanced_event('done',('background_next',{'item_id':rows[1]['id'],'project':'d'*32},.2))
        self.assertEqual(rows[1]['status'],'copy_ready')
        self.assertEqual(rows[2]['status'],'waiting')


if __name__=='__main__':unittest.main()
