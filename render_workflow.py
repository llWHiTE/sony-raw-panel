"""Derived rendering orchestration. Immutable cache entries never replace project recipes."""
from contextlib import contextmanager
import ctypes as C
import json
from pathlib import Path
import shutil
import time
import uuid

import runtime_paths as runtime
from render_cache import RenderCache, digest, key_for, safe_file
from profile_catalog import load, save, stamp
from recipe_compare import recipe_fingerprint, recipes_equal
from raw_dimensions import image_size


@contextmanager
def stage(controller, name):
    start = time.monotonic()
    try:
        yield
    finally:
        controller.timings[name] = round(time.monotonic() - start, 4)


def engine_stamp(engine, source=None):
    """Fingerprint installed engine code and the model's actual profile files."""
    exe = runtime.resolve_sony() if engine == 'sony' else runtime.resolve_photoshop()
    if not exe:
        return None
    exe = Path(exe)
    if engine == 'sony':
        files = [exe] + sorted(exe.parent.glob('*.dll'))
    else:
        from development_profiles import adobe_roots
        files = [exe]
        candidates = [exe.parent / 'Required/Plug-ins/File Formats/Camera Raw.8bi',
                      Path('C:/Program Files/Common Files/Adobe/Plug-Ins/CC/File Formats/Camera Raw.8bi')]
        plugins = [p for p in candidates if p.is_file()]
        if not plugins or not source:
            return None
        files += plugins
        from raw_dimensions import camera_model
        standard_name = 'Sony ' + camera_model(source) + ' Adobe Standard.dcp'
        files += [Path(row[0]) for row in stamp(source, adobe_roots())
                  if Path(row[0]).parent.name != 'Adobe Standard' or Path(row[0]).name == standard_name]
    return key_for({'files': [(str(p), digest(p)) for p in files]})


def cache_for(c):
    if not hasattr(c, 'render_cache'):
        c.render_cache = RenderCache(c.session.parent, getattr(c, 'cache_limit', 5_000_000_000))
    return c.render_cache


def store_cache(c, key, path, metadata):
    try:
        return cache_for(c).put(key, path, metadata)
    except (OSError, ValueError) as error:
        c.notify('Результат готов; запись кэша пропущена: ' + str(error))
        return None


def sony_key(c, folder, data, recipe, dimensions):
    if not cache_for(c).limit:
        return None
    version = engine_stamp('sony')
    if not version:
        return None
    return key_for(dict(raw=data['source_sha256'], engine='sony', version=version,
                        recipe=recipe_fingerprint(recipe), dimensions=list(dimensions), bits=16, space='sRGB'))


def adobe_request(c, state):
    """Add a cached input or a private TIFF destination to a JSX request."""
    cache = cache_for(c)
    if not cache.limit:
        return state
    folder, data = c.bridge.project(state['project'])
    c.bridge.validate_raw(folder, data)
    if not safe_file(state['adobe']) or digest(state['adobe']) != data['source_sha256']:
        raise ValueError('Частная Adobe RAW-копия изменена. Создайте сравнение заново.')
    version = engine_stamp('adobe', state['adobe'])
    if not version:
        return state
    from lut_library import xmp_tree
    root, _ = xmp_tree(Path(state['adobe']).with_suffix('.xmp'))
    def canonical(element):
        return [element.tag, sorted(element.attrib.items()), (element.text or '').strip(), [canonical(child) for child in element]]
    folder, data = c.bridge.project(state['project'])
    dimensions = state.get('view') or {}
    size = [dimensions.get('width'), dimensions.get('height')]
    if not all(size):
        from preview_settings import scaled_size
        size = scaled_size(*state['dimensions']['original'], state['percent'])
    key = key_for(dict(raw=data['source_sha256'], engine='adobe', version=version,
                       recipe=canonical(root), dimensions=list(size), bits=16, space='sRGB'))
    temporary = Path(state['directory']) / ('adobe-render-' + uuid.uuid4().hex + '.tif')
    result = cache.copy(key, temporary)
    return dict(state, adobeCacheKey=key, adobeCacheInput=str(temporary) if result else None,
                adobeCacheOutput=None if result else str(temporary), adobeCacheFile=str(temporary))


