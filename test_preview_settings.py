from pathlib import Path
import struct
import tempfile
import unittest

import preview_settings as preview
from raw_dimensions import image_size


def raw_fixture(width, height, endian='<'):
    header = (b'II' if endian == '<' else b'MM') + struct.pack(endian + 'HI', 42, 8)
    root = struct.pack(endian + 'H', 1) + struct.pack(endian + 'HHII', 34665, 4, 1, 26) + bytes(4)
    exif = struct.pack(endian + 'H', 2)
    exif += struct.pack(endian + 'HHII', 40962, 4, 1, width)
    exif += struct.pack(endian + 'HHII', 40963, 4, 1, height)
    return header + root + exif + bytes(4)


class PercentTests(unittest.TestCase):
    def test_custom_percent_and_rounding(self):
        self.assertEqual(preview.scaled_size(6001,4001,33), (1980,1320))
        self.assertEqual(preview.scaled_size(1,1,1), (1,1))
        self.assertEqual(preview.validate_percent('35'),35)

    def test_invalid_percent_is_rejected(self):
        for value in (0,101,-1,False,True,3.5,'abc',None,float('inf'),float('nan')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                preview.validate_percent(value)

    def test_custom_preferences_survive_reload(self):
        self.assertEqual(preview.preferences(dict(preview_percent=33,custom_percent=33,preview_mode='custom')), (33,33,'custom'))
        self.assertEqual(preview.preferences(dict(preview_percent=50,custom_percent=35)), (50,35,'preset'))
        self.assertEqual(preview.preferences(dict(preview_percent=75,preview_mode='custom')), (75,75,'custom'))

    def test_corrupt_and_old_preferences_have_safe_defaults(self):
        self.assertEqual(preview.preferences(None),(50,35,'preset'))
        self.assertEqual(preview.preferences(dict(preview_percent='broken',custom_percent=-3)),(50,35,'preset'))
        self.assertEqual(preview.preferences(dict(preview_size='Полное разрешение'))[0],100)
        self.assertEqual(preview.preferences(dict(preview_size='Детальнее · 3000 px'))[0],75)


class RawDimensionsTests(unittest.TestCase):
    def test_dimensions_are_read_from_each_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'camera.ARW'
            for width,height in ((9504,6336),(6000,4000),(8640,5760)):
                for endian in ('<','>'):
                    path.write_bytes(raw_fixture(width,height,endian))
                    self.assertEqual(image_size(path),(width,height))
                    self.assertEqual(preview.scaled_size(*image_size(path),50),(width//2,height//2))

    def test_orientation_swaps_only_display_dimensions(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'portrait.ARW'
            for endian in ('<','>'):
                for orientation in range(1,9):
                    header=(b'II' if endian=='<' else b'MM')+struct.pack(endian+'HI',42,8)
                    root=struct.pack(endian+'H',2)
                    root+=struct.pack(endian+'HHI',274,3,1)+struct.pack(endian+'H',orientation)+bytes(2)
                    root+=struct.pack(endian+'HHII',34665,4,1,38)+bytes(4)
                    exif=raw_fixture(7952,5304,endian)[26:]
                    path.write_bytes(header+root+exif)
                    expected=(5304,7952) if orientation in (5,6,7,8) else (7952,5304)
                    self.assertEqual(image_size(path,oriented=True),expected)
                    self.assertEqual(image_size(path),(7952,5304))
                    self.assertEqual(preview.scaled_size(*image_size(path,oriented=True),50),tuple(v//2 for v in expected))

    def test_missing_dimensions_do_not_reuse_another_camera(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'unknown.ARW'
            path.write_bytes(b'II'+struct.pack('<HIH',42,8,0)+bytes(4))
            with self.assertRaises(ValueError):image_size(path)

    def test_invalid_offsets_and_truncation_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'bad.ARW'
            for data in (b'bad', b'II'+struct.pack('<HI',42,9000),raw_fixture(6000,4000)[:30],raw_fixture(0,4000)):
                path.write_bytes(data)
                with self.assertRaises(ValueError):image_size(path)


if __name__ == '__main__':
    unittest.main()
