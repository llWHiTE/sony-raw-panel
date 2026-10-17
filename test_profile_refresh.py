from contextlib import nullcontext
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import panel_core as core
from comparison_adobe import write_sidecar


class ProfileRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        p=patch.object(core,'ROOT',self.root);p.start();self.addCleanup(p.stop)
        self.c=core.Controller(session=self.root/'session.json')
        self.raw=self.root/'AdobeRAW-test.ARW';self.raw.write_bytes(b'private')
        write_sidecar(self.raw)
        self.base=self.root/'adobe-base.xmp';self.base.write_bytes(self.raw.with_suffix('.xmp').read_bytes())
        self.c.comparison=dict(id='a'*32,project='b'*32,revision='c'*32,source=str(self.root/'original.ARW'),
                               adobe=str(self.raw),directory=str(self.root),adobeBase=str(self.base),
                               adobeProfileID='camera_standard',sonyProfile=dict(id='camera_standard',label='Standard'),
                               view=dict(document=7,sonyLayer=2,adobeLayer=3),shown='sony',lut=None)
        self.resolved=dict(id='adobe_standard',label='Adobe Standard',camera_profile='Adobe Standard')

    def test_adobe_only_refresh_does_not_call_sony(self):
        view=dict(self.c.comparison['view'],adobeLayer=8)
        with patch('development_profiles.resolve_adobe',return_value=self.resolved),patch('render_workflow.adobe_request',side_effect=lambda c,s:s),patch.object(self.c,'compare_call',side_effect=[{'ok':True},{'comparison':view}]) as ps,patch.object(core,'operation',side_effect=AssertionError('no Sony')):
            result=self.c.set_comparison_profile('adobe','adobe_standard')
        self.assertEqual([x.args[0] for x in ps.call_args_list],['check','refresh'])
        self.assertEqual(self.c.comparison['view']['sonyLayer'],2)
        self.assertEqual(self.c.comparison['view']['adobeLayer'],8)
        self.assertEqual(self.c.comparison['adobeProfileID'],'adobe_standard')
        self.assertEqual(self.c.comparison['shown'],'sony')
        self.assertIn(b'Adobe Standard',self.base.read_bytes())
        self.assertEqual(result['engine'],'adobe')

    def test_failed_refresh_restores_both_sidecars_and_selection(self):
        sidecar=self.raw.with_suffix('.xmp');before=sidecar.read_bytes();base=self.base.read_bytes()
        old=dict(self.c.comparison)
        with patch('development_profiles.resolve_adobe',return_value=self.resolved),patch('render_workflow.adobe_request',side_effect=lambda c,s:s),patch.object(self.c,'compare_call',side_effect=[{'ok':True},RuntimeError('manually edited')]):
            with self.assertRaises(RuntimeError):self.c.set_comparison_profile('adobe','adobe_standard')
        self.assertEqual(sidecar.read_bytes(),before)
        self.assertEqual(self.base.read_bytes(),base)
        self.assertEqual(self.c.comparison,old)

    def test_manual_edit_rejected_before_native_render(self):
        with patch.object(self.c,'compare_call',side_effect=RuntimeError('manual')),patch('render_workflow.prepare_sony') as prepare:
            with self.assertRaises(RuntimeError):self.c.set_comparison_profile('sony','sony:8')
            prepare.assert_not_called()

    def test_same_profile_is_noop(self):
        with patch.object(self.c,'compare_call') as ps:
            self.assertTrue(self.c.set_comparison_profile('adobe','camera_standard')['unchanged'])
            self.assertTrue(self.c.set_comparison_profile('sony','camera_standard')['unchanged'])
            ps.assert_not_called()

    def test_pending_import_blocks_profile(self):
        self.c.recovery={'kind':'open'}
        with patch.object(self.c,'compare_call') as ps:
            with self.assertRaises(RuntimeError):self.c.set_comparison_profile('adobe','adobe_color')
            ps.assert_not_called()

    def test_missing_or_corrupt_prerender_falls_back_to_normal_render(self):
        state=dict(self.c.comparison,dimensions={'original':[6000,4000]})
        token='d'*32;job=self.root/token;job.mkdir()
        self.c.full_prepared=dict(comparison_id=state['id'],revision=state['revision'],token=token,render=str(job/'missing.tif'))
        self.c.bridge=SimpleNamespace(project=lambda ident:(self.root,{}),Sony=lambda:None,
                                      CACHE=self.root,child=lambda root,ident:root/ident)
        for content in (None,'{invalid'):
            if content is not None:(job/'job.json').write_text(content,encoding='utf-8')
            with self.subTest(content=content),patch.object(self.c,'sony_lane',return_value=nullcontext()),patch('render_workflow._guard_live'),patch('render_workflow.full_sony',return_value={'render':'fresh'}) as render:
                self.assertEqual(self.c.obtain_full_sony(state),{'render':'fresh'})
                render.assert_called_once_with(self.c,state)

    def test_prerender_manual_recipe_guard_never_falls_back(self):
        state=dict(self.c.comparison,dimensions={'original':[6000,4000]})
        self.c.full_prepared=dict(comparison_id=state['id'],revision=state['revision'])
        self.c.bridge=SimpleNamespace(project=lambda ident:(self.root,{}),Sony=lambda:None)
        with patch.object(self.c,'sony_lane',return_value=nullcontext()),patch('render_workflow._guard_live',side_effect=RuntimeError('manual')),patch('render_workflow.full_sony') as render:
            with self.assertRaisesRegex(RuntimeError,'manual'):self.c.obtain_full_sony(state)
            render.assert_not_called()

    def test_unsupported_engine_cannot_modify_state(self):
        with self.assertRaises(RuntimeError):self.c.set_comparison_profile('anything','profile')


