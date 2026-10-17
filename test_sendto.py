import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import windows_integration as win


class SendToTests(unittest.TestCase):
    def test_native_shortcut_lifecycle_in_isolated_folder_only(self):
        with tempfile.TemporaryDirectory(prefix='sony-sendto-') as temp:
            root=Path(temp);exe=root/'Sony Panel with spaces.exe';exe.write_bytes(b'test target, never executed')
            with patch.dict(os.environ,SONY_RAW_LAUNCHER=str(exe)):
                win.shortcut('install',root)
                link=root/'Sony RAW Panel.lnk'
                self.assertTrue(link.is_file())
                win.shortcut('install',root)
                self.assertTrue(link.is_file())
                win.shortcut('remove',root)
                self.assertFalse(link.exists())
                self.assertTrue(exe.exists())

    def test_other_portable_shortcut_is_not_overwritten_or_removed(self):
        with tempfile.TemporaryDirectory(prefix='sony-sendto-') as temp:
            root=Path(temp);other=root/'other';other.mkdir()
            first=root/'Sony.exe';first.write_bytes(b'one')
            second=other/'Sony.exe';second.write_bytes(b'two')
            with patch.dict(os.environ,SONY_RAW_LAUNCHER=str(first)):
                win.shortcut('install',root)
            link=root/'Sony RAW Panel.lnk';before=link.read_bytes()
            with patch.dict(os.environ,SONY_RAW_LAUNCHER=str(second)):
                with self.assertRaises(RuntimeError):win.shortcut('install',root)
                with self.assertRaises(RuntimeError):win.shortcut('remove',root)
            self.assertEqual(link.read_bytes(),before)


if __name__=='__main__':unittest.main()
