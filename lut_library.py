"""User-editable local CUBE library; selected LUTs are snapshotted per operation."""
import hashlib
import uuid
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

CRS = 'http://ns.adobe.com/camera-raw-settings/1.0/'
RDF = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'


def xmp_tree(path):
    data = Path(path).read_bytes()
    if len(data) > 32 * 1024 * 1024 or b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('Небезопасный или слишком большой XMP.')
    root = ET.fromstring(data)
    description = root.find('.//{' + RDF + '}Description')
    if description is None or not any(k.startswith('{' + CRS + '}') for k in description.attrib):
        raise ValueError('XMP не содержит настроек Camera Raw.')
    return root, description


def apply_xmp(raw, selection):
    if not selection or selection.get('kind') != 'xmp':
        return 'Camera ST'
    root, target = xmp_tree(Path(raw).with_suffix('.xmp'))
    _, source = xmp_tree(selection['path'])
    for key, value in source.attrib.items():
        if key.startswith('{' + CRS + '}'):
            target.set(key, value)
    for child in list(source):
        if child.tag.startswith('{' + CRS + '}'):
            for existing in list(target):
                if existing.tag == child.tag:
                    target.remove(existing)
            target.append(ET.fromstring(ET.tostring(child)))
    for key in list(target.attrib):
        local = key.split('}')[-1]
        if local.startswith('Crop') or local in ('Orientation',):
            del target.attrib[key]
    target.set('{' + CRS + '}HasCrop', 'False')
    target.set('{' + CRS + '}HasSettings', 'True')
    ET.register_namespace('crs', CRS)
    ET.register_namespace('rdf', RDF)
    root_path = Path(raw).with_suffix('.xmp')
    root_path.write_bytes(ET.tostring(root, encoding='utf-8', xml_declaration=True))
    return target.get('{' + CRS + '}CameraProfile', 'Camera ST')


def validate(path):
    path = Path(path)
    if path.suffix.lower() not in ('.cube', '.xmp') or not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError('Выберите .cube или .xmp размером до 32 МБ.')
    if path.suffix.lower() == '.xmp':
        xmp_tree(path)
        return hashlib.sha256(path.read_bytes()).hexdigest()
    from lut_profile import read_cube
    read_cube(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_lut(selection, root):
    if not selection or selection.get('kind') != 'cube':
        return selection
    from lut_profile import compile_profile, VERSION
    path = Path(selection['path'])
    digest = validate(path)
    if selection.get('sha256') and selection['sha256'] != digest:
        raise ValueError('Сохранённая копия LUT повреждена.')
    folder = Path(root) / 'lut-profiles'
    folder.mkdir(exist_ok=True)
    profile = folder / ('%s-v%d.icc' % (digest, VERSION))
    # Reuse only a verified profile; old sessions without one are upgraded here.
    expected = selection.get('profile_sha256')
    if not expected or not profile.is_file() or hashlib.sha256(profile.read_bytes()).hexdigest() != expected:
        contents = compile_profile(path)
        temporary = folder / (uuid.uuid4().hex + '.tmp')
        try:
            temporary.write_bytes(contents)
            temporary.replace(profile)
        finally:
            temporary.unlink(missing_ok=True)
        expected = hashlib.sha256(contents).hexdigest()
    return dict(selection, profile=str(profile), profile_sha256=expected, sha256=digest)


class Library:
    def __init__(self, root, bundle):
        self.root = Path(root)
        self.directory = self.root / 'luts'
        self.directory.mkdir(exist_ok=True)
        marker = self.directory / '.initialized'
        if not marker.exists():
            for path in sorted((Path(bundle) / 'bundled-luts').glob('*')):
                self.add(path)
            marker.write_text('Initial library imported; removals are persistent.\n', encoding='utf-8')

    def entries(self):
        return sorted((p for p in self.directory.iterdir() if p.suffix.lower() in ('.cube', '.xmp') and p.is_file()), key=lambda p: p.name.casefold())

    def add(self, source):
        source = Path(source)
        validate(source)
        name = source.stem
        target = self.directory / (name + source.suffix.lower())
        index = 2
        while target.exists():
            if target.read_bytes() == source.read_bytes():
                return target
            target = self.directory / ('%s (%d)%s' % (name, index, source.suffix.lower()))
            index += 1
        shutil.copy2(source, target)
        return target

    def remove(self, path):
        path = Path(path)
        if path.parent != self.directory or path.is_symlink():
            raise ValueError('Удалять можно только LUT из библиотеки панели.')
        path.unlink()

    def snapshot(self, path):
        path = Path(path)
        if path.parent != self.directory or path.is_symlink():
            raise ValueError('Выберите LUT из библиотеки панели.')
        digest = validate(path)
        folder = self.root / 'lut-snapshots'
        folder.mkdir(exist_ok=True)
        target = folder / (digest + path.suffix.lower())
        if not target.exists():
            shutil.copy2(path, target)
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError('Сохранённая копия LUT повреждена.')
        return prepare_lut(dict(path=str(target), name=path.stem, sha256=digest, kind=path.suffix.lower().lstrip('.')), self.root)
