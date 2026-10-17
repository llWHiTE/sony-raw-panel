"""Engine-specific development profiles; proprietary Adobe profiles stay installed locally."""
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET

DEFAULT = 'camera_standard'
ADOBE = {
    DEFAULT: 'Camera Standard',
    'adobe_color': 'Adobe Color',
    'adobe_standard': 'Adobe Standard',
    'adobe_portrait': 'Adobe Portrait',
    'camera_pt': 'Camera PT',
    'camera_vv': 'Camera VV',
}
SONY = {DEFAULT: 'Camera Standard'}
CRS = 'http://ns.adobe.com/camera-raw-settings/1.0/'
RDF = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'


def preference(value, engine):
    if not isinstance(value, str) or len(value) > 200:
        return DEFAULT
    values = ADOBE if engine == 'adobe' else SONY
    prefixes = ('dcp:', 'look:') if engine == 'adobe' else ('sony:',)
    return value if value in values or value.startswith(prefixes) else DEFAULT


def adobe_roots():
    return [Path(os.environ.get('PROGRAMDATA', 'C:/ProgramData')) / 'Adobe/CameraRaw',
            Path(os.environ.get('APPDATA', str(Path.home() / 'AppData/Roaming'))) / 'Adobe/CameraRaw']


def available_adobe(source, roots=None):
    from raw_dimensions import camera_model
    model = camera_model(source)
    roots = list(adobe_roots() if roots is None else roots)
    prefix = 'Sony ' + model
    result = []
    seen = set()
    aliases = {'Camera ST': DEFAULT, 'Camera Standard': DEFAULT, 'Camera PT': 'camera_pt',
               'Camera Portrait': 'camera_pt', 'Camera VV': 'camera_vv', 'Camera Vivid': 'camera_vv'}
    for root in roots:
        for path in sorted((root / 'CameraProfiles/Camera' / prefix).glob(prefix + ' *.dcp')):
            name = path.stem[len(prefix) + 1:]
            ident = aliases.get(name, 'dcp:' + name)
            if ident not in seen:
                result.append(dict(id=ident, label=name, model=model, camera_profile=name))
                seen.add(ident)
    standard = any((root / 'CameraProfiles/Adobe Standard' / (prefix + ' Adobe Standard.dcp')).is_file() for root in roots)
    if standard:
        result.append(dict(id='adobe_standard', label='Adobe Standard', model=model, camera_profile='Adobe Standard'))
        from lut_library import xmp_tree
        for root in roots:
            for path in sorted((root / 'Settings/Adobe/Profiles/Adobe Raw').glob('*.xmp')):
                try:
                    _, description = xmp_tree(path)
                    restriction = description.get('{' + CRS + '}CameraModelRestriction', '')
                    if restriction and restriction not in (model, prefix):
                        continue
                    name = path.stem
                    ident = next((key for key, label in ADOBE.items() if label == name), 'look:' + name)
                    uuid = description.get('{' + CRS + '}UUID', '')
                    if ident in seen or not re.fullmatch(r'[A-Fa-f0-9]{32}', uuid):
                        continue
                    if description.get('{' + CRS + '}CameraProfile', 'Adobe Standard') != 'Adobe Standard':
                        continue
                    result.append(dict(id=ident, label=name, model=model, camera_profile='Adobe Standard',
                                       look_name=name, look_uuid=uuid, profile_path=str(path)))
                    seen.add(ident)
                except (OSError, ValueError, ET.ParseError):
                    continue
    priority = [DEFAULT, 'adobe_color', 'adobe_standard', 'adobe_portrait', 'camera_pt', 'camera_vv']
    return sorted(result, key=lambda item: (priority.index(item['id']) if item['id'] in priority else len(priority), item['label']))


def resolve_adobe(source, profile=DEFAULT, roots=None):
    for item in available_adobe(source, roots):
        if item['id'] == profile:
            return item
    raise ValueError('Camera Raw: выбранный профиль не установлен для этой камеры: ' + str(profile))


def restore_adobe_profile(raw, baseline):
    """Restore only the frozen profile/Look, retaining the new preset's adjustments."""
    from lut_library import xmp_tree
    root, target = xmp_tree(Path(raw).with_suffix('.xmp'))
    _, source = xmp_tree(baseline)
    def is_profile(key):
        return key.startswith('{' + CRS + '}') and key.split('}')[-1].startswith(('CameraProfile', 'Look', 'Table_'))
    for key in list(target.attrib):
        if is_profile(key):
            del target.attrib[key]
    for key, value in source.attrib.items():
        if is_profile(key):
            target.set(key, value)
    for child in list(target):
        if child.tag == '{' + CRS + '}Look':
            target.remove(child)
    for child in source:
        if child.tag == '{' + CRS + '}Look':
            target.append(ET.fromstring(ET.tostring(child)))
    ET.register_namespace('crs', CRS)
    ET.register_namespace('rdf', RDF)
    Path(raw).with_suffix('.xmp').write_bytes(ET.tostring(root, encoding='utf-8', xml_declaration=True))


def apply_adobe_profile(raw, resolved):
    """The explicit profile wins over a preset's competing camera profile/Look."""
    from lut_library import xmp_tree
    root, description = xmp_tree(Path(raw).with_suffix('.xmp'))
    for key in list(description.attrib):
        if not key.startswith('{' + CRS + '}'):
            continue
        local = key.split('}')[-1]
        if local.startswith(('CameraProfile', 'Look', 'Table_')):
            del description.attrib[key]
    for child in list(description):
        if child.tag == '{' + CRS + '}Look':
            description.remove(child)
    description.set('{' + CRS + '}CameraProfile', resolved['camera_profile'])
    if resolved.get('look_name'):
        look = ET.SubElement(description, '{' + CRS + '}Look')
        look_description = ET.SubElement(look, '{' + RDF + '}Description', {
            '{' + CRS + '}Name': resolved['look_name'],
            '{' + CRS + '}UUID': resolved['look_uuid'],
            '{' + CRS + '}Amount': '1.000000',
            '{' + CRS + '}Stubbed': 'false',
            '{' + CRS + '}SupportsAmount': 'false',
            '{' + CRS + '}SupportsMonochrome': 'false',
            '{' + CRS + '}SupportsOutputReferred': 'false',
        })
        _, installed = xmp_tree(resolved['profile_path'])
        excluded = {'PresetType', 'Cluster', 'UUID', 'SupportsAmount', 'SupportsColor', 'SupportsMonochrome',
                    'SupportsHighDynamicRange', 'SupportsNormalDynamicRange', 'SupportsSceneReferred',
                    'SupportsOutputReferred', 'CameraModelRestriction', 'Copyright', 'ContactInfo', 'HasSettings'}
        parameters = ET.SubElement(ET.SubElement(look_description, '{' + CRS + '}Parameters'), '{' + RDF + '}Description')
        for key, value in installed.attrib.items():
            if key.startswith('{' + CRS + '}') and key.split('}')[-1] not in excluded:
                parameters.set(key, value)
        for child in installed:
            if child.tag.startswith('{' + CRS + '}ToneCurve'):
                parameters.append(ET.fromstring(ET.tostring(child)))
    ET.register_namespace('crs', CRS)
    ET.register_namespace('rdf', RDF)
    Path(raw).with_suffix('.xmp').write_bytes(ET.tostring(root, encoding='utf-8', xml_declaration=True))