def commit_adobe(c, request):
    path = request.get('adobeCacheFile')
    if not path:
        return
    path = Path(path)
    try:
        if path.is_file() and not request.get('adobeCacheInput'):
            store_cache(c, request['adobeCacheKey'], path, dict(engine='adobe'))
    finally:
        path.unlink(missing_ok=True)


def discard_adobe(request):
    if request.get('adobeCacheFile'):
        Path(request['adobeCacheFile']).unlink(missing_ok=True)


def _guard_live(c, sony, folder, data, revision):
    name = 'SonyRAW-' + data['id'] + '.ARW'
    if sony.active_name() == name:
        saved = c.bridge.settings_path(folder, data, revision)
        import tempfile
        # A transient Sony/AV read handle must not turn scratch-file cleanup into a failed operation.
        with tempfile.TemporaryDirectory(prefix='recipe-check-', dir=c.session.parent, ignore_cleanup_errors=True) as directory:
            current = Path(directory) / 'check.xml'
            sony.save_settings(current, name)
            if not recipes_equal(saved, current):
                raise RuntimeError('Настройки Sony изменены вручную. Завершите коррекцию; сравнение не перезаписано.')


def _align_cached_recipe(c, sony, folder, data, revision):
    live_revision = data.get('active_revision') or revision
    _guard_live(c, sony, folder, data, live_revision)
    if live_revision != revision and sony.active_name() == 'SonyRAW-' + data['id'] + '.ARW':
        c.bridge.activate(sony, folder, data, revision)


def prepare_sony(c, source, percent, profile, project=None, previous=None):
    import comparison
    b = c.bridge
    from preview_settings import scaled_size
    cache = cache_for(c)
    index_path = c.session.parent / 'render-requests.json'
    index = load(index_path)
    with stage(c, 'source_validation'):
        if previous:
            previous_folder, previous_data = b.project(previous['project'])
            private = b.validate_raw(previous_folder, previous_data)
            source_hash = previous_data['source_sha256']
            dimensions = image_size(private, oriented=True)
        else:
            source_hash = digest(source)
            dimensions = image_size(source, oriented=True)
        request_key = key_for(dict(raw=source_hash, profile=profile, percent=percent, engine=engine_stamp('sony') if cache.limit else None))
    # New comparisons may reuse a fully identified, immutable earlier configuration.
    record = index.get(request_key) if not previous and cache.limit else None
    if record:
        try:
            folder, data = b.project(record['project'])
            recipe = b.settings_path(folder, data, record['revision'])
            key = sony_key(c, folder, data, recipe, scaled_size(*dimensions, percent))
            hit = cache.get(key)
            if hit and data['source_sha256'] == source_hash:
                sony = None
                # If Sony is already editing this exact project, do not hide unsaved changes.
                from windows_integration import w
                mains = [h for h in w.windows() if w.cls(h).startswith('Afx:') and w.u.GetMenu(h) and Path(w.executable(w.pid(h))).name.lower() == 'edit.exe']
                if mains:
                    sony = comparison.PreviewSony()
                    _align_cached_recipe(c, sony, folder, data, record['revision'])
                token = uuid.uuid4().hex
                directory = c.session.parent / 'comparisons' / token
                directory.mkdir(parents=True)
                if cache.copy(key, directory / 'sony.tif'):
                    state = dict(record['state'], id=token, directory=str(directory), sony=str(directory / 'sony.tif'),
                                 source=str(source), created=time.time(), sony_seconds=0, cache_hit=True, auxiliary=False)
                    b.atomic_json(directory / 'comparison.json', state)
                    return state
        except (OSError, ValueError, KeyError):
            pass
    with stage(c, 'sony_activate_recipe'):
        if previous:
            folder, data = b.project(previous['project'])
        elif project:
            folder, data = b.project(project)
        else:
            b.PROJECTS.mkdir(exist_ok=True)
            folder, data = b.new_project(source)
        b.validate_raw(folder, data)
        sony = comparison.PreviewSony()
        if previous:
            _guard_live(c, sony, folder, data, previous['revision'])
        b.activate(sony, folder, data, previous['revision'] if previous else None)
        token = uuid.uuid4().hex
        selected = b.apply_profile(sony, folder, data, profile, recipe_token=token)
        recipe = b.settings_path(folder, data, token)
        data['active_revision'] = token
        b.atomic_json(folder / 'project.json', data)
    directory = c.session.parent / 'comparisons' / uuid.uuid4().hex
    directory.mkdir(parents=True)
    key = sony_key(c, folder, data, recipe, scaled_size(*dimensions, percent))
    with stage(c, 'sony_cache_export'):
        hit = cache.copy(key, directory / 'sony.tif') if key else None
        if not hit:
            result = sony.preview(directory / 'sony.tif', 'SonyRAW-' + data['id'] + '.ARW', percent, source_dimensions=dimensions)
            if key:
                store_cache(c, key, directory / 'sony.tif', dict(engine='sony', dimensions=result))
        else:
            tags = b.base.tiff_info(directory / 'sony.tif')
            result = dict(width=tags[256][0], height=tags[257][0], original=list(dimensions), percent=percent,
                          edge=max(scaled_size(*dimensions, percent)) if percent < 100 else 0)
    state = dict(version=1, id=directory.name, project=data['id'], revision=token, source=str(source), sonyProfile=selected,
                 directory=str(directory), sony=str(directory / 'sony.tif'), percent=percent, edge=result['edge'],
                 dimensions=result, created=time.time(), sony_seconds=round(sum(c.timings.values()), 3), cache_hit=bool(hit), auxiliary=bool(previous))
    b.atomic_json(directory / 'comparison.json', state)
    index[request_key] = dict(project=data['id'], revision=token, state=state)
    save(index_path, dict(list(index.items())[-256:]))
    return state


