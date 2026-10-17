import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('bridge_v2', ROOT / 'bridge_v2.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_cache = b.CACHE
        b.CACHE = Path(self.temp.name) / 'cache'
        b.CACHE.mkdir()
        self.project = uuid.uuid4().hex
        self.token = uuid.uuid4().hex
        self.job = b.CACHE / self.token
        self.job.mkdir()
        self.raster = self.job / ('SonyRAW-' + self.project + '.tif')
        self.raster.write_bytes(b'private disposable test image')
        self.recipe = self.job / 'do-not-delete.xml'
        self.recipe.write_text('recipe')
        self.state = dict(version=2, token=self.token, project=self.project, status='ready')
        self.save()

    def save(self):
        (self.job / 'job.json').write_text(json.dumps(self.state), encoding='utf-8')

    def tearDown(self):
        b.CACHE = self.old_cache
        self.temp.cleanup()

    def test_ready_render_is_not_deleted_without_ack(self):
        self.assertFalse(b.clean_job(self.token)['cleaned'])
        self.assertTrue(self.raster.exists())

    def test_ack_deletes_only_expected_raster(self):
        self.assertTrue(b.clean_job(self.token, True, self.project)['cleaned'])
        self.assertFalse(self.raster.exists())
        self.assertTrue(self.recipe.exists())
        self.assertTrue(b.clean_job(self.token, True, self.project)['cleaned'])

    def test_versioned_render_is_cleaned(self):
        target = self.job / ('SonyRAW-' + self.project + '-' + self.token + '.tif')
        self.raster.rename(target)
        self.state['filename'] = target.name
        self.save()
        self.assertTrue(b.clean_job(self.token, True, self.project)['cleaned'])
        self.assertFalse(target.exists())

    def test_unexpected_filename_is_not_deleted(self):
        self.state['filename'] = 'do-not-delete.xml'
        self.save()
        with self.assertRaises(ValueError):
            b.clean_job(self.token, True, self.project)
        self.assertTrue(self.recipe.exists())

    def test_cross_project_ack_is_rejected(self):
        with self.assertRaises(ValueError):
            b.clean_job(self.token, True, uuid.uuid4().hex)
        self.assertTrue(self.raster.exists())

    def test_failed_render_cannot_be_acknowledged(self):
        self.state['status'] = 'rendering'
        self.save()
        with self.assertRaises(ValueError):
            b.clean_job(self.token, True, self.project)
        self.assertTrue(self.raster.exists())

    def test_path_traversal_is_rejected(self):
        for value in ('../other', 'C:/private', '', 'f' * 31, 'f' * 33):
            with self.subTest(value=value), self.assertRaises(ValueError):
                b.clean_job(value, True, self.project)


class WriterCompletionTests(unittest.TestCase):
    def test_closed_writer_also_waits_for_sony_progress_to_close(self):
        with tempfile.TemporaryDirectory() as directory:
            image=Path(directory)/'ready.tif';image.write_bytes(b'0'*24)
            sony=object.__new__(b.Sony)
            tags={256:[1],257:[1],259:[1]}
            with patch.object(b.w.k,'CreateFileW',return_value=123),patch.object(b.w.k,'CloseHandle'),patch.object(b.base,'tiff_info',return_value=tags),patch.object(sony,'ready') as ready:
                self.assertEqual(sony.complete_tiff(image),tags)
                ready.assert_called_once_with(300,allow_progress=True)

    def test_completion_does_not_dismiss_an_unexpected_dialog(self):
        with tempfile.TemporaryDirectory() as directory:
            image=Path(directory)/'ready.tif';image.write_bytes(b'0'*24)
            sony=object.__new__(b.Sony)
            with patch.object(b.w.k,'CreateFileW',return_value=123),patch.object(b.w.k,'CloseHandle'),patch.object(b.base,'tiff_info',return_value={256:[1],257:[1],259:[1]}),patch.object(sony,'ready',side_effect=RuntimeError('Sony requires attention')):
                with self.assertRaisesRegex(RuntimeError,'attention'):sony.complete_tiff(image)
            self.assertTrue(image.exists())


class RecipeTests(unittest.TestCase):
    def test_saved_revision_not_latest_recipe_is_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            old = uuid.uuid4().hex
            new = uuid.uuid4().hex
            a = folder / ('settings-' + old + '.xml')
            z = folder / ('settings-' + new + '.xml')
            a.write_text('older recipe')
            z.write_text('newer recipe')
            data = dict(settings=z.name, settings_sha256=b.base.sha(z), recipes={a.name: b.base.sha(a), z.name: b.base.sha(z)})
            self.assertEqual(b.settings_path(folder, data, old), a)
            self.assertEqual(b.settings_path(folder, data), z)
            a.write_text('modified externally')
            with self.assertRaises(ValueError):
                b.settings_path(folder, data, old)


if __name__ == '__main__':
    unittest.main()
