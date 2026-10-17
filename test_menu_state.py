import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import bridge


class SonyMenuTests(unittest.TestCase):
    def setUp(self):
        self.sony = bridge.Sony.__new__(bridge.Sony)
        self.sony.main = 99
        self.items = {1: [(0xffffffff, 2), (0xffffffff, 3)],
                      2: [(57601, None), (41217, None)],
                      3: [(37395, None), (0xffffffff, 4)],
                      4: [(37396, None)]}
        self.user = SimpleNamespace(
            GetMenu=Mock(return_value=1),
            GetSubMenu=Mock(side_effect=lambda menu, i: self.items[menu][i][1]),
            GetMenuItemCount=Mock(side_effect=lambda menu: len(self.items[menu])),
            GetMenuItemID=Mock(side_effect=lambda menu, i: self.items[menu][i][0]),
            GetMenuState=Mock(return_value=0))

    def test_refreshes_only_containing_popup(self):
        with patch.object(bridge.w, 'u', self.user), patch.object(bridge.w, 'send') as send:
            self.assertEqual(self.sony.command_state(37395), 0)
            send.assert_called_once_with(99, 0x0117, 3, 1)
            self.user.GetMenuState.assert_called_once_with(3, 37395, 0)

    def test_nested_popup_uses_its_parent_position(self):
        with patch.object(bridge.w, 'u', self.user), patch.object(bridge.w, 'send') as send:
            self.sony.command_state(37396)
            send.assert_called_once_with(99, 0x0117, 4, 1)

    def test_unknown_command_does_not_initialize_root(self):
        with patch.object(bridge.w, 'u', self.user), patch.object(bridge.w, 'send') as send:
            self.assertEqual(self.sony.command_state(123), -1)
            send.assert_not_called()
            self.user.GetMenuState.assert_not_called()

    def test_disabled_command_remains_disabled(self):
        self.user.GetMenuState.return_value = 3
        with patch.object(bridge.w, 'u', self.user), patch.object(bridge.w, 'send'):
            self.assertEqual(self.sony.command_state(41217), 3)


if __name__ == '__main__':
    unittest.main()