class CachedRecipeTests(unittest.TestCase):
    def setUp(self):
        self.data={'id':'a'*32,'active_revision':'b'*32}
        self.revision='c'*32;self.folder=Path('private-project')
        self.sony=SimpleNamespace(active_name=Mock(return_value='SonyRAW-'+self.data['id']+'.ARW'))
        self.c=SimpleNamespace(bridge=SimpleNamespace(activate=Mock()))

    def test_locked_scratch_cleanup_does_not_mask_recipe_validation(self):
        from render_workflow import _guard_live
        with tempfile.TemporaryDirectory() as directory:
            self.c.session=Path(directory)/'session.json'
            saved=Path(directory)/'saved.xml';saved.write_bytes(b'recipe')
            self.c.bridge.settings_path=Mock(return_value=saved)
            for equal in (True,False):
                held=[]
                def save(path,name):
                    path.write_bytes(b'recipe');held.append(path.open('rb'))
                self.sony.save_settings=save
                try:
                    with patch('render_workflow.recipes_equal',return_value=equal) as compare:
                        if equal:_guard_live(self.c,self.sony,self.folder,self.data,self.revision)
                        else:
                            with self.assertRaisesRegex(RuntimeError,'вручную'):
                                _guard_live(self.c,self.sony,self.folder,self.data,self.revision)
                        compare.assert_called_once()
                finally:
                    for stream in held:stream.close()

    def test_prior_owned_profile_is_checked_before_loading_cached_revision(self):
        from render_workflow import _align_cached_recipe
        with patch('render_workflow._guard_live') as guard:
            _align_cached_recipe(self.c,self.sony,self.folder,self.data,self.revision)
        guard.assert_called_once_with(self.c,self.sony,self.folder,self.data,'b'*32)
        self.c.bridge.activate.assert_called_once_with(self.sony,self.folder,self.data,self.revision)

    def test_manual_edit_is_not_hidden_by_a_cached_profile(self):
        from render_workflow import _align_cached_recipe
        with patch('render_workflow._guard_live',side_effect=RuntimeError('manual')):
            with self.assertRaisesRegex(RuntimeError,'manual'):
                _align_cached_recipe(self.c,self.sony,self.folder,self.data,self.revision)
        self.c.bridge.activate.assert_not_called()

    def test_matching_revision_does_not_add_an_activation(self):
        from render_workflow import _align_cached_recipe
        with patch('render_workflow._guard_live'):
            _align_cached_recipe(self.c,self.sony,self.folder,self.data,self.data['active_revision'])
        self.c.bridge.activate.assert_not_called()

    def test_foreign_active_tab_is_not_switched_on_a_cache_hit(self):
        from render_workflow import _align_cached_recipe
        self.sony.active_name.return_value='other.ARW'
        with patch('render_workflow._guard_live'):
            _align_cached_recipe(self.c,self.sony,self.folder,self.data,self.revision)
        self.c.bridge.activate.assert_not_called()


if __name__=='__main__':unittest.main()
