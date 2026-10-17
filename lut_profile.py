"""Compile CUBE tables into embedded RGB device-link profiles for Color Lookup.

Photoshop stores the CUBE text for editing, but renders the binary ICC `profile`.
ICC CLUT order is blue-fastest; CUBE file order is red-fastest.
"""
import math
from pathlib import Path
import struct


VERSION = 1


def read_cube(path):
    size = None
    rows = []
    domains = {'DOMAIN_MIN': (0., 0., 0.), 'DOMAIN_MAX': (1., 1., 1.)}
    seen = set()
    for raw in Path(path).read_text(encoding='utf-8-sig').splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line or line.startswith('TITLE '):
            continue
        parts = line.split()
        if parts[0] == 'LUT_3D_SIZE':
            if size is not None or len(parts) != 2:
                raise ValueError('Неверный LUT_3D_SIZE.')
            size = int(parts[1])
            if not 2 <= size <= 128:
                raise ValueError('Поддерживается 3D LUT размером 2–128.')
        elif parts[0] in domains:
            if parts[0] in seen or len(parts) != 4:
                raise ValueError('Неверный диапазон LUT.')
            seen.add(parts[0])
            domains[parts[0]] = tuple(float(v) for v in parts[1:])
        else:
            if len(parts) != 3:
                raise ValueError('Поддерживаются трёхмерные .cube LUT.')
            row = tuple(float(v) for v in parts)
            if not all(math.isfinite(v) for v in row):
                raise ValueError('Неверные значения LUT.')
            rows.append(row)
    low, high = domains['DOMAIN_MIN'], domains['DOMAIN_MAX']
    if not all(math.isfinite(a) and math.isfinite(b) and a < b for a, b in zip(low, high)):
        raise ValueError('DOMAIN_MAX должен быть больше DOMAIN_MIN.')
    if size is None or len(rows) != size ** 3:
        raise ValueError('Число строк не соответствует размеру 3D LUT.')
    return size, rows, low, high


def u16(value):
    return round(max(0., min(1., value)) * 65535)


def compile_profile(path):
    size, rows, low, high = read_cube(path)
    input_count = 2 if low == (0., 0., 0.) and high == (1., 1., 1.) else 4096
    matrix = struct.pack('>9i', 65536, 0, 0, 0, 65536, 0, 0, 0, 65536)
    table = bytearray(b'mft2' + bytes(4) + bytes((3, 3, size, 0)) + matrix + struct.pack('>HH', input_count, 2))
    for a, b in zip(low, high):
        table.extend(struct.pack('>%dH' % input_count, *(u16((i / (input_count - 1) - a) / (b - a)) for i in range(input_count))))
    for r in range(size):
        for g in range(size):
            for b in range(size):
                values = rows[r + size * (g + size * b)]
                table.extend(struct.pack('>3H', *(u16(v) for v in values)))
    table.extend(struct.pack('>6H', 0, 65535, 0, 65535, 0, 65535))

    description = b'Sony RAW Panel CUBE\0'
    desc = b'desc' + bytes(4) + struct.pack('>I', len(description)) + description + bytes(8 + 2 + 1 + 67)
    tags = [(b'desc', desc), (b'cprt', b'text' + bytes(4) + b'User-supplied LUT; original rights retained.\0'),
            (b'pseq', b'pseq' + bytes(8)), (b'A2B0', bytes(table))]
    offset = 128 + 4 + len(tags) * 12
    directory = bytearray(struct.pack('>I', len(tags)))
    contents = bytearray()
    for signature, data in tags:
        directory.extend(struct.pack('>4sII', signature, offset + len(contents), len(data)))
        contents.extend(data)
        contents.extend(bytes((-len(contents)) % 4))
    header = bytearray(128)
    struct.pack_into('>I', header, 0, offset + len(contents))
    header[8:12] = bytes((2, 0x10, 0, 0))
    header[12:24] = b'linkRGB RGB '
    struct.pack_into('>6H', header, 24, 2026, 1, 1, 0, 0, 0)
    header[36:40] = b'acsp'
    struct.pack_into('>3i', header, 68, 63190, 65536, 54061)
    return bytes(header + directory + contents)
