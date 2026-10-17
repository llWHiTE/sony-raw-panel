import ctypes as C
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import windows_integration as win


class WindowsIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.raw=self.root/'Кадр с пробелом.ARW';self.raw.write_bytes(b'raw')

    def test_unicode_file_only_protocol(self):
        payload=win.encode_paths([self.raw])
        self.assertEqual(win.decode_paths(payload),[str(self.raw)])
        self.assertEqual(win.decode_paths(win.encode_paths([])),[])

    def test_no_commands_or_relative_paths_accepted(self):
        payloads=[b'{"version":1,"files":[],"command":"apply"}',b'{"version":1,"files":["relative.ARW"]}',
                  b'{"version":2,"files":[]}',b'[]',b'x'*(win.MAX_BYTES+1)]
        for payload in payloads:
            with self.subTest(payload=payload[:80]),self.assertRaises(ValueError):win.decode_paths(payload)

    def test_non_raw_and_missing_file_rejected(self):
        path=self.root/'other.ps1';path.write_text('not executable')
        with self.assertRaises(ValueError):win.encode_paths([path])
        with self.assertRaises(FileNotFoundError):win.encode_paths([self.root/'missing.ARW'])

    def test_channel_scopes_instances_to_data_root(self):
        self.assertEqual(win.channel(self.root),win.channel(self.root))
        self.assertNotEqual(win.channel(self.root),win.channel(self.root/'other'))

    def test_hotkeys_validate_and_disable_key_repeat(self):
        self.assertEqual(win.hotkey('Ctrl+Alt+Shift+Enter'),(0x4007,13))
        self.assertEqual(win.hotkey('Ctrl+Alt+Shift+S'),(0x4007,ord('S')))
        for value in ('S','Ctrl+Ctrl+S','Ctrl+F999','Ctrl+Escape','Bad+S'):
            with self.assertRaises(ValueError):win.hotkey(value)

    def test_conflict_rolls_back_previous_registration(self):
        keys=win.Hotkeys(1)
        with patch.object(win.w.u,'RegisterHotKey',return_value=True),patch.object(win.w.u,'UnregisterHotKey',return_value=True):
            keys.configure(True)
            old=keys.config
            # Fail one new registration, then allow restoring the old settings.
            with patch.object(win.w.u,'RegisterHotKey',side_effect=[False,True,True,True]):
                with self.assertRaises(ValueError):keys.configure(True,dict(win.DEFAULT_KEYS,edit='Ctrl+Alt+Shift+X'))
            self.assertEqual(keys.config,old)
            self.assertEqual(len(keys.registered),3)
            keys.close();self.assertEqual(keys.registered,{})

    def test_duplicate_hotkeys_do_not_unregister_current_keys(self):
        keys=win.Hotkeys(1)
        with patch.object(win.w.u,'UnregisterHotKey') as unregister:
            with self.assertRaises(ValueError):keys.configure(True,dict(win.DEFAULT_KEYS,apply=win.DEFAULT_KEYS['edit']))
            unregister.assert_not_called()

    def test_source_mode_does_not_install_any_shortcut(self):
        with patch.dict('os.environ',{},clear=True):
            with self.assertRaises(ValueError):win.shortcut('install',self.root)
        self.assertFalse((self.root/'Sony RAW Panel.lnk').exists())


if __name__=='__main__':unittest.main()
