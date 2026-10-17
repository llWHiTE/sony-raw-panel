import hashlib
from pathlib import Path
import struct
import tempfile
import unittest

from lut_library import prepare_lut, validate
from lut_profile import compile_profile


class LutProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cube = self.root / 'identity.cube'
        self.cube.write_text('LUT_3D_SIZE 2\n' + '\n'.join('%d %d %d' % (r, g, b) for b in range(2) for g in range(2) for r in range(2)), encoding='utf-8')

    def tag(self, data, signature):
        for i in range(struct.unpack_from('>I', data, 128)[0]):
            name, offset, length = struct.unpack_from('>4sII', data, 132 + i * 12)
            self.assertEqual(offset % 4, 0)
            if name == signature:
                return data[offset:offset + length]
        self.fail('Missing tag: %r' % signature)

    def test_icc_header_and_determinism(self):
        data = compile_profile(self.cube)
        self.assertEqual(data, compile_profile(self.cube))
        self.assertEqual(struct.unpack_from('>I', data)[0], len(data))
        self.assertEqual(data[12:24], b'linkRGB RGB ')
        self.assertEqual(data[36:40], b'acsp')
        self.assertTrue(self.tag(data, b'desc').startswith(b'desc'))
        self.assertTrue(self.tag(data, b'cprt').startswith(b'text'))

    def test_clut_channel_order_and_identity_curves(self):
        table = self.tag(compile_profile(self.cube), b'A2B0')
        self.assertEqual(table[:4], b'mft2')
        self.assertEqual(table[8:12], bytes((3, 3, 2, 0)))
        self.assertEqual(struct.unpack_from('>HH', table, 48), (2, 2))
        self.assertEqual(struct.unpack_from('>6H', table, 52), (0, 65535, 0, 65535, 0, 65535))
        expected = [v * 65535 for r in range(2) for g in range(2) for b in range(2) for v in (r, g, b)]
        self.assertEqual(list(struct.unpack_from('>24H', table, 64)), expected)
        self.assertEqual(struct.unpack_from('>6H', table, 112), (0, 65535, 0, 65535, 0, 65535))

    def test_domain_is_encoded_in_input_curves(self):
        self.cube.write_text('DOMAIN_MIN 0 0.25 -1\nDOMAIN_MAX 2 0.75 1\n' + self.cube.read_text(), encoding='utf-8')
        table = self.tag(compile_profile(self.cube), b'A2B0')
        self.assertEqual(struct.unpack_from('>HH', table, 48), (4096, 2))
        self.assertEqual(struct.unpack_from('>H', table, 52 + 4095 * 2)[0], 32768)
        self.assertEqual(struct.unpack_from('>H', table, 52 + 4096 * 2)[0], 0)
        self.assertEqual(struct.unpack_from('>H', table, 52 + 8192 * 2)[0], 32768)

    def test_invalid_domains_are_rejected(self):
        original = self.cube.read_text()
        for domain in ('DOMAIN_MAX 0 1 1', 'DOMAIN_MIN nan 0 0', 'DOMAIN_MIN 2 0 0', 'DOMAIN_MIN 0 0 0\nDOMAIN_MIN 0 0 0'):
            self.cube.write_text(domain + '\n' + original, encoding='utf-8')
            with self.assertRaises(ValueError):
                validate(self.cube)

    def test_old_selection_upgrades_and_corrupt_profile_regenerates(self):
        selection = {'kind': 'cube', 'path': str(self.cube), 'name': 'Identity'}
        prepared = prepare_lut(selection, self.root)
        self.assertNotIn('profile', selection)
        profile = Path(prepared['profile'])
        self.assertEqual(profile.parent, self.root / 'lut-profiles')
        original = profile.read_bytes()
        self.assertEqual(hashlib.sha256(original).hexdigest(), prepared['profile_sha256'])
        profile.write_bytes(b'corrupt')
        self.assertEqual(prepare_lut(prepared, self.root), prepared)
        self.assertEqual(profile.read_bytes(), original)
        profile.unlink()
        self.assertEqual(prepare_lut(prepared, self.root), prepared)

    def test_changed_source_is_rejected(self):
        prepared = prepare_lut({'kind': 'cube', 'path': str(self.cube)}, self.root)
        self.cube.write_text(self.cube.read_text() + '\n# changed\n')
        with self.assertRaises(ValueError):
            prepare_lut(prepared, self.root)

    def test_xmp_and_disabled_lut_do_not_generate_profiles(self):
        self.assertIsNone(prepare_lut(None, self.root))
        selection = {'kind': 'xmp', 'path': 'not-read.xmp'}
        self.assertEqual(prepare_lut(selection, self.root), selection)
        self.assertFalse((self.root / 'lut-profiles').exists())


if __name__ == '__main__':
    unittest.main()
