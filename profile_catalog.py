"""Metadata-only camera catalogs. Never starts or opens images in a renderer."""
import json
from pathlib import Path
import time
import uuid

from development_profiles import DEFAULT, available_adobe, adobe_roots
from raw_dimensions import camera_model


def load(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save(path, value):
    path = Path(path)
    path.parent.mkdir(exist_ok=True, parents=True)
    temporary = path.parent / (uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def sony_options(rows):
    return [dict(id=DEFAULT if code == 2 else 'sony:' + str(code), label=label, code=code) for code, label in rows]


def remember_sony(source, root, options):
    model = camera_model(source)
    path = Path(root) / 'sony-profile-cache.json'
    cache = load(path)
    cache[model] = dict(options=options, updated=time.time())
    save(path, cache)


def stamp(source, roots):
    model = camera_model(source)
    signature = []
    for root in roots:
        for folder in (root / 'CameraProfiles/Camera' / ('Sony ' + model),
                       root / 'CameraProfiles/Adobe Standard', root / 'Settings/Adobe/Profiles/Adobe Raw'):
            if folder.is_dir():
                signature.extend((str(path), path.stat().st_mtime_ns, path.stat().st_size)
                                 for path in sorted(folder.iterdir()) if path.is_file())
    return signature


def catalog(source, root, bundle, roots=None, refresh=False):
    started = time.monotonic()
    source = Path(source).resolve(strict=True)
    model = camera_model(source)
    roots = list(adobe_roots() if roots is None else roots)
    path = Path(root) / 'adobe-profile-cache.json'
    cache = load(path)
    signature = [list(row) for row in stamp(source, roots)]
    record = cache.get(model, {})
    cached = not refresh and record.get('signature') == signature and isinstance(record.get('options'), list)
    adobe = record['options'] if cached else available_adobe(source, roots)
    if not cached:
        cache[model] = dict(signature=signature, options=adobe)
        save(path, cache)
    observed = load(Path(root) / 'sony-profile-cache.json').get(model, {})
    sony = observed.get('options')
    origin = 'Sony Creative Style / Look (кэш)'
    if not sony:
        seed = load(Path(bundle) / 'sony-profile-catalog.json').get('models', {}).get(model)
        sony = sony_options(seed) if seed else [dict(id=DEFAULT, label='Camera Standard', code=2)]
        origin = 'Проверенный каталог Sony' if seed else 'Список Sony уточнится при первой проявке, без дополнительного открытия'
    return dict(source=str(source), model=model, adobe=adobe, sony=sony, sony_origin=origin,
                cached=cached, seconds=round(time.monotonic() - started, 4))
