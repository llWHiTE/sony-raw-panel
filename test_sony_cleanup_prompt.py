from types import SimpleNamespace
import unittest

from preview_cleanup import close_sony_preview, save_prompt


class Windows:
    def __init__(self, text=None, prompt=True, owner=10):
        self.current = 'SonyRAW-' + 'a'*32 + '.ARW'
        self.names = [self.current]
        self.prompt = prompt
        self.shown = False
        self.owner = owner
        self.message = text or ('Сохранить изменения в\n' + self.current + '?')
        self.clicks = []
        self.u = self

    def GetWindow(self, handle, relation): return self.owner
    def GetDlgCtrlID(self, handle): return {21:0, 22:6, 23:7, 24:2}.get(handle,0)
    def IsWindowVisible(self, handle): return True
    def IsWindowEnabled(self, handle): return not self.shown if handle == 10 else True
    def pid(self, handle): return 100
    def cls(self, handle): return {20:'#32770',21:'Static',22:'Button',23:'Button',24:'Button'}.get(handle,'')
    def windows(self, handle): return [21,22,23,24] if handle == 20 else []
    def get_text(self, handle): return self.message if handle == 21 else ''
    def post(self, *args):
        if self.prompt: self.shown = True
        else: self.names = []
    def click(self, handle):
        self.clicks.append(handle)
        self.shown = False
        if handle == 23: self.names = []
    def wait(self, check, seconds, label):
        for _ in range(5):
            if check(): return True
        raise TimeoutError(label)


class SonyCleanupPromptTests(unittest.TestCase):
    def setup(self, w):
        def ready(seconds):
            if w.shown: raise RuntimeError('existing dialog')
        sony = SimpleNamespace(main=10,pid=100,ready=ready,active_name=lambda:w.current,dialogs=lambda:[20] if w.shown else [])
        return SimpleNamespace(w=w), sony

    def test_unchanged_private_preview_discards_only_its_save_prompt(self):
        w=Windows();bridge,sony=self.setup(w)
        close_sony_preview(bridge,sony,w.current,lambda:w.names)
        self.assertEqual(w.clicks,[23])
        self.assertEqual(w.names,[])

    def test_close_without_save_prompt(self):
        w=Windows(prompt=False);bridge,sony=self.setup(w)
        close_sony_preview(bridge,sony,w.current,lambda:w.names)
        self.assertEqual(w.clicks,[])
        self.assertEqual(w.names,[])

    def test_raced_close_of_other_photo_is_cancelled_not_discarded(self):
        w=Windows(text='Save changes to Other.ARW?');bridge,sony=self.setup(w)
        with self.assertRaises(RuntimeError):close_sony_preview(bridge,sony,w.current,lambda:w.names)
        self.assertEqual(w.clicks,[24])
        self.assertEqual(w.names,[w.current])

    def test_unknown_question_is_never_accepted(self):
        w=Windows(text='Delete ' + 'SonyRAW-'+'a'*32+'.ARW?');bridge,sony=self.setup(w)
        with self.assertRaises(RuntimeError):close_sony_preview(bridge,sony,w.current,lambda:w.names)
        self.assertEqual(w.clicks,[])
        self.assertTrue(w.shown)

    def test_unrelated_owner_is_never_accepted(self):
        w=Windows(owner=11);bridge,sony=self.setup(w)
        self.assertIsNone(save_prompt(w,sony,20))

    def test_existing_modal_dialog_is_not_touched(self):
        w=Windows();w.shown=True;bridge,sony=self.setup(w)
        with self.assertRaises(RuntimeError):close_sony_preview(bridge,sony,w.current,lambda:w.names)
        self.assertEqual(w.clicks,[])

    def test_non_service_name_is_rejected_before_close(self):
        w=Windows();bridge,sony=self.setup(w)
        with self.assertRaises(ValueError):close_sony_preview(bridge,sony,'Original.ARW',lambda:w.names)
        self.assertEqual(w.clicks,[])
        self.assertFalse(w.shown)

    def test_tab_change_before_close_aborts(self):
        w=Windows();bridge,sony=self.setup(w);sony.active_name=lambda:'Other.ARW'
        with self.assertRaises(RuntimeError):close_sony_preview(bridge,sony,w.current,lambda:w.names)
        self.assertEqual(w.clicks,[])
        self.assertFalse(w.shown)


if __name__ == '__main__':unittest.main()