def full_sony(c, state, background=False):
    b = c.bridge
    b.CACHE.mkdir(exist_ok=True)
    folder, data = b.project(state['project'])
    b.validate_raw(folder, data)
    recipe = b.settings_path(folder, data, state['revision'])
    key = sony_key(c, folder, data, recipe, state['dimensions']['original'])
    cache = cache_for(c)
    hit = cache.get(key) if key else None
    if not hit:
        sony = b.Sony()
        _guard_live(c, sony, folder, data, state['revision'])
        b.activate(sony, folder, data, state['revision'])
        rendered = b.render(sony, folder, data, recipe)
        if key:
            store_cache(c, key, rendered['render'], dict(engine='sony', project=data['id'], revision=state['revision']))
        if background:
            # Keep the standard ready job until explicit import or cancellation.
            return dict(rendered, settings_key=key, revision=state['revision'])
        return rendered
    # Materialize a standard bridge job with a fresh immutable revision and basename.
    token = uuid.uuid4().hex
    b.CACHE.mkdir(exist_ok=True)
    job = b.child(b.CACHE, token)
    job.mkdir()
    target = job / ('SonyRAW-' + data['id'] + '-' + token + '.tif')
    cache.copy(key, target)
    destination = folder / ('settings-' + token + '.xml')
    shutil.copy2(recipe, destination)
    data.setdefault('recipes', {})[destination.name] = b.base.sha(destination)
    b.atomic_json(folder / 'project.json', data)
    tags = b.base.tiff_info(target)
    b.atomic_json(job / 'job.json', dict(version=2, project=data['id'], token=token, status='ready', created=time.time(),
                  filename=target.name, settings=destination.name, bytes=target.stat().st_size, tiff=tags, render_seconds=0))
    return dict(project=data['id'], token=token, render=str(target), render_seconds=0, cache_hit=True,
                settings_key=key, revision=state['revision'])
