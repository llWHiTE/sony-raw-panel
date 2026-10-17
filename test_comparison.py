import importlib.util
from pathlib import Path
import tempfile
import unittest
import uuid

ROOT=Path(__file__).resolve().parent

def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

compare=load('comparison')
adobe=load('comparison_adobe')


class PreviewTests(unittest.TestCase):
    def test_fast_preview_preserves_aspect(self):
        self.assertEqual(compare.scaled_size(6336,9504,1600),(1067,1600))
        self.assertEqual(compare.scaled_size(9504,6336,3000),(3000,2000))

    def test_full_does_not_resize(self):
        self.assertEqual(compare.scaled_size(6336,9504,0),(6336,9504))

    def test_small_source_is_not_upscaled(self):
        self.assertEqual(compare.scaled_size(800,600,1600),(800,600))

    def test_invalid_dimensions_rejected(self):
        for values in ((0,600,1600),(800,-1,1600),(800,600,-1)):
            with self.subTest(values=values),self.assertRaises(ValueError):compare.scaled_size(*values)

    def test_adobe_sidecar_never_written_beside_original(self):
        with tempfile.TemporaryDirectory() as temp:
            parent=Path(temp);source=parent/'original.ARW';source.write_bytes(b'raw-test-data')
            original_xmp=source.with_suffix('.xmp');original_xmp.write_text('user recipe')
            private=parent/'private';private.mkdir()
            copy=adobe.adobe_copy(private,source,uuid.uuid4().hex)
            self.assertNotEqual(copy,source)
            self.assertEqual(copy.read_bytes(),source.read_bytes())
            self.assertIn('Camera ST',copy.with_suffix('.xmp').read_text(encoding='utf-8'))
            self.assertEqual(original_xmp.read_text(),'user recipe')

    def test_adobe_copy_cannot_be_reused_if_modified(self):
        with tempfile.TemporaryDirectory() as temp:
            parent=Path(temp);source=parent/'original.ARW';source.write_bytes(b'raw')
            private=parent/'private';private.mkdir();ident=uuid.uuid4().hex
            copy=adobe.adobe_copy(private,source,ident);copy.write_bytes(b'changed')
            with self.assertRaises(ValueError):adobe.adobe_copy(private,source,ident)

    def test_invalid_identifier_rejected(self):
        with self.assertRaises(ValueError):adobe.adobe_copy(Path('.'),Path('raw.ARW'),'../outside')


if __name__=='__main__':unittest.main()
