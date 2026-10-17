import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('workflow_core',ROOT/'panel_core.py')
core=importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


class FakePS:
    def __init__(self):self.calls=[]
    def call(self,action,data=None,start=False):
        self.calls.append((action,data))
        if action=='open':return {'target':{'project':data['project'],'revision':data['token'],'document':7,'layer':2}}
        return {'ok':True}
    def foreground(self):pass


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.c=core.Controller(session=Path(self.temp.name)/'session.json')
        self.c.ps=FakePS()
        self.target=dict(document=7,layer=2,project='a'*32,revision='b'*32)
    def tearDown(self):self.temp.cleanup()

    def test_prefetch_does_not_call_sony_or_photoshop_and_is_reused(self):
        source=Path(self.temp.name)/'source.ARW';source.write_bytes(b'raw')
        with patch.object(core.bridge,'new_project',return_value=(Path(self.temp.name),{'id':'c'*32})) as create,patch.object(core,'operation',side_effect=AssertionError('No renderer')):
            first=self.c.prefetch(source)
            self.assertEqual(self.c.prefetch(source),first)
            create.assert_called_once()
            self.assertEqual(self.c._prepared_project(source),'c'*32)
            source.write_bytes(b'changed')
            self.assertIsNone(self.c._prepared_project(source))
        self.assertEqual(self.c.ps.calls,[])

    def test_explicit_edit_profile_is_not_reset_on_apply(self):
        with patch.object(core,'operation',return_value={}) as operation:
            self.c.edit(self.target,sony_profile='sony:8')
            self.assertEqual(operation.call_args.args[0]['sony_profile'],'sony:8')
        with patch.object(core,'operation',return_value={'unchanged':True}) as operation:
            self.c.apply()
            self.assertNotIn('sony_profile',operation.call_args.args[0])

    def test_default_profile_is_sent_to_initial_sony_operation(self):
        with patch.object(core,'operation',return_value=dict(project='a'*32,kind='initial',source='source.ARW')) as operation:
            self.c.open(Path('source.ARW'),first_sony=True)
            self.assertEqual(operation.call_args.args[0]['sony_profile'],'camera_standard')

    def test_first_setup_opens_sony_without_render_or_photoshop(self):
        prepared=dict(project='a'*32,revision='b'*32,kind='initial',source='source.ARW')
        with patch.object(core,'operation',return_value=prepared) as operation:
            result=self.c.open(Path('source.ARW'),first_sony=True)
        self.assertTrue(result['prepared'])
        self.assertEqual(operation.call_args.args[0]['action'],'prepare')
        self.assertEqual(self.c.ps.calls,[])
        self.assertEqual(self.c.pending,prepared)

    def test_initial_apply_imports_new_document_not_replace(self):
        self.c.pending=dict(project='a'*32,revision='b'*32,kind='initial',source='source.ARW')
        render=dict(project='a'*32,token='c'*32,render='render.tif')
        calls=[]
        def operation(request):
            calls.append(request)
            return {'cleaned':True} if request['action']=='ack' else render
        with patch.object(core,'operation',side_effect=operation):result=self.c.apply()
        self.assertEqual([a for a,_ in self.c.ps.calls],['open'])
        self.assertFalse(calls[0]['skip_unchanged'])
        self.assertEqual(result['target']['revision'],'c'*32)
        self.assertIsNone(self.c.pending)

    def test_unchanged_recipe_does_not_import_or_ack(self):
        self.c.pending=dict(self.target)
        with patch.object(core,'operation',return_value={'unchanged':True}) as operation:
            result=self.c.apply()
        self.assertTrue(result['unchanged'])
        self.assertTrue(operation.call_args.args[0]['skip_unchanged'])
        self.assertEqual([a for a,_ in self.c.ps.calls],['validate'])
        self.assertEqual(result['target'],self.target)
        self.assertIsNone(self.c.pending)

    def test_adobe_dispatch_does_not_start_sony(self):
        with patch.object(self.c,'open_adobe',return_value={'engine':'adobe'}) as adobe,patch.object(core,'operation') as sony:
            result=self.c.open(Path('source.ARW'),engine='adobe',first_sony=True)
        adobe.assert_called_once()
        sony.assert_not_called()
        self.assertEqual(result['engine'],'adobe')

    def test_cancel_after_failed_import_preserves_render_without_photoshop(self):
        import json
        raw = Path(self.temp.name)/'working.ARW'
        raw.write_bytes(b'raw')
        render = Path(self.temp.name)/'ready.tif'
        render.write_bytes(b'render')
        self.c.pending = dict(self.target)
        self.c.recovery = dict(kind='replace', target=self.target, render={'render':str(render)})
        self.c.save_session()
        with patch.object(core,'operation',side_effect=AssertionError('Sony must not be called')):
            result = self.c.cancel()
        self.assertTrue(result['cancelled'])
        self.assertEqual(self.c.ps.calls,[])
        self.assertEqual(raw.read_bytes(),b'raw')
        self.assertEqual(render.read_bytes(),b'render')
        self.assertIsNone(self.c.pending)
        self.assertIsNone(self.c.recovery)
        archive=json.loads(Path(result['archive']).read_text())
        self.assertEqual(archive['recovery']['render']['render'],str(render))
        restored=core.Controller(session=self.c.session)
        self.assertIsNone(restored.pending)
        self.assertIsNone(restored.recovery)

    def test_cancel_keeps_comparison_document_and_backing_files(self):
        self.c.comparison={'id':'a'*32,'view':{'document':99}}
        with patch.object(self.c,'compare_call',side_effect=AssertionError('Do not close documents')):
            self.assertTrue(self.c.cancel()['cancelled'])
        self.assertIsNone(self.c.comparison)

    def test_cancel_save_failure_keeps_recovery_available(self):
        self.c.pending=dict(self.target)
        with patch.object(self.c,'save_session',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.c.cancel()
        self.assertEqual(self.c.pending,self.target)

    def test_shown_engine_changes_only_after_success(self):
        self.c.comparison={'view':{'document':1,'historyCount':2},'shown':'sony'}
        with patch.object(self.c,'compare_call',side_effect=RuntimeError('disconnected')):
            with self.assertRaises(RuntimeError):self.c.show_comparison('adobe')
        self.assertEqual(self.c.comparison['shown'],'sony')
        with patch.object(self.c,'compare_call',side_effect=[{'modified':False},{'historyCount':3}]):
            self.c.show_comparison('adobe')
        self.assertEqual(self.c.comparison['shown'],'adobe')

    def test_initial_session_restores_after_restart(self):
        self.c.pending=dict(project='a'*32,revision='b'*32,kind='initial',source='source.ARW')
        self.c.save_session()
        loaded=core.Controller(session=self.c.session)
        self.assertEqual(loaded.pending,self.c.pending)


if __name__=='__main__':unittest.main()
