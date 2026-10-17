import argparse
import ctypes as C
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import traceback
import uuid
import xml.etree.ElementTree as ET

SOURCE = Path(__file__).resolve().parent
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))
import runtime_paths as runtime
ROOT = runtime.data_root()
BUNDLE = runtime.bundle_root()
spec = importlib.util.spec_from_file_location('bridge_v1', BUNDLE / 'bridge.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
w = base.w
PROJECTS = ROOT / 'projects'
CACHE = ROOT / 'cache-v2'
ID = re.compile(r'^[a-f0-9]{32}$')


def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def checked_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError('Invalid project or render identifier.')
    return value


def child(root, ident):
    path = root / checked_id(ident)
    if path.resolve() != path.absolute() or root.resolve() != root.absolute():
        raise ValueError('Redirected project/cache folders are not supported.')
    return path


def project(ident):
    folder = child(PROJECTS, ident)
    data = json.loads((folder / 'project.json').read_text(encoding='utf-8'))
    if data.get('id') != ident or data.get('version') != 2:
        raise ValueError('Invalid Sony RAW project.')
    return folder, data


def settings_path(folder, data, revision=None):
    name = ('settings-' + checked_id(revision) + '.xml') if revision else data.get('settings')
    if not name:
        return None
    if not re.fullmatch(r'settings-[a-f0-9]{32}\.xml', name):
        raise ValueError('Invalid Sony recipe name.')
    expected = data.get('recipes', {}).get(name)
    if not expected and name == data.get('settings'):
        expected = data.get('settings_sha256')
    path = folder / name
    if not expected or path.resolve().parent != folder.resolve() or base.sha(path) != expected:
        raise ValueError('Sony settings file changed or its saved version is missing.')
    return path


def snapshot_recipe(sony, folder, data, token=None):
    token = token or uuid.uuid4().hex
    recipe = folder / ('settings-' + token + '.xml')
    sony.save_settings(recipe, 'SonyRAW-' + data['id'] + '.ARW')
    tree = ET.parse(recipe)
    if not any(e.text == 'DevelopmentParameters' for e in tree.iter('key')):
        raise ValueError('Sony did not save a development recipe.')
    elements = list(tree.iter())
    code = next((elements[i + 1].text for i, element in enumerate(elements[:-1]) if element.tag == 'key' and element.text == 'ColorModeByNum'), None)
    selected = next((item for item in data.get('sony_options', []) if str(item['code']) == code), None)
    if selected:
        data['sony_profile'] = selected
    elif code is not None:
        data['sony_profile'] = dict(id='camera_standard' if code == '2' else 'sony:' + code,
                                    code=int(code), label='Camera Standard' if code == '2' else 'Sony ' + code)
    data['settings'] = recipe.name
    data['settings_sha256'] = base.sha(recipe)
    data.setdefault('recipes', {})[recipe.name] = data['settings_sha256']
    atomic_json(folder / 'project.json', data)
    return recipe


def checkpoint_other(sony, target, active_name):
    name = active_name or ''
    match = re.fullmatch(r'SonyRAW-([a-f0-9]{32})\.ARW', name)
    if match and match[1] != target and (PROJECTS / match[1] / 'project.json').is_file():
        folder, data = project(match[1])
        snapshot_recipe(sony, folder, data)


class Sony(base.Sony):
    def __init__(self):
        super().__init__()
        w.u.IsIconic.argtypes = [w.W.HWND]
        w.u.ShowWindow.argtypes = [w.W.HWND, C.c_int]
        w.u.SetForegroundWindow.argtypes = [w.W.HWND]
        if w.u.IsIconic(self.main):
            w.u.ShowWindow(self.main, 9)

    def active_name(self):
        labels = [h for h in w.windows(self.main) if w.u.GetDlgCtrlID(h) == 34101 and w.cls(h) == 'Static']
        names = [w.get_text(h).strip() for h in labels]
        names = [name for name in names if name]
        if len(names) == 1:
            return names[0].lstrip('*')
        if not names:
            return None
        # Every tab exposes 34101; only the settings dialog names the active document.
        dialog = self.command_dialog(37395)
        try:
            value = w.get_text(w.control(dialog, 1001, 'Edit'))
        finally:
            w.click(w.control(dialog, 2, 'Button'))
            self.finish_dialog(dialog, 15)
        name = Path(value).stem + '.ARW'
        return name if any(n.lstrip('*') == name for n in names) else None

    def require(self, name):
        self.ready()
        if self.active_name() != name:
            raise RuntimeError('Sony active RAW differs from the selected Photoshop project. Use Edit Sony RAW first; do not switch photos during export.')

    def check_dialog_source(self, dialog, field, expected_name):
        if Path(w.get_text(field)).stem != Path(expected_name).stem:
            w.click(w.control(dialog, 2, 'Button'))
            self.finish_dialog(dialog, 15)
            raise RuntimeError('Sony selected a different RAW. The operation was cancelled before writing anything.')

    def save_settings(self, destination, expected_name=None):
        dialog = self.command_dialog(37395)
        field = w.control(dialog, 1001, 'Edit')
        if expected_name:
            self.check_dialog_source(dialog, field, expected_name)
        w.set_text(field, str(destination))
        self.submit(dialog)
        self.finish_dialog(dialog, 30)
        w.wait(lambda: destination.is_file() and destination.stat().st_size > 0, 15, 'Sony settings XML was not created.')

    def export(self, destination, expected_name, dimensions=None):
        dialog = self.command_dialog(41217)
        self.check_dialog_source(dialog, w.control(dialog, 1148, 'Edit'), expected_name)
        self.navigate(dialog, destination.parent)
        w.select(w.control(dialog, 1136, 'ComboBox'), 1)
        bit = w.control(dialog, 1700, 'Button')
        w.wait(lambda: w.u.IsWindowEnabled(bit), 10, 'TIFF controls did not become ready.')
        w.click(bit)
        w.wait(lambda: w.send(bit, 0x00F0) == 1, 5, '16-bit output was not selected.')
        w.select(w.control(dialog, 1303, 'ComboBox'), 1)
        if dimensions:
            w.set_text(w.control(dialog, 1042, 'Edit'), str(dimensions[0]))
            w.set_text(w.control(dialog, 1037, 'Edit'), str(dimensions[1]))
        w.set_text(w.control(dialog, 1148, 'Edit'), destination.name)
        self.submit(dialog)
        self.finish_dialog(dialog, 300, allow_progress=True)
        return self.complete_tiff(destination)

    def complete_tiff(self, destination):
        w.k.CreateFileW.argtypes = [w.W.LPCWSTR, w.W.DWORD, w.W.DWORD, C.c_void_p, w.W.DWORD, w.W.DWORD, w.W.HANDLE]
        w.k.CreateFileW.restype = w.W.HANDLE
        def complete():
            # FILE_SHARE_READ excludes any writer; UI completion alone is insufficient.
            handle = w.k.CreateFileW(str(destination), 0x80000000, 1, None, 3, 0, None)
            if handle == C.c_void_p(-1).value:
                return False
            try:
                tags = base.tiff_info(destination)
                if tags.get(259) != [1] or destination.stat().st_size < tags[256][0] * tags[257][0] * 6:
                    raise ValueError('Incomplete or unexpected Sony TIFF.')
                return tags
            finally:
                w.k.CloseHandle(handle)
        tags = w.wait(complete, 300, 'Sony TIFF writer did not finish.')
        # The writer may close before Sony dismisses its final 100% progress dialog.
        self.ready(300, allow_progress=True)
        return tags

    def profiles(self, name):
        self.require(name)
        control = w.control(self.main, 1302, 'ComboBox')
        count = w.send(control, 0x0146)
        if not 2 <= count <= 256:
            raise RuntimeError('Sony: список Creative Style / Look недоступен.')
        result = []
        for index in range(1, count):
            text = C.create_unicode_buffer(1024)
            w.send(control, 0x0148, index, C.addressof(text))
            code = w.send(control, 0x0150, index)
            if not 0 < code < 65536 or not text.value:
                raise RuntimeError('Sony: неожиданный идентификатор творческого профиля.')
            result.append(dict(id='camera_standard' if code == 2 else 'sony:' + str(code),
                               label=text.value, code=code, index=index))
        return result

    def set_profile(self, name, profile, options=None):
        options = self.profiles(name) if options is None else options
        selected = next((item for item in options if item['id'] == profile), None)
        if selected is None:
            raise ValueError('Sony: выбранный стиль недоступен для этого RAW: ' + str(profile))
        control = w.control(self.main, 1302, 'ComboBox')
        w.select(control, selected['index'])
        self.ready()
        self.require(name)
        if w.send(control, 0x0150, w.send(control, 0x0147)) != selected['code']:
            raise RuntimeError('Sony не подтвердил выбранный профиль.')
        return selected

    def load_settings(self, path, name):
        self.require(name)
        dialog = self.command_dialog(37396)
        edits = [h for h in w.windows(dialog) if w.cls(h) == 'Edit' and w.u.GetDlgCtrlID(h) in (1001, 1148) and w.u.IsWindowVisible(h)]
        if len(edits) != 1:
            raise RuntimeError('Unexpected Sony settings-load dialog.')
        w.set_text(edits[0], str(path))
        self.submit(dialog)
        self.finish_dialog(dialog, 120, allow_progress=True)
        self.require(name)


def new_project(source):
    source = Path(source).resolve(strict=True)
    if not source.is_file() or source.suffix.lower() != '.arw':
        raise ValueError('Select an existing ARW.')
    if shutil.disk_usage(ROOT).free < source.stat().st_size + 1_200_000_000:
        raise RuntimeError('Not enough free disk space for RAW processing.')
    ident = uuid.uuid4().hex
    folder = child(PROJECTS, ident)
    folder.mkdir()
    stat = source.stat()
    digest = base.sha(source)
    from raw_dimensions import image_size
    dimensions = image_size(source, oriented=True)
    raw = folder / ('SonyRAW-' + ident + '.ARW')
    shutil.copy2(source, raw)
    if base.sha(raw) != digest or source.stat().st_mtime_ns != stat.st_mtime_ns:
        raise RuntimeError('RAW copy verification failed.')
    data = dict(version=2, id=ident, source=str(source), source_sha256=digest,
                source_size=stat.st_size, source_mtime_ns=stat.st_mtime_ns,
                raw_size=raw.stat().st_size, raw_mtime_ns=raw.stat().st_mtime_ns,
                settings=None, output_dimensions=list(dimensions), created=time.time())
    from render_cache import signature
    data['raw_signature'] = list(signature(raw))
    atomic_json(folder / 'project.json', data)
    return folder, data


def validate_raw(folder, data):
    raw = folder / ('SonyRAW-' + data['id'] + '.ARW')
    st = raw.stat()
    if raw.resolve() != raw.absolute() or st.st_nlink != 1:
        raise RuntimeError('Working RAW must be an independent regular copy, not a filesystem link.')
    if st.st_size != data['raw_size']:
        raise RuntimeError('Working RAW copy changed. Original is untouched; do not overwrite the project.')
    from render_cache import signature, digest
    current = list(signature(raw))
    if current != data.get('raw_signature'):
        if digest(raw) != data.get('source_sha256'):
            raise RuntimeError('Working RAW copy changed. Original is untouched; do not overwrite the project.')
        data['raw_signature'] = current
        data['raw_mtime_ns'] = st.st_mtime_ns
        atomic_json(folder / 'project.json', data)
    return raw


def activate(sony, folder, data, revision=None):
    raw = validate_raw(folder, data)
    current = sony.active_name()
    active = current == raw.name
    if active and (not revision or data.get('active_revision') == revision):
        return True
    recipe = settings_path(folder, data, revision)
    if active:
        snapshot_recipe(sony, folder, data)
    else:
        checkpoint_other(sony, data['id'], current)
        sony.open(raw)
        w.wait(lambda: sony.active_name() == raw.name, 15, 'Cannot identify the active Sony RAW safely.')
    if recipe:
        sony.load_settings(recipe, raw.name)
        data['active_revision'] = recipe.stem.removeprefix('settings-')
        data['settings'] = recipe.name
        data['settings_sha256'] = base.sha(recipe)
        atomic_json(folder / 'project.json', data)
    return False


def apply_profile(sony, folder, data, profile, recipe_token=None):
    from profile_catalog import remember_sony
    data['sony_options'] = sony.profiles('SonyRAW-' + data['id'] + '.ARW')
    remember_sony(validate_raw(folder, data), ROOT, data['sony_options'])
    selected = sony.set_profile('SonyRAW-' + data['id'] + '.ARW', profile, options=data['sony_options'])
    recipe = snapshot_recipe(sony, folder, data, recipe_token)
    root = ET.parse(recipe).getroot()
    values = list(root.iter())
    codes = [values[i + 1].text for i, value in enumerate(values[:-1]) if value.tag == 'key' and value.text == 'ColorModeByNum']
    if codes != [str(selected['code'])]:
        raise RuntimeError('Sony-рецепт не подтвердил выбранный профиль.')
    data['sony_profile'] = selected
    atomic_json(folder / 'project.json', data)
    return selected


def render(sony, folder, data, recipe=None):
    started = time.monotonic()
    ident = data['id']
    name = 'SonyRAW-' + ident + '.ARW'
    if shutil.disk_usage(CACHE).free < 900_000_000:
        raise RuntimeError('Not enough free disk space for TIFF export.')
    token = uuid.uuid4().hex
    job = child(CACHE, token)
    job.mkdir()
    state = dict(version=2, project=ident, token=token, status='rendering', created=time.time())
    atomic_json(job / 'job.json', state)
    if recipe is None:
        recipe = snapshot_recipe(sony, folder, data, token)
    else:
        destination = folder / ('settings-' + token + '.xml')
        shutil.copy2(recipe, destination)
        recipe = destination
        data['settings'] = recipe.name
        data['settings_sha256'] = base.sha(recipe)
        data.setdefault('recipes', {})[recipe.name] = data['settings_sha256']
    target = job / ('SonyRAW-' + ident + '-' + token + '.tif')
    sony.export(target, name, data.get('output_dimensions'))
    tags = base.embed_srgb(target)
    geometry = [tags[256][0], tags[257][0], tags.get(274, [1])[0]]
    if data.get('geometry') and data['geometry'] != geometry:
        raise RuntimeError('Sony crop, rotation or output dimensions changed. Restore the original geometry before updating a retouched document.')
    data['geometry'] = geometry
    data['active_revision'] = token
    atomic_json(folder / 'project.json', data)
    state.update(status='ready', filename=target.name, settings=recipe.name, bytes=target.stat().st_size, render_seconds=round(time.monotonic()-started, 3), tiff=tags)
    atomic_json(job / 'job.json', state)
    return dict(project=ident, token=token, render=str(target), render_seconds=state['render_seconds'])


def clean_job(token, acknowledge=False, expected_project=None):
    job = child(CACHE, token)
    record = job / 'job.json'
    state = json.loads(record.read_text(encoding='utf-8'))
    if state.get('version') != 2 or state.get('token') != token:
        raise ValueError('Unrecognized cache job.')
    ident = checked_id(state['project'])
    if expected_project is not None and ident != expected_project:
        raise ValueError('Cache/project mismatch.')
    if acknowledge:
        if state['status'] not in ('ready', 'embedded', 'cleaned'):
            raise ValueError('Only a completed render can be acknowledged.')
        state['status'] = 'embedded'
        atomic_json(record, state)
    if state['status'] not in ('embedded', 'cleaned'):
        return dict(cleaned=False, bytes_freed=0)
    legacy_name = 'SonyRAW-' + ident + '.tif'
    versioned_name = 'SonyRAW-' + ident + '-' + token + '.tif'
    filename = state.get('filename', legacy_name)
    if filename not in (legacy_name, versioned_name):
        raise ValueError('Unexpected cache filename.')
    target = job / filename
    if target.resolve().parent != job.resolve() or target.is_symlink():
        raise ValueError('Unsafe cache target.')
    size = target.stat().st_size if target.exists() else 0
    try:
        target.unlink(missing_ok=True)
    except PermissionError:
        return dict(cleaned=False, bytes_freed=0)
    state['status'] = 'cleaned'
    atomic_json(record, state)
    return dict(cleaned=True, bytes_freed=size)


def cleanup():
    freed = 0
    skipped = 0
    for folder in CACHE.iterdir():
        if not folder.is_dir() or not ID.fullmatch(folder.name):
            continue
        try:
            result = clean_job(folder.name)
            freed += result['bytes_freed']
            skipped += not result['cleaned']
        except (OSError, ValueError, KeyError):
            skipped += 1
    return dict(bytes_freed=freed, skipped=skipped)


def dispatch(request):
    PROJECTS.mkdir(exist_ok=True)
    CACHE.mkdir(exist_ok=True)
    action = request['action']
    started = time.monotonic()
    if action == 'ack':
        return clean_job(checked_id(request['token']), True, checked_id(request['project']))
    if action == 'cleanup':
        return cleanup()
    if action == 'warmup':
        sony = Sony()
        return dict(pid=sony.pid, seconds=round(time.monotonic()-started, 3))
    if action in ('open', 'prepare', 'profiles'):
        if request.get('project'):
            folder, data = project(checked_id(request['project']))
            if Path(data['source']).resolve() != Path(request['source']).resolve():
                raise ValueError('RAW не соответствует подготовленному проекту.')
            validate_raw(folder, data)
        else:
            folder, data = new_project(request['source'])
    elif action in ('edit', 'update', 'checkpoint'):
        folder, data = project(checked_id(request['project']))
    else:
        raise ValueError('Unknown action.')
    cleanup()
    sony = Sony()
    revision = request.get('revision')
    if revision:
        checked_id(revision)
    if action == 'checkpoint':
        validate_raw(folder, data)
        recipe = snapshot_recipe(sony, folder, data)
        return dict(project=data['id'], settings=recipe.name)
    candidate_recipe = None
    if action == 'profiles':
        activate(sony, folder, data)
        options = sony.profiles('SonyRAW-' + data['id'] + '.ARW')
        snapshot_recipe(sony, folder, data)
        return dict(project=data['id'], source=data['source'], profiles=options)
    if action == 'prepare':
        activate(sony, folder, data)
        if request.get('sony_profile') is not None:
            apply_profile(sony, folder, data, request['sony_profile'])
            recipe = settings_path(folder, data)
        else:
            recipe = snapshot_recipe(sony, folder, data)
        data['active_revision'] = recipe.stem.removeprefix('settings-')
        atomic_json(folder / 'project.json', data)
        w.u.SetForegroundWindow(sony.main)
        return dict(project=data['id'], revision=data['active_revision'], source=data['source'], kind='initial',
                    name=Path(data['source']).name)
    if action == 'update':
        validate_raw(folder, data)
        sony.require('SonyRAW-' + data['id'] + '.ARW')
        if revision and revision != data.get('active_revision'):
            raise RuntimeError('Sony is editing a different saved recipe version. Run Edit Sony RAW for this smart object first.')
        if request.get('skip_unchanged') and revision:
            baseline = settings_path(folder, data, revision)
            candidate_recipe = snapshot_recipe(sony, folder, data)
            from recipe_compare import recipes_equal
            if baseline and recipes_equal(baseline, candidate_recipe):
                return dict(unchanged=True, project=data['id'], revision=revision,
                            total_seconds=round(time.monotonic()-started, 3), reused_raw=True)
        reused = True
    else:
        reused = activate(sony, folder, data, revision)
        if request.get('sony_profile') is not None:
            apply_profile(sony, folder, data, request['sony_profile'])
            candidate_recipe = settings_path(folder, data)
    if action == 'edit':
        if w.u.IsIconic(sony.main):
            w.u.ShowWindow(sony.main, 9)
        w.u.SetForegroundWindow(sony.main)
        return dict(project=data['id'], reused=reused)
    result = render(sony, folder, data, candidate_recipe)
    result.update(total_seconds=round(time.monotonic()-started, 3), reused_raw=reused)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', type=Path, required=True)
    args = parser.parse_args()
    result = args.request.with_suffix('.result.json')
    mutex = None
    try:
        mutex = w.k.CreateMutexW(None, False, 'Local\\SonyRawPrototypeRender')
        if not mutex or C.get_last_error() == 183:
            raise RuntimeError('Another Sony RAW operation is running.')
        request = json.loads(args.request.read_text(encoding='utf-8-sig'))
        response = dispatch(request)
        response['ok'] = True
        atomic_json(result, response)
        print(json.dumps(response, ensure_ascii=True), flush=True)
        return 0
    except Exception as error:
        traceback.print_exc()
        atomic_json(result, dict(ok=False, error=str(error)))
        return 1
    finally:
        if mutex:
            w.k.CloseHandle(mutex)


if __name__ == '__main__':
    sys.exit(main())
