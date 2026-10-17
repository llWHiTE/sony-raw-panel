import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('bridge', ROOT / 'bridge.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def fixture(endian):
    tags = []
    payload = bytearray()
    count = 11
    start = 8 + 2 + 12 * count + 4

    def tag(number, kind, values):
        if kind == 2:
            data = values
            n = len(values)
        else:
            n = len(values)
            data = struct.pack(endian + str(n) + ('H' if kind == 3 else 'I'), *values)
        if len(data) <= 4:
            value = data.ljust(4, b'\0')
        else:
            value = struct.pack(endian + 'I', start + len(payload))
            payload.extend(data)
        tags.append(struct.pack(endian + 'HHI', number, kind, n) + value)

    tag(256, 4, [1])
    tag(257, 4, [1])
    tag(258, 3, [16, 16, 16])
    tag(259, 3, [1])
    tag(262, 3, [2])
    tag(274, 3, [1])
    tag(277, 3, [3])
    tag(278, 4, [1])
    tag(279, 4, [6])
    tag(305, 2, b'Edit 4.0.00.10311\0')
    tag(273, 4, [start + len(payload)])
    payload.extend(struct.pack(endian + 'HHH', 123, 456, 789))
    tags.sort(key=lambda e: struct.unpack(endian + 'H', e[:2])[0])
    return (b'II' if endian == '<' else b'MM') + struct.pack(endian + 'HIH', 42, 8, count) + b''.join(tags) + b'\0' * 4 + payload


class BridgeTests(unittest.TestCase):
    def test_profile_embedding_preserves_existing_payload(self):
        for endian in ('<', '>'):
            with self.subTest(endian=endian), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'test.tif'
                before = fixture(endian)
                path.write_bytes(before)
                tags_before = bridge.tiff_info(path)
                tags_after = bridge.embed_srgb(path)
                after = path.read_bytes()
                self.assertEqual(before[:4], after[:4])
                self.assertEqual(before[8:], after[8:len(before)])
                self.assertEqual(tags_before, {k: v for k, v in tags_after.items() if k != 34675})
                self.assertEqual(tags_after[34675]['bytes'], 3144)
                with self.assertRaises(ValueError):
                    bridge.embed_srgb(path)

    def test_invalid_image_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'invalid.tif'
            path.write_bytes(b'not a tiff')
            with self.assertRaises(ValueError):
                bridge.tiff_info(path)


if __name__ == '__main__':
    unittest.main()
