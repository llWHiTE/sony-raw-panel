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

    def test_initial_session_restores_after_restart(self):
        self.c.pending=dict(project='a'*32,revision='b'*32,kind='initial',source='source.ARW')
        self.c.save_session()
        loaded=core.Controller(session=self.c.session)
        self.assertEqual(loaded.pending,self.c.pending)


if __name__=='__main__':unittest.main()
