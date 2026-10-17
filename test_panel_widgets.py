import json
from pathlib import Path
import tempfile
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

import sony_panel as ui


class PanelWidgetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.folder=Path(self.temp.name)
        self.paths=patch.object(ui,'ROOT',self.folder)
        self.paths.start()
        self.root=tk.Tk()
        self.panel=ui.Panel(self.root,warmup=False,session=self.folder/'session.json')
        scans=patch.object(self.panel,'scan')
        scans.start();self.addCleanup(scans.stop)
        for task in self.root.tk.call('after','info'):self.root.after_cancel(task)
        self.root.update_idletasks()

    def tearDown(self):
        self.panel.controller.pending=None
        self.panel.controller.recovery=None
        self.panel.controller.comparison=None
        self.panel.close()
        self.paths.stop()
        self.temp.cleanup()

    def pump(self):
        deadline=time.monotonic()+3
        while self.panel.busy and time.monotonic()<deadline:
            self.panel.drain()
            self.root.update()
            time.sleep(.01)
        self.panel.drain()
        self.assertFalse(self.panel.busy)

    def catalog(self, model='ILCE-7RM3'):
        return dict(source=str(self.folder/'photo.ARW'), model=model, seconds=.002, cached=True, sony_origin='Sony cache',
                    adobe=[dict(id='camera_standard',label='Camera Standard'),dict(id='adobe_color',label='Adobe Color')],
                    sony=[dict(id='camera_standard',label='Standard'),dict(id='sony:8',label='Portrait')])

    def test_profile_defaults_are_standard_and_choices_are_camera_specific(self):
        self.assertEqual(self.panel.adobe_profile.get(),'Camera Standard')
        self.assertEqual(self.panel.sony_profile.get(),'Camera Standard')
        self.panel.set_catalog(self.catalog())
        self.assertEqual(self.panel.adobe_profile.get(),'Camera Standard')
        self.assertEqual(self.panel.sony_profile.get(),'Standard')
        self.panel.sony_profile.set('Portrait');self.panel.profile_changed()
        self.panel.set_catalog(self.catalog('ILCE-OTHER'))
        self.assertEqual(self.panel.sony_profile.get(),'Standard')
        self.panel.set_catalog(self.catalog())
        self.assertEqual(self.panel.sony_profile.get(),'Portrait')
        self.assertEqual(self.panel.selected_profiles()['sony_profile'],'sony:8')

    def test_added_raw_only_reads_catalog_and_prefetches_without_render(self):
        controller=self.panel.controller
        catalog=self.catalog();catalog['prefetch_engine']='sony'
        with patch.object(controller,'profile_catalog',return_value=catalog),patch.object(controller,'prefetch',return_value={}) as prefetch,patch.object(controller,'open',side_effect=AssertionError('must not open')),patch.object(controller,'compare',side_effect=AssertionError('must not render')):
            self.panel.stage_source(catalog['source']);self.pump()
            deadline=time.monotonic()+3
            while self.panel.prefetching and time.monotonic()<deadline:
                self.panel.drain();self.root.update();time.sleep(.01)
            prefetch.assert_called_once()
            self.assertFalse(self.panel.prefetching)
            self.assertEqual(self.panel.source_catalog['model'],'ILCE-7RM3')

    def test_prefetch_completion_does_not_finish_queued_open(self):
        self.panel.prefetching=True;self.panel.busy=True
        self.panel.events.put(('done',('prefetch',{},.3)))
        self.panel.drain()
        self.assertFalse(self.panel.prefetching)
        self.assertTrue(self.panel.busy)
        self.panel.busy=False

    def test_custom_percent_dialog_saves_value(self):
        self.panel.preview_size.set(ui.preview.CUSTOM)
        self.panel.select_quality()
        window=next(w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel))
        children=window.winfo_children()[0].winfo_children()
        entry=next(w for w in children if isinstance(w,ttk.Spinbox))
        entry.delete(0,'end');entry.insert(0,'37')
        next(w for w in children if isinstance(w,ttk.Button) and w.cget('text')=='Сохранить и использовать').invoke()
        prefs=json.loads((self.folder/'ui-preferences.json').read_text(encoding='utf-8'))
        self.assertEqual(ui.preview.preferences(prefs),(37,37,'custom'))
        self.panel.preview_size.set(ui.preview.PRESETS[75]);self.panel.select_quality()
        prefs=json.loads((self.folder/'ui-preferences.json').read_text(encoding='utf-8'))
        self.assertEqual(prefs['preview_percent'],75)
        self.assertEqual(prefs['custom_percent'],37)

    def test_lut_choice_is_enabled_in_ready_comparison(self):
        self.panel.controller.comparison=dict(percent=50,shown='sony',view={'width':3000,'height':2000})
        self.panel.buttons()
        self.assertEqual(str(self.panel.lut_choice.cget('state')),'readonly')
        self.panel.busy=True;self.panel.buttons()
        self.assertEqual(str(self.panel.lut_choice.cget('state')),'disabled')
        self.panel.busy=False

    def test_live_lut_snapshot_runs_in_worker_and_error_restores_selection(self):
        import threading
        c=self.panel.controller
        c.comparison=dict(percent=50,shown='adobe',view={'width':3000,'height':2000},lut=dict(name='LEICA NAT',kind='cube'))
        self.panel.lut_text.set('LEICA BW HC.cube')
        main=threading.get_ident();threads=[]
        def snapshot(path):
            threads.append(threading.get_ident());return dict(name='LEICA BW HC',kind='cube')
        with patch.object(self.panel.lut_library,'snapshot',side_effect=snapshot),patch.object(c,'set_comparison_lut',side_effect=RuntimeError('modified')):
            self.panel.change_comparison_lut();self.pump()
        self.assertTrue(threads)
        self.assertNotEqual(threads[0],main)
        self.assertEqual(self.panel.lut_text.get(),'LEICA NAT.cube')
        self.assertIn('Смена LUT',self.panel.duration_text.get())
        self.assertEqual(c.comparison['shown'],'adobe')

    def test_single_compare_button_toggles_both_directions(self):
        c=self.panel.controller
        c.comparison=dict(percent=50,shown='sony',view={'width':3000,'height':2000})
        def show(engine):
            c.comparison['shown']=engine
            return {'ok':True}
        with patch.object(c,'show_comparison',side_effect=show) as toggle:
            self.panel.buttons()
            self.panel.compare_button.invoke();self.pump()
            self.assertEqual(c.comparison['shown'],'adobe')
            self.assertIn('показать Sony',self.panel.compare_button.cget('text'))
            self.panel.compare_button.invoke();self.pump()
            self.assertEqual(c.comparison['shown'],'sony')
            self.assertEqual([call.args[0] for call in toggle.call_args_list],['adobe','sony'])

    def test_use_current_chooses_the_shown_engine(self):
        c=self.panel.controller
        c.comparison=dict(percent=50,shown='adobe',view={'width':3000,'height':2000})
        self.panel.buttons()
        with patch.object(self.panel,'choose_engine') as choose:
            self.panel.use_current.invoke()
        choose.assert_called_once_with('adobe')

    def test_error_shows_cancel_and_cancel_needs_no_photoshop(self):
        c=self.panel.controller
        render=self.folder/'ready.tif';render.write_bytes(b'ready')
        c.recovery=dict(kind='open',render={'render':str(render)})
        self.panel.busy=True
        self.panel.events.put(('error',('apply','RPC unavailable',2.4)))
        self.panel.drain()
        self.assertTrue(self.panel.cancel_button.winfo_manager())
        self.assertEqual(str(self.panel.cancel_button.cget('state')),'normal')
        with patch.object(ui.messagebox,'askyesno',return_value=True),patch.object(c.ps,'call',side_effect=AssertionError('Offline cancellation')):
            self.panel.cancel_button.invoke();self.pump()
        self.assertIsNone(c.recovery)
        self.assertTrue(render.exists())
        self.assertEqual(str(self.panel.open_button.cget('state')),'normal')
        self.assertTrue(list((self.folder/'cancelled-operations').glob('*.json')))

    def test_duration_survives_clock_and_background_scan(self):
        self.panel.busy=True
        self.panel.events.put(('done',('open',{'engine':'adobe'},4.25)))
        self.panel.drain()
        value=self.panel.duration_text.get()
        self.assertIn('4.2',value)
        self.panel.clock()
        self.panel.scanned({'running':False,'targets':[]})
        self.assertEqual(self.panel.duration_text.get(),value)

    def test_retry_duration_is_labeled_as_a_separate_attempt(self):
        c=self.panel.controller
        c.pending={'kind':'initial','prepare_seconds':9}
        c.recovery={'kind':'open'}
        target=dict(project='a'*32,revision='b'*32,document=7,layer=2)
        result=dict(target=target,cleaned=True,seconds=.1)
        with patch.object(c,'retry_import',return_value=result),patch.object(c,'status',return_value={'running':True,'targets':[]}):
            self.panel.apply()
            self.pump()
        self.assertIn('Повторный импорт',self.panel.duration_text.get())
        self.assertNotIn('первая проявка',self.panel.duration_text.get())

    def test_cleanup_warning_can_be_disabled_only_on_confirmation(self):
        self.panel.cleanup_button.invoke()
        window=next(w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel))
        widgets=window.winfo_children()[0].winfo_children()
        next(w for w in widgets if isinstance(w,ttk.Checkbutton)).invoke()
        result=dict(bytes_freed=0,previews_closed=0,sony_closed=0,photoshop_purged=True,warnings=[])
        with patch.object(self.panel.controller,'cleanup',return_value=result) as cleanup:
            next(w for w in widgets if isinstance(w,ttk.Button) and w.cget('text')=='Очистить кэш').invoke()
            self.pump()
        cleanup.assert_called_once_with(purge_all=True)
        self.assertFalse(self.panel.cleanup_warning.get())
        prefs=json.loads((self.folder/'ui-preferences.json').read_text(encoding='utf-8'))
        self.assertFalse(prefs['cleanup_warning'])
        with patch.object(self.panel.controller,'cleanup',return_value=result) as cleanup:
            self.panel.cleanup_button.invoke();self.pump()
        cleanup.assert_called_once_with(purge_all=True)
        self.assertFalse(any(isinstance(w,tk.Toplevel) for w in self.root.winfo_children()))

    def test_cancelled_cleanup_warning_does_not_purge(self):
        self.panel.cleanup_button.invoke()
        window=next(w for w in self.root.winfo_children() if isinstance(w,tk.Toplevel))
        widgets=window.winfo_children()[0].winfo_children()
        next(w for w in widgets if isinstance(w,ttk.Checkbutton)).invoke()
        with patch.object(self.panel.controller,'cleanup') as cleanup:
            next(w for w in widgets if isinstance(w,ttk.Button) and w.cget('text')=='Отмена').invoke()
        cleanup.assert_not_called()
        self.assertTrue(self.panel.cleanup_warning.get())

    def test_comparison_frame_collapses_without_changing_window_size(self):
        before=self.root.geometry()
        c=self.panel.controller
        c.comparison=dict(percent=50,shown='sony',view={'width':3000,'height':2000})
        self.panel.buttons();self.root.update_idletasks()
        self.assertTrue(self.panel.compare_frame.winfo_manager())
        c.comparison=None
        self.panel.buttons();self.root.update_idletasks()
        self.assertFalse(self.panel.compare_frame.winfo_manager())
        self.assertEqual(self.root.geometry(),before)


if __name__=='__main__':
    unittest.main()
