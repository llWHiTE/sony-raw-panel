from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from lut_library import Library, validate, apply_xmp, CRS
from comparison_adobe import adobe_copy

CUBE='TITLE "test"\nLUT_3D_SIZE 2\n'+'\n'.join('%d %d %d'%(r,g,b) for b in (0,1) for g in (0,1) for r in (0,1))+'\n'


class LutTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.bundle=self.root/'bundle';(self.bundle/'bundled-luts').mkdir(parents=True)
        self.data=self.root/'data';self.data.mkdir()
        self.original=self.bundle/'bundled-luts/test.cube';self.original.write_text(CUBE)
        self.lib=Library(self.data,self.bundle)

    def tearDown(self):self.temp.cleanup()

    def test_initial_library_can_be_removed_without_reappearing(self):
        self.assertEqual(len(self.lib.entries()),1)
        self.lib.remove(self.lib.entries()[0])
        self.assertTrue(self.original.exists())
        self.assertEqual(Library(self.data,self.bundle).entries(),[])

    def test_snapshot_survives_library_deletion(self):
        path=self.lib.entries()[0];state=self.lib.snapshot(path)
        self.lib.remove(path)
        self.assertEqual(Path(state['path']).read_text(),CUBE)
        self.assertEqual(state['kind'],'cube')

    def test_duplicate_import_and_name_collision(self):
        first=self.lib.add(self.original)
        self.assertEqual(len(self.lib.entries()),1)
        other=self.root/'test.cube';other.write_text(CUBE.replace('TITLE "test"','TITLE "other"'))
        second=self.lib.add(other)
        self.assertNotEqual(first,second)
        self.assertEqual(len(self.lib.entries()),2)

    def test_malformed_and_nonfinite_cube_rejected(self):
        path=self.root/'bad.cube'
        for text in ('LUT_3D_SIZE 33\n0 0 0',CUBE.replace('0 0 0','NaN 0 0'),'LUT_1D_SIZE 2\n0 0 0'):
            path.write_text(text)
            with self.assertRaises(ValueError):validate(path)

    def test_remove_cannot_target_original(self):
        with self.assertRaises(ValueError):self.lib.remove(self.original)
        self.assertTrue(self.original.exists())

    def test_xmp_changes_private_adobe_sidecar_only_and_excludes_crop(self):
        source=self.root/'source.ARW';source.write_bytes(b'raw')
        source.with_suffix('.xmp').write_text('original sidecar')
        folder=self.root/'private';folder.mkdir()
        private=adobe_copy(folder,source,'a'*32)
        xmp=self.root/'look.xmp'
        xmp.write_text('<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description xmlns:crs="'+CRS+'" crs:Contrast2012="12" crs:CameraProfile="Adobe Standard" crs:CropTop="0.2" crs:HasCrop="True"/></rdf:RDF></x:xmpmeta>')
        self.assertTrue(validate(xmp))
        result=apply_xmp(private,dict(kind='xmp',path=str(xmp)))
        self.assertEqual(result,'Adobe Standard')
        text=private.with_suffix('.xmp').read_text()
        self.assertIn('Contrast2012="12"',text)
        self.assertNotIn('CropTop',text)
        self.assertIn('HasCrop="False"',text)
        self.assertEqual(source.with_suffix('.xmp').read_text(),'original sidecar')
        self.assertEqual(source.read_bytes(),b'raw')

    def test_xmp_entities_rejected(self):
        path=self.root/'unsafe.xmp';path.write_text('<!DOCTYPE x [<!ENTITY t "x">]><x/>')
        with self.assertRaises(ValueError):validate(path)


if __name__=='__main__':unittest.main()
