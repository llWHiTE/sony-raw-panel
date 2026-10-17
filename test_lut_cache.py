from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import lut_library as library
import lut_profile


class LutCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.path=self.root/'test.cube'
        self.path.write_text('LUT_3D_SIZE 2\n'+'\n'.join('%d %d %d'%(r,g,b) for b in range(2) for g in range(2) for r in range(2)))
        self.lib=library.Library(self.root,self.root)
        self.entry=self.lib.add(self.path)

    def test_repeated_snapshot_does_not_reparse_or_recompile_verified_files(self):
        with patch.object(library,'validate_uncached',wraps=library.validate_uncached) as validate,patch.object(lut_profile,'compile_profile',wraps=lut_profile.compile_profile) as compile:
            first=self.lib.snapshot(self.entry)
            calls=validate.call_count
            self.assertEqual(self.lib.snapshot(self.entry),first)
            self.assertEqual(library.prepare_lut(first,self.root),first)
            self.assertEqual(validate.call_count,calls)
            self.assertEqual(compile.call_count,1)

    def test_source_change_invalidates_cached_validation(self):
        first=self.lib.snapshot(self.entry)
        self.entry.write_text(self.entry.read_text()+'\n# changed\n')
        second=self.lib.snapshot(self.entry)
        self.assertNotEqual(second['sha256'],first['sha256'])
        self.assertNotEqual(second['path'],first['path'])

    def test_corrupt_profile_is_rebuilt_not_reused(self):
        first=self.lib.snapshot(self.entry)
        profile=Path(first['profile']);before=profile.read_bytes();profile.write_bytes(b'bad')
        with patch.object(lut_profile,'compile_profile',wraps=lut_profile.compile_profile) as compile:
            self.assertEqual(library.prepare_lut(first,self.root),first)
            compile.assert_called_once()
        self.assertEqual(profile.read_bytes(),before)

    def test_removed_profile_is_rebuilt(self):
        first=self.lib.snapshot(self.entry);Path(first['profile']).unlink()
        self.assertEqual(library.prepare_lut(first,self.root),first)
        self.assertTrue(Path(first['profile']).is_file())

    def test_missing_library_entry_does_not_remove_operation_snapshot(self):
        first=self.lib.snapshot(self.entry);self.lib.remove(self.entry)
        self.assertTrue(Path(first['path']).is_file())
        self.assertEqual(library.prepare_lut(first,self.root),first)


if __name__=='__main__':unittest.main()
