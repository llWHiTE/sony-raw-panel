"""Read the usable image dimensions from each Sony ARW's TIFF/Exif metadata."""
import struct
import re


def camera_model(path):
    with open(path, 'rb') as file:
        file.seek(0, 2)
        size = file.tell()
        def read(offset, length):
            if offset < 0 or length < 0 or offset + length > size:
                raise ValueError('Повреждены метаданные модели ARW.')
            file.seek(offset)
            value = file.read(length)
            if len(value) != length:
                raise ValueError('Не удалось прочитать модель камеры.')
            return value
        header = read(0, 8)
        if header[:2] not in (b'II', b'MM'):
            raise ValueError('Файл ARW не содержит TIFF-метаданные.')
        endian = '<' if header[:2] == b'II' else '>'
        magic, offset = struct.unpack(endian + 'HI', header[2:])
        if magic != 42:
            raise ValueError('Неподдерживаемые метаданные ARW.')
        count = struct.unpack(endian + 'H', read(offset, 2))[0]
        if count > 4096:
            raise ValueError('Слишком большой каталог ARW.')
        entries = read(offset + 2, count * 12)
        models = []
        for i in range(count):
            entry = entries[i * 12:(i + 1) * 12]
            tag, kind, length = struct.unpack(endian + 'HHI', entry[:8])
            if tag != 272:
                continue
            if kind != 2 or not 2 <= length <= 128:
                raise ValueError('Неверная модель камеры в ARW.')
            data = entry[8:8 + length] if length <= 4 else read(struct.unpack(endian + 'I', entry[8:])[0], length)
            value = data.rstrip(b'\0').decode('ascii').strip()
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _-]{0,100}', value):
                raise ValueError('Неверная модель камеры в ARW.')
            models.append(value)
        if len(models) == 1:
            return models[0]
    raise ValueError('В ARW не найдена однозначная модель камеры.')


def image_size(path, oriented=False):
    with open(path, 'rb') as file:
        file.seek(0, 2)
        size = file.tell()

        def read(offset, length):
            if offset < 0 or length < 0 or offset + length > size:
                raise ValueError('Повреждены метаданные размеров ARW.')
            file.seek(offset)
            data = file.read(length)
            if len(data) != length:
                raise ValueError('Не удалось прочитать размеры ARW.')
            return data

        header = read(0, 8)
        if header[:2] not in (b'II', b'MM'):
            raise ValueError('Файл ARW не содержит ожидаемые TIFF-метаданные.')
        endian = '<' if header[:2] == b'II' else '>'
        if struct.unpack(endian + 'H', header[2:4])[0] != 42:
            raise ValueError('Неподдерживаемый формат метаданных ARW.')

        def directory(offset):
            count = struct.unpack(endian + 'H', read(offset, 2))[0]
            if count > 4096:
                raise ValueError('Слишком большой каталог метаданных ARW.')
            entries = read(offset + 2, count * 12)
            result = {}
            for i in range(count):
                entry = entries[i * 12:(i + 1) * 12]
                tag, kind, count_values = struct.unpack(endian + 'HHI', entry[:8])
                if tag not in (274, 330, 34665, 40962, 40963, 50720):
                    continue
                if kind not in (3, 4) or not 1 <= count_values <= 16:
                    continue
                length = count_values * (2 if kind == 3 else 4)
                data = entry[8:8 + length] if length <= 4 else read(struct.unpack(endian + 'I', entry[8:])[0], length)
                result[tag] = struct.unpack(endian + str(count_values) + ('H' if kind == 3 else 'I'), data)
            return result

        first = directory(struct.unpack(endian + 'I', header[4:])[0])
        orientation = first.get(274, (1,))[0]
        if orientation not in range(1, 9):
            raise ValueError('Неподдерживаемая ориентация ARW.')
        def display(dimensions):
            return tuple(reversed(dimensions)) if oriented and orientation in (5, 6, 7, 8) else tuple(dimensions)
        if first.get(34665):
            exif = directory(first[34665][0])
            if exif.get(40962) and exif.get(40963):
                dimensions = exif[40962][0], exif[40963][0]
                if all(0 < value <= 100000 for value in dimensions):
                    return display(dimensions)
        for offset in first.get(330, ()):
            crop = directory(offset).get(50720)
            if crop and len(crop) == 2 and all(0 < value <= 100000 for value in crop):
                return display(crop)
    raise ValueError('В ARW не найдены размеры исходного изображения. Предпросмотр не создан: размер другой камеры не будет использован.')
