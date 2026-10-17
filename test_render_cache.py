import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from render_cache import RenderCache, digest, key_for


class RenderCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = RenderCache(self.root, 100)
        self.image = self.root / 'source.tif'; self.image.write_bytes(b'image-data')
        self.key = key_for({'raw': 'abc', 'engine': 'sony', 'recipe': 'one'})

    def test_roundtrip_and_independent_copy(self):
        self.cache.put(self.key, self.image, {'engine': 'sony'})
        target = self.root / 'operation.tif'
        result = self.cache.copy(self.key, target)
        self.assertEqual(result['sha256'], digest(self.image))
        self.assertEqual(target.read_bytes(), self.image.read_bytes())
        self.assertEqual(target.stat().st_nlink, 1)
        target.write_bytes(b'edited')
        self.assertEqual(Path(self.cache.get(self.key)['path']).read_bytes(), b'image-data')

    def test_keys_cover_each_render_dependency(self):
        base = dict(raw='sha', engine='sony', version='v1', recipe='r', dimensions=[3000,2000], bits=16, space='sRGB')
        first = key_for(base)
        for key, value in dict(raw='other', engine='adobe', version='v2', recipe='new', dimensions=[2000,3000], bits=8, space='P3').items():
            with self.subTest(key=key): self.assertNotEqual(first, key_for(dict(base, **{key:value})))
        self.assertEqual(first, key_for(dict(reversed(list(base.items())))))

    def test_corruption_is_miss(self):
        self.cache.put(self.key, self.image, {})
        (self.cache.folder(self.key) / 'image.tif').write_bytes(b'corrupt')
        self.assertIsNone(self.cache.get(self.key))

    def test_non_object_manifest_is_miss(self):
        self.cache.put(self.key,self.image,{})
        (self.cache.folder(self.key)/'entry.json').write_text('[]',encoding='utf-8')
        self.assertIsNone(self.cache.get(self.key))

    def test_missing_manifest_is_miss(self):
        folder = self.cache.folder(self.key); folder.mkdir()
        (folder / 'image.tif').write_bytes(b'incomplete')
        self.assertIsNone(self.cache.get(self.key))

    def test_interrupted_publish_does_not_create_valid_entry(self):
        with patch('render_cache.atomic', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError): self.cache.put(self.key, self.image, {})
        self.assertIsNone(self.cache.get(self.key))
        self.assertFalse(list(self.cache.directory.glob('writing-*')))

    def test_limit_and_lru_preserve_pinned_entry(self):
        self.cache.limit = 10
        self.cache.put(self.key, self.image, {})
        second = key_for({'recipe':'two'})
        with self.cache.lease(self.key):
            self.cache.put(second, self.image, {})
            self.cache.trim()
            self.assertIsNotNone(self.cache.get(self.key))
        self.cache.trim()
        self.assertLessEqual(self.cache.trim()['bytes'], 10)

    def test_clear_keeps_active_lease_and_original(self):
        self.cache.put(self.key, self.image, {})
        with self.cache.lease(self.key):
            self.assertEqual(self.cache.trim(clear=True)['bytes_freed'], 0)
        self.assertEqual(self.cache.trim(clear=True)['bytes_freed'], 10)
        self.assertTrue(self.image.exists())

    def test_disabled_and_oversize_cache(self):
        self.cache.limit = 0
        self.assertIsNone(self.cache.put(self.key, self.image, {}))
        self.cache.limit = 2
        self.assertIsNone(self.cache.put(self.key, self.image, {}))

    def test_path_traversal_and_hardlinked_images_rejected(self):
        for key in ('../anything', 'x'*64, '', None):
            with self.assertRaises(ValueError): self.cache.folder(key)
        self.cache.put(self.key, self.image, {})
        target = self.cache.folder(self.key) / 'image.tif'; target.unlink()
        try: target.hardlink_to(self.image)
        except OSError as error: self.skipTest(str(error))
        self.assertIsNone(self.cache.get(self.key))
        self.cache.trim(clear=True)
        self.assertTrue(self.image.exists())

    def test_unknown_files_not_deleted(self):
        self.cache.put(self.key, self.image, {})
        other = self.cache.folder(self.key) / 'personal.ARW'; other.write_bytes(b'original')
        self.cache.trim(clear=True)
        self.assertTrue(other.exists())

    def test_rapid_same_size_rewrites_with_preserved_mtime(self):
        stamp=self.image.stat()
        for index in range(64):
            content=('%010d'%index).encode('ascii')
            self.image.write_bytes(content)
            os.utime(self.image,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
            self.assertEqual(digest(self.image),hashlib.sha256(content).hexdigest())

    @unittest.skipUnless(os.name=='nt','Windows volume version fallback')
    def test_volume_without_usn_uses_stable_content_verification(self):
        from render_cache import signature
        with patch('render_cache._windows_version',return_value=(0,None)):
            first=digest(self.image);stamp=signature(self.image)
            self.assertEqual(signature(self.image),stamp)
            self.image.write_bytes(b'new--image')
            self.assertNotEqual(digest(self.image),first)

    def test_hash_invalidated_after_rewrite(self):
        first = digest(self.image)
        self.image.write_bytes(b'new--image')
        self.assertNotEqual(first, digest(self.image))


if __name__ == '__main__': unittest.main()
