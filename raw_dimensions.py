"""Read the usable image dimensions from each Sony ARW's TIFF/Exif metadata."""
import struct


def image_size(path):
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
                if tag not in (330, 34665, 40962, 40963, 50720):
                    continue
                if kind not in (3, 4) or not 1 <= count_values <= 16:
                    continue
                length = count_values * (2 if kind == 3 else 4)
                data = entry[8:8 + length] if length <= 4 else read(struct.unpack(endian + 'I', entry[8:])[0], length)
                result[tag] = struct.unpack(endian + str(count_values) + ('H' if kind == 3 else 'I'), data)
            return result

        first = directory(struct.unpack(endian + 'I', header[4:])[0])
        if first.get(34665):
            exif = directory(first[34665][0])
            if exif.get(40962) and exif.get(40963):
                dimensions = exif[40962][0], exif[40963][0]
                if all(0 < value <= 100000 for value in dimensions):
                    return dimensions
        for offset in first.get(330, ()):
            crop = directory(offset).get(50720)
            if crop and len(crop) == 2 and all(0 < value <= 100000 for value in crop):
                return crop
    raise ValueError('В ARW не найдены размеры исходного изображения. Предпросмотр не создан: размер другой камеры не будет использован.')
