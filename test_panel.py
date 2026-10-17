import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('panel_core', ROOT / 'panel_core.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class FakePhotoshop:
    def __init__(self):
        self.calls = []
        self.fail_replace = False

    def call(self, action, data=None, start=False):
        self.calls.append((action, data))
        if action == 'replace':
            if self.fail_replace:
                raise RuntimeError('Photoshop busy')
            target = dict(data['target'])
            target['revision'] = data['render']['token']
            return {'target': target}
        if action == 'open':
            return {'target': {'document': 7, 'layer': 2, 'project': data['project'], 'revision': data['token']}}
        return {'ok': True}

    def foreground(self):
        pass


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous_root = p.ROOT
        p.ROOT = Path(self.temp.name)
        self.controller = p.Controller()
        self.controller.ps = FakePhotoshop()
        self.target = dict(document=1, layer=2, project='a'*32, revision='b'*32)
        self.render = dict(project='a'*32, token='c'*32, render=str(p.ROOT/'result.tif'))

    def tearDown(self):
        p.ROOT = self.previous_root
        self.temp.cleanup()

    def test_cross_document_identity_is_not_equal(self):
        other = dict(self.target, document=9)
        self.assertFalse(p.same_target(self.target, other))

    def test_edit_persists_exact_target(self):
        with patch.object(p, 'operation', return_value={'reused': True}):
            self.controller.edit(self.target)
        self.assertEqual(self.controller.pending, self.target)
        restored = p.Controller()
        self.assertEqual(restored.pending, self.target)

    def test_apply_preserves_target_and_acknowledges_only_after_import(self):
        self.controller.pending = dict(self.target)
        calls = []
        def operation(request):
            calls.append(request)
            if request['action'] == 'update':
                return self.render
            self.assertEqual(self.controller.ps.calls[-1][0], 'replace')
            return {'cleaned': True}
        with patch.object(p, 'operation', side_effect=operation):
            result = self.controller.apply()
        self.assertEqual(result['target']['document'], 1)
        self.assertEqual(result['target']['revision'], 'c'*32)
        self.assertIsNone(self.controller.pending)
        self.assertEqual([r['action'] for r in calls], ['update','ack'])

    def test_failed_import_is_retried_without_second_render(self):
        self.controller.pending = dict(self.target)
        self.controller.ps.fail_replace = True
        with patch.object(p, 'operation', return_value=self.render) as op:
            with self.assertRaises(RuntimeError):
                self.controller.apply()
            self.assertEqual(op.call_count, 1)
        self.assertIsNotNone(self.controller.pending)
        self.assertEqual(p.Controller().recovery['render'], self.render)
        self.controller.ps.fail_replace = False
        with patch.object(p, 'operation', return_value={'cleaned': True}) as op:
            self.controller.retry_import()
            self.assertEqual(op.call_args.args[0]['action'], 'ack')
            self.assertEqual(op.call_count, 1)
        self.assertIsNone(self.controller.recovery)

    def test_open_cannot_replace_pending_edit(self):
        self.controller.pending = dict(self.target)
        with patch.object(p, 'operation') as op:
            with self.assertRaises(RuntimeError):
                self.controller.open(Path('any.ARW'))
            op.assert_not_called()

    def test_failed_validation_does_not_start_sony_render(self):
        self.controller.pending = dict(self.target)
        with patch.object(self.controller.ps, 'call', side_effect=RuntimeError('stale layer')), patch.object(p, 'operation') as op:
            with self.assertRaises(RuntimeError):
                self.controller.apply()
            op.assert_not_called()


if __name__ == '__main__':
    unittest.main()
