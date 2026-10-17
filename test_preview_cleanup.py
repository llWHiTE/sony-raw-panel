from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

import panel_core as core
from preview_cleanup import records, remove_files


class PreviewCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.c=core.Controller(session=self.root/'session.json')
        self.paths=patch.object(core,'ROOT',self.root)
        self.paths.start()
        for target,name,value in ((core.bridge.w.k,'CreateMutexW',1),(core.bridge.w.k,'CloseHandle',1),(core.C,'get_last_error',0)):
            mocked=patch.object(target,name,return_value=value)
            mocked.start();self.addCleanup(mocked.stop)

    def tearDown(self):
        self.paths.stop()
        self.temp.cleanup()

    def manifest(self,**extras):
        ident='a'*32
        folder=self.root/'comparisons'/ident
        folder.mkdir(parents=True)
        state=dict(version=1,id=ident,project='b'*32,revision='c'*32,view=dict(document=7,previewID=ident),**extras)
        (folder/'comparison.json').write_text(json.dumps(state))
        (folder/'sony.tif').write_bytes(b'tiff')
        (folder/'keep.ARW').write_bytes(b'original')
        return folder,state

    def test_remove_only_allowlisted_service_files(self):
        folder,state=self.manifest(closed=True)
        result=remove_files(folder,state['id'])
        self.assertEqual(result['bytes_freed'],4)
        self.assertTrue((folder/'keep.ARW').exists())
        self.assertTrue((folder/'comparison.json').exists())

    def test_frozen_adobe_base_removed_but_user_sidecars_retained(self):
        folder,state=self.manifest(closed=True)
        (folder/'adobe-base.xmp').write_bytes(b'frozen')
        (folder/'personal.xmp').write_bytes(b'user settings')
        result=remove_files(folder,state['id'])
        self.assertEqual(result['bytes_freed'],10)
        self.assertFalse((folder/'adobe-base.xmp').exists())
        self.assertEqual((folder/'personal.xmp').read_bytes(),b'user settings')

    def test_unrecognized_manifest_is_ignored(self):
        folder,state=self.manifest()
        state['id']='d'*32
        (folder/'comparison.json').write_text(json.dumps(state))
        self.assertEqual(list(records(self.root)),[])

    def test_unmodified_preview_is_closed_then_files_removed_and_purge_requested(self):
        folder,state=self.manifest()
        calls=[]
        def compare(action,data,start=True):
            calls.append(action)
            if action=='close':self.assertTrue((folder/'sony.tif').exists())
            return {'ok':True,'purged':action=='purge'}
        with patch.object(core,'operation',return_value=dict(bytes_freed=0,skipped=0)),patch.object(self.c,'compare_call',side_effect=compare),patch('preview_cleanup.release_sony',return_value=dict(closed=1,retained=0,warnings=[])):
            result=self.c.cleanup(purge_all=True)
        self.assertEqual(calls,['close','purge'])
        self.assertTrue(result['photoshop_purged'])
        self.assertEqual(result['sony_closed'],1)
        self.assertFalse((folder/'sony.tif').exists())
        self.assertTrue((folder/'keep.ARW').exists())

    def test_modified_preview_files_and_sony_tab_are_retained(self):
        folder,state=self.manifest()
        with patch.object(core,'operation',return_value=dict(bytes_freed=0,skipped=0)),patch.object(self.c,'compare_call',side_effect=RuntimeError('modified')),patch('preview_cleanup.release_sony',return_value=dict(closed=0,retained=0,warnings=[])) as sony:
            result=self.c.cleanup()
        self.assertTrue((folder/'sony.tif').exists())
        self.assertEqual(result['previews_retained'],1)
        self.assertEqual(sony.call_args.args[1],{})

    def test_active_working_project_is_not_unloaded(self):
        folder,state=self.manifest(selected_engine='sony')
        with patch.object(core,'operation',return_value=dict(bytes_freed=0,skipped=0)),patch.object(self.c,'compare_call') as ps,patch('preview_cleanup.release_sony',return_value=dict(closed=0,retained=0,warnings=[])) as sony:
            self.c.cleanup()
        self.assertTrue((folder/'sony.tif').exists())
        ps.assert_not_called()
        self.assertEqual(sony.call_args.args[1],{})

    def test_pending_import_blocks_full_purge_before_any_cleanup(self):
        self.c.recovery={'kind':'open'}
        with patch.object(core,'operation') as operation,patch.object(self.c,'compare_call') as ps:
            with self.assertRaises(RuntimeError):self.c.cleanup(purge_all=True)
        operation.assert_not_called()
        ps.assert_not_called()

    def test_unknown_comparison_without_document_confirmation_keeps_files(self):
        folder,state=self.manifest()
        state.pop('view')
        (folder/'comparison.json').write_text(json.dumps(state))
        with patch.object(core,'operation',return_value=dict(bytes_freed=0,skipped=0)),patch('preview_cleanup.release_sony',return_value=dict(closed=0,retained=0,warnings=[])):
            result=self.c.cleanup()
        self.assertTrue((folder/'sony.tif').exists())
        self.assertEqual(result['previews_retained'],1)


if __name__=='__main__':
    unittest.main()
