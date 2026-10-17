import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import panel_core as core
from comparison_adobe import write_sidecar
from lut_library import CRS, RDF


class LiveLutTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.paths=patch.object(core,'ROOT',self.root);self.paths.start();self.addCleanup(self.paths.stop)
        self.c=core.Controller(session=self.root/'session.json')
        self.c.ps=SimpleNamespace(foreground=lambda:None)
        self.view=dict(document=7,sonyLayer=2,adobeLayer=3,previewID='a'*32,historyCount=4,layerCount=2)
        self.c.comparison=dict(id='a'*32,project='b'*32,revision='c'*32,view=self.view,shown='adobe',source='photo.ARW',lut=None)
        self.lut=dict(kind='cube',path='verified.cube',name='Test',sha256='d'*64)

    def test_cube_switch_only_calls_one_photoshop_command_and_commits_after_success(self):
        updated=dict(self.view,lutLayer=4,layerCount=3,historyCount=6)
        def compare(action,request):
            self.assertEqual(action,'lut');self.assertFalse(request['refreshAdobe'])
            self.assertIsNone(self.c.comparison['lut'])
            return dict(comparison=updated)
        with patch.object(self.c,'compare_call',side_effect=compare) as ps,patch.object(core,'operation',side_effect=AssertionError('No Sony')):
            result=self.c.set_comparison_lut(self.lut)
        self.assertEqual(ps.call_count,1)
        self.assertFalse(result['adobe_rendered'])
        self.assertEqual(self.c.comparison['lut'],self.lut)
        self.assertEqual(self.c.comparison['view'],updated)
        self.assertEqual(self.c.comparison['shown'],'adobe')
        self.assertEqual(json.loads(self.c.session.read_text())['comparison']['lut'],self.lut)

    def test_failed_switch_preserves_view_and_selection(self):
        original=copy.deepcopy(self.c.comparison)
        with patch.object(self.c,'compare_call',side_effect=RuntimeError('modified')):
            with self.assertRaises(RuntimeError):self.c.set_comparison_lut(self.lut)
        self.assertEqual(self.c.comparison,original)

    def test_switch_off_removes_lut_in_state(self):
        self.c.comparison['lut']=self.lut
        with patch.object(self.c,'compare_call',return_value=dict(comparison=self.view)):
            self.c.set_comparison_lut(None)
        self.assertIsNone(self.c.comparison['lut'])

    def test_same_selection_does_not_contact_photoshop(self):
        self.c.comparison['lut']=self.lut
        with patch.object(self.c,'compare_call') as ps:
            self.assertTrue(self.c.set_comparison_lut(dict(self.lut))['unchanged'])
        ps.assert_not_called()

    def test_pending_import_blocks_switch(self):
        self.c.recovery={'kind':'open'}
        with patch.object(self.c,'compare_call') as ps:
            with self.assertRaises(RuntimeError):self.c.set_comparison_lut(self.lut)
        ps.assert_not_called()

    def sidecars(self):
        raw=self.root/'AdobeRAW-test.ARW';raw.write_bytes(b'private raw')
        write_sidecar(raw)
        base=self.root/'adobe-base.xmp';base.write_bytes(raw.with_suffix('.xmp').read_bytes())
        preset=self.root/'look.xmp'
        preset.write_text('<x xmlns:rdf="%s" xmlns:crs="%s"><rdf:Description crs:CameraProfile="Wrong" crs:Exposure2012="1.5"/></x>'%(RDF,CRS))
        self.c.comparison.update(directory=str(self.root),adobe=str(raw),adobeBase=str(base))
        return raw,dict(kind='xmp',path=str(preset),name='Look',sha256='e'*64)

    def test_xmp_refresh_restores_frozen_profile_and_preserves_adjustments(self):
        raw,selection=self.sidecars()
        def compare(action,request):
            self.assertTrue(request['refreshAdobe'])
            d=ET.parse(raw.with_suffix('.xmp')).find('.//{'+RDF+'}Description')
            self.assertEqual(d.get('{'+CRS+'}CameraProfile'),'Camera ST')
            self.assertEqual(d.get('{'+CRS+'}Exposure2012'),'1.5')
            return dict(comparison=self.view)
        with patch.object(self.c,'compare_call',side_effect=compare):
            self.assertTrue(self.c.set_comparison_lut(selection)['adobe_rendered'])

    def test_failed_xmp_refresh_rolls_back_sidecar_and_state(self):
        raw,selection=self.sidecars();sidecar=raw.with_suffix('.xmp');before=sidecar.read_bytes()
        state=copy.deepcopy(self.c.comparison)
        with patch.object(self.c,'compare_call',side_effect=RuntimeError('decode failed')):
            with self.assertRaises(RuntimeError):self.c.set_comparison_lut(selection)
        self.assertEqual(sidecar.read_bytes(),before)
        self.assertEqual(self.c.comparison,state)

    def test_xmp_hardlinked_sidecar_is_never_overwritten(self):
        raw,selection=self.sidecars();sidecar=raw.with_suffix('.xmp')
        original=self.root/'original.xmp';original.write_bytes(sidecar.read_bytes())
        sidecar.unlink()
        try:sidecar.hardlink_to(original)
        except OSError as error:self.skipTest(str(error))
        before=original.read_bytes()
        with patch.object(self.c,'compare_call') as ps:
            with self.assertRaises(RuntimeError):self.c.set_comparison_lut(selection)
        ps.assert_not_called()
        self.assertEqual(original.read_bytes(),before)

    def test_old_comparison_requires_base_for_xmp_but_allows_cube(self):
        self.c.comparison.update(adobe=str(self.root/'private.ARW'),directory=str(self.root))
        with patch.object(self.c,'compare_call') as ps:
            with self.assertRaises(RuntimeError):self.c.set_comparison_lut(dict(kind='xmp',path='look.xmp'))
            ps.assert_not_called()

    def test_full_adobe_uses_last_successful_lut(self):
        self.c.comparison['lut']=self.lut
        with patch.object(self.c,'compare_call',return_value=dict(document=7)) as ps,patch.object(self.c,'finish_comparison'):
            self.c.choose_comparison('adobe')
        self.assertEqual(ps.call_args.args[0],'adobeFull')
        self.assertEqual(ps.call_args.args[1]['lut'],self.lut)

    def test_full_sony_uses_last_successful_lut(self):
        self.c.comparison['lut']=self.lut
        render=dict(project='b'*32,token='f'*32,render='render.tif')
        self.c.ps.call=lambda *args,**kwargs:dict(target=dict(document=7))
        with patch.object(core,'operation',return_value=render),patch.object(self.c,'_ack',return_value=True),patch.object(self.c,'finish_comparison'):
            self.c.choose_comparison('sony')
        self.assertEqual(render['lut'],self.lut)


if __name__=='__main__':unittest.main()
