import base64
import ctypes as C
import importlib.util
import json
import queue
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

SOURCE = Path(__file__).resolve().parent
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))
import runtime_paths as runtime
ROOT = runtime.data_root()
BUNDLE = runtime.bundle_root()
spec = importlib.util.spec_from_file_location('sony_bridge_v2', BUNDLE / 'bridge_v2.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class Photoshop:
    def __init__(self):
        self.process = None
        self.responses = queue.Queue()
        self.lock = threading.Lock()

    def _start(self):
        if self.process is not None and self.process.poll() is None:
            return
        self.responses = queue.Queue()
        (ROOT / 'panel-logs').mkdir(exist_ok=True)
        self.stderr = (ROOT / 'panel-logs' / 'photoshop-host.log').open('a', encoding='utf-8')
        self.process = subprocess.Popen(
            ['powershell.exe', '-NoLogo', '-NoProfile', '-STA', '-File', str(BUNDLE / 'photoshop_host.ps1')],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr,
            text=True, encoding='utf-8', bufsize=1, creationflags=subprocess.CREATE_NO_WINDOW,
            cwd=str(ROOT))
        process = self.process
        responses = self.responses
        def read():
            try:
                for line in process.stdout:
                    responses.put(line)
            finally:
                responses.put(None)
        threading.Thread(target=read, daemon=True).start()

    def evaluate(self, script, start=False, timeout=180):
        with self.lock:
            self._start()
            script = '$.evalFile(new File(%s)); $.evalFile(new File(%s));\n' % (
                json.dumps(str(BUNDLE / 'panel_photoshop.jsx')), json.dumps(str(BUNDLE / 'lut_photoshop.jsx'))) + script
            photoshop_path = runtime.resolve_photoshop() if start else None
            payload = dict(action='eval', start=start, photoshop=str(photoshop_path) if photoshop_path else None,
                           script=base64.b64encode(script.encode('utf-8')).decode('ascii'))
            self.process.stdin.write(json.dumps(payload) + '\n')
            self.process.stdin.flush()
            try:
                line = self.responses.get(timeout=timeout)
            except queue.Empty:
                self.process.kill()
                self.process.wait(timeout=5)
                raise TimeoutError('Photoshop не ответил вовремя. Проверьте его диалоги. Операция не будет повторена автоматически.')
            if line is None:
                raise RuntimeError('Соединение с Photoshop закрыто. Повторите команду.')
            response = json.loads(line)
            if not response['ok']:
                raise RuntimeError(response['error'])
            if not response.get('running'):
                return None
            return response['value']

    def call(self, action, data=None, start=False):
        from lut_library import prepare_lut
        data = dict(data or {})
        if data.get('lut'):
            data['lut'] = prepare_lut(data['lut'], ROOT)
        script = 'sonyPanelCall(%s, %s);' % (json.dumps(action), json.dumps(data, ensure_ascii=True))
        response = self.evaluate(script, start=start)
        if response is None:
            return {'running': False, 'targets': []}
        result = json.loads(response)
        if not result.get('ok'):
            raise RuntimeError(result.get('error', 'Photoshop scripting error'))
        return result

    def foreground(self):
        w = bridge.w
        w.u.ShowWindow.argtypes = [w.W.HWND, C.c_int]
        w.u.IsIconic.argtypes = [w.W.HWND]
        w.u.SetForegroundWindow.argtypes = [w.W.HWND]
        for h in w.windows():
            if w.cls(h) == 'Photoshop' and w.u.IsWindowVisible(h):
                path = w.executable(w.pid(h))
                if Path(path).name.lower() == 'photoshop.exe':
                    if w.u.IsIconic(h):
                        w.u.ShowWindow(h, 9)
                    w.u.SetForegroundWindow(h)
                    return

    def close(self):
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.stdin.write('{"action":"quit"}\n')
                self.process.stdin.flush()
                self.process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                self.process.terminate()
        if hasattr(self, 'stderr'):
            self.stderr.close()


def operation(request):
    handle = bridge.w.k.CreateMutexW(None, False, 'Local\\SonyRawPrototypeRender')
    error = C.get_last_error()
    try:
        if not handle or error == 183:
            raise RuntimeError('Другая команда Sony RAW уже выполняется. Дождитесь её окончания.')
        return bridge.dispatch(request)
    finally:
        if handle:
            bridge.w.k.CloseHandle(handle)


class Controller:
    def __init__(self, notify=None, session=None):
        self.ps = Photoshop()
        self.notify = notify or (lambda message: None)
        self.pending = None
        self.completed = None
        self.last_render = None
        self.recovery = None
        self.comparison = None
        self.prefetched = None
        self.catalog = None
        self.session = Path(session) if session else ROOT / 'panel-session.json'
        try:
            state = json.loads(self.session.read_text(encoding='utf-8'))
            self.pending = state.get('pending')
            self.recovery = state.get('recovery')
            self.comparison = state.get('comparison')
        except (OSError, ValueError):
            pass

    def save_session(self):
        bridge.atomic_json(self.session, dict(pending=self.pending, recovery=self.recovery, comparison=self.comparison))
        if self.comparison and self.comparison.get('id'):
            folder = bridge.child(ROOT / 'comparisons', self.comparison['id'])
            if folder.is_dir():
                bridge.atomic_json(folder / 'comparison.json', self.comparison)

    def compare_call(self, action, data, start=True):
        from lut_library import prepare_lut
        data = dict(data)
        if data.get('lut'):
            data['lut'] = prepare_lut(data['lut'], ROOT)
        script = '$.evalFile(new File(%s)); sonyCompareCall(%s, %s);' % (
            json.dumps(str(BUNDLE / 'comparison_photoshop.jsx')), json.dumps(action), json.dumps(data, ensure_ascii=True))
        response = self.ps.evaluate(script, start=start, timeout=300)
        if response is None and action in ('close', 'purge'):
            return {'ok': True, 'absent': True, 'purged': False}
        if response is None:
            raise RuntimeError('Photoshop не запущен.')
        result = json.loads(response)
        if not result.get('ok'):
            raise RuntimeError(result.get('error', 'Comparison failed'))
        return result

    def source_signature(self, source):
        source = Path(source).resolve(strict=True)
        stat = source.stat()
        return [str(source), stat.st_size, stat.st_mtime_ns]

    def profile_catalog(self, source, refresh=False):
        from profile_catalog import catalog
        self.catalog = catalog(source, ROOT, BUNDLE, refresh=refresh)
        return self.catalog

    def prefetch(self, source, engine='sony'):
        signature = self.source_signature(source)
        current = self.prefetched
        if current and current['signature'] == signature and current['engine'] == engine:
            return current
        started = time.monotonic()
        if engine == 'sony':
            bridge.PROJECTS.mkdir(exist_ok=True)
            _, data = bridge.new_project(source)
            prepared = dict(project=data['id'])
        else:
            from comparison_adobe import adobe_copy
            folder = ROOT / 'adobe-projects' / uuid.uuid4().hex
            folder.mkdir(parents=True)
            private = adobe_copy(folder, Path(source), folder.name)
            digest = bridge.base.sha(private)
            bridge.atomic_json(folder / 'project.json', dict(source=str(source), engine='adobe', sha256=digest))
            stat = private.stat()
            prepared = dict(adobe=str(private), raw_size=stat.st_size, raw_mtime_ns=stat.st_mtime_ns, sha256=digest)
        if self.source_signature(source) != signature:
            raise ValueError('RAW изменился во время фоновой подготовки.')
        self.prefetched = dict(prepared, signature=signature, engine=engine, seconds=round(time.monotonic()-started, 2))
        return self.prefetched

    def _prepared_project(self, source):
        prepared = self.prefetched
        if prepared and prepared['engine'] == 'sony' and prepared['signature'] == self.source_signature(source):
            return prepared['project']
        return None

    def compare(self, source, percent=50, lut=None, adobe_profile='camera_standard', sony_profile='camera_standard'):
        from preview_settings import validate_percent
        percent = validate_percent(percent)
        started = time.monotonic()
        if self.pending or self.recovery:
            raise RuntimeError('Завершите текущую коррекцию перед сравнением.')
        if getattr(self, 'comparison', None):
            raise RuntimeError('Сначала выберите Sony/Adobe или закройте текущее сравнение.')
        def load(name):
            spec = importlib.util.spec_from_file_location(name, BUNDLE / (name + '.py'))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        from development_profiles import resolve_adobe
        resolved_profile = resolve_adobe(source, adobe_profile)
        comparison = load('comparison')
        adobe = load('comparison_adobe')
        self.notify('Готовлю уменьшенное сравнение Sony / Adobe…')
        handle = bridge.w.k.CreateMutexW(None, False, 'Local\\SonyRawPrototypeRender')
        error = C.get_last_error()
        try:
            if not handle or error == 183:
                raise RuntimeError('Другая операция Sony уже выполняется.')
            state = comparison.prepare(Path(source), percent, self.notify, sony_profile=sony_profile, project=self._prepared_project(source))
        finally:
            if handle:
                bridge.w.k.CloseHandle(handle)
        self.notify('Adobe: %s, баланс белого «Как снято»…' % resolved_profile['label'])
        project_folder, project_data = bridge.project(state['project'])
        state['adobe'] = str(adobe.adobe_copy(Path(state['directory']), bridge.validate_raw(project_folder, project_data), state['id'], project_data['source_sha256']))
        from lut_library import apply_xmp
        from development_profiles import apply_adobe_profile, restore_adobe_profile
        apply_adobe_profile(state['adobe'], resolved_profile)
        baseline = Path(state['directory']) / 'adobe-base.xmp'
        baseline.write_bytes(Path(state['adobe']).with_suffix('.xmp').read_bytes())
        state['adobeBase'] = str(baseline)
        state['lut'] = lut
        apply_xmp(state['adobe'], lut)
        restore_adobe_profile(state['adobe'], baseline)
        state['adobeProfile'] = resolved_profile['camera_profile']
        state['adobeLook'] = resolved_profile.get('look_name')
        state['adobeLookUUID'] = resolved_profile.get('look_uuid')
        state['adobeProfileLabel'] = resolved_profile['label']
        state['adobeProfileID'] = adobe_profile
        self.comparison = state
        self.save_session()
        result = self.compare_call('build', state)
        state['view'] = result['comparison']
        state['shown'] = 'sony'
        state['seconds'] = round(time.monotonic()-started, 2)
        self.save_session()
        self.ps.foreground()
        return state

    def show_comparison(self, engine):
        state = getattr(self, 'comparison', None)
        if not state or not state.get('view'):
            raise RuntimeError('Сравнение ещё не готово.')
        result = self.compare_call('show', dict(state['view'], engine=engine))
        state['view']['historyCount'] = result['historyCount']
        if 'historyID' in result:
            state['view']['historyID'] = result['historyID']
        state['view']['modified'] = result['modified']
        state['shown'] = engine
        self.save_session()
        self.ps.foreground()
        return result

    def set_comparison_lut(self, lut):
        state = self.comparison
        if not state or not state.get('view'):
            raise RuntimeError('Сравнение ещё не готово.')
        if self.pending or self.recovery:
            raise RuntimeError('Завершите текущий импорт перед сменой LUT.')
        previous = state.get('lut')
        identity = lambda value: ((value or {}).get('kind'), (value or {}).get('sha256'), (value or {}).get('path'))
        if identity(previous) == identity(lut):
            return dict(unchanged=True, seconds=0, adobe_rendered=False)
        started = time.monotonic()
        adobe_changed = any(value and value.get('kind') == 'xmp' for value in (previous, lut))
        sidecar = Path(state['adobe']).with_suffix('.xmp') if adobe_changed else None
        original = None
        if adobe_changed:
            baseline = Path(state.get('adobeBase', ''))
            expected = Path(state['directory']) / 'adobe-base.xmp'
            if baseline != expected or not baseline.is_file() or baseline.resolve() != baseline.absolute():
                raise RuntimeError('Для смены XMP создайте сравнение новой версией панели. CUBE можно менять без пересоздания.')
            if sidecar.parent != baseline.parent or sidecar.resolve() != sidecar.absolute() or sidecar.stat().st_nlink != 1:
                raise RuntimeError('Частный XMP сравнения перенаправлен. Создайте сравнение заново.')
            self.notify('Применяю XMP: обновляется только Adobe. Sony не перепроявляется…')
            original = sidecar.read_bytes()
            try:
                sidecar.write_bytes(baseline.read_bytes())
                from lut_library import apply_xmp
                from development_profiles import restore_adobe_profile
                apply_xmp(state['adobe'], lut)
                restore_adobe_profile(state['adobe'], baseline)
            except Exception:
                sidecar.write_bytes(original)
                raise
        else:
            self.notify('Меняю LUT в готовом сравнении — без проявки RAW…')
        request = dict(state, lut=lut, view=dict(state['view']), refreshAdobe=adobe_changed)
        try:
            result = self.compare_call('lut', request)
        except Exception:
            if original is not None:
                sidecar.write_bytes(original)
            raise
        state['view'] = result['comparison']
        state['lut'] = lut
        state['lut_seconds'] = round(time.monotonic() - started, 3)
        self.save_session()
        return dict(seconds=state['lut_seconds'], adobe_rendered=adobe_changed, unchanged=False)

    def choose_comparison(self, engine):
        state = getattr(self, 'comparison', None)
        if not state:
            raise RuntimeError('Нет активного сравнения.')
        self.notify('Создаю рабочий документ из исходного RAW в полном разрешении…')
        started = time.monotonic()
        if engine == 'sony':
            state['selected_engine'] = 'sony'
            self.save_session()
            render = operation(dict(action='update', project=state['project'], revision=state['revision']))
            render.update(source=state['source'], sourceName=Path(state['source']).name,
                          lut=state.get('lut') if (state.get('lut') or {}).get('kind') == 'cube' else None)
            self.recovery = dict(kind='open', render=render)
            self.save_session()
            target = self.ps.call('open', render, start=True)['target']
            self.recovery = None
            self.save_session()
            cleaned = self._ack(render)
            result = dict(target=target, cleaned=cleaned, seconds=round(time.monotonic()-started,2))
        elif engine == 'adobe':
            result = self.compare_call('adobeFull', state)
            result.update(engine='adobe', seconds=round(time.monotonic()-started,2))
        else:
            raise ValueError('Unknown development engine.')
        state['selected_engine'] = engine
        self.save_session()
        self.finish_comparison()
        self.ps.foreground()
        return result

    def finish_comparison(self):
        state = getattr(self, 'comparison', None)
        if not state:
            return {'closed': True}
        if state.get('view'):
            try:
                self.compare_call('close', state['view'], start=False)
            except RuntimeError as error:
                # A modified preview belongs to the user; leave its backing files intact.
                state['retained'] = True
                self.save_session()
                self.comparison = None
                self.save_session()
                return {'closed': False, 'retained': str(error)}
        folder = ROOT / 'comparisons' / bridge.checked_id(state['id'])
        if folder.resolve() != folder.absolute():
            raise ValueError('Unexpected comparison path.')
        from preview_cleanup import remove_files
        removed = remove_files(folder, state['id'])
        state['closed'] = True
        self.save_session()
        self.comparison = None
        self.save_session()
        return dict(closed=True, **removed)

    def cancel(self):
        state = dict(pending=self.pending, recovery=self.recovery, comparison=self.comparison)
        if not any(state.values()):
            return {'cancelled': True, 'retained': False}
        archive = self.session.parent / 'cancelled-operations'
        archive.mkdir(exist_ok=True)
        path = archive / (uuid.uuid4().hex + '.json')
        bridge.atomic_json(path, dict(state, cancelled_at=time.time()))
        self.pending = self.recovery = self.comparison = None
        try:
            self.save_session()
        except Exception:
            self.pending, self.recovery, self.comparison = state['pending'], state['recovery'], state['comparison']
            raise
        self.completed = None
        self.last_render = None
        return dict(cancelled=True, retained=True, archive=str(path))

    def cleanup(self, purge_all=False):
        from preview_cleanup import records, remove_files, release_sony
        if purge_all and (self.pending or self.recovery):
            raise RuntimeError('Сначала завершите или отмените текущую проявку перед очисткой кэша.')
        result = operation({'action': 'cleanup'})
        result.update(previews_closed=0, previews_retained=0, sony_closed=0, sony_retained=0, photoshop_purged=False, warnings=[])
        excluded = set()
        for state in (self.pending, self.recovery, self.completed):
            if state:
                ident = state.get('project') or state.get('render', {}).get('project')
                if ident:
                    excluded.add(ident)
        if self.comparison and not self.pending and not self.recovery:
            closed = self.finish_comparison()
            result['previews_closed'] += bool(closed.get('closed'))
            result['previews_retained'] += not closed.get('closed', False)
            result['bytes_freed'] += closed.get('bytes_freed', 0)
        candidates = {}
        for folder, state in records(ROOT):
            if state.get('project') in excluded or state.get('selected_engine') == 'sony':
                continue
            ident = state.get('project')
            if ident and state.get('revision') and not state.get('retained'):
                candidates[ident] = state['revision']
            if state.get('retained'):
                result['previews_retained'] += 1
                continue
            if not state.get('closed'):
                if not state.get('view'):
                    result['previews_retained'] += 1
                    continue
                try:
                    self.compare_call('close', state['view'], start=False)
                    result['previews_closed'] += 1
                    state['closed'] = True
                    bridge.atomic_json(folder / 'comparison.json', state)
                except RuntimeError as error:
                    result['previews_retained'] += 1
                    result['warnings'].append(str(error))
                    candidates.pop(ident, None)
                    continue
            removed = remove_files(folder, state['id'])
            result['bytes_freed'] += removed['bytes_freed']
            result['skipped'] += removed['skipped']
        try:
            handle = bridge.w.k.CreateMutexW(None, False, 'Local\\SonyRawPrototypeRender')
            error = C.get_last_error()
            try:
                if not handle or error == 183:
                    raise RuntimeError('Sony занят другой операцией; вкладки не закрыты.')
                sony = release_sony(bridge, candidates, excluded)
                result['sony_closed'], result['sony_retained'] = sony['closed'], sony['retained']
                result['warnings'].extend(sony['warnings'])
            finally:
                if handle:
                    bridge.w.k.CloseHandle(handle)
        except (OSError, ValueError, RuntimeError, TimeoutError) as error:
            result['warnings'].append(str(error))
        if purge_all:
            purged = self.compare_call('purge', {}, start=False)
            result['photoshop_purged'] = purged.get('purged', False)
        return result

    def status(self):
        status = self.ps.call('status')
        for target in status.get('targets', []):
            try:
                folder, data = bridge.project(target['project'])
                target['source'] = data['source']
                target['sony_profile'] = data.get('sony_profile')
                if self.catalog is None and Path(data['source']).is_file():
                    try:
                        from profile_catalog import catalog
                        target['profile_catalog'] = catalog(data['source'], ROOT, BUNDLE)
                    except (OSError, ValueError):
                        pass
            except (OSError, ValueError):
                target['source'] = '(проект недоступен)'
        return status

    def warmup(self):
        self.notify('Подготавливаю Sony…')
        return operation({'action': 'warmup'})

    def _ack(self, render):
        self.notify('Освобождаю временный TIFF…')
        try:
            result = operation(dict(action='ack', project=render['project'], token=render['token']))
            return result['cleaned']
        except Exception:
            return False

    def open(self, source, first_sony=False, engine='sony', lut=None, adobe_profile='camera_standard', sony_profile='camera_standard'):
        started = time.monotonic()
        if self.pending or self.recovery or self.comparison:
            raise RuntimeError('Сначала завершите текущую проявку или повторите импорт. Неоконченная коррекция не будет заменена другим RAW.')
        if engine == 'adobe':
            return self.open_adobe(source, lut=lut, profile=adobe_profile)
        if lut and lut.get('kind') == 'xmp':
            raise ValueError('XMP-пресет работает только в Adobe. Выберите Adobe или обычный .cube LUT для Sony.')
        if first_sony:
            self.notify('Открываю RAW в Sony без промежуточной проявки…')
            target = operation(dict(action='prepare', source=str(source), sony_profile=sony_profile, project=self._prepared_project(source)))
            target['lut'] = lut
            target['prepare_seconds'] = round(time.monotonic()-started, 2)
            self.pending = target
            self.save_session()
            return dict(prepared=True, target=target, seconds=target['prepare_seconds'])
        self.notify('Подключаю Photoshop…')
        self.ps.call('status', start=True)
        self.notify('Sony проявляет RAW. При первом запуске это дольше…')
        render = operation(dict(action='open', source=str(source), sony_profile=sony_profile, project=self._prepared_project(source)))
        render.update(source=str(source), sourceName=Path(source).name, lut=lut)
        self.last_render = render
        self.notify('Встраиваю результат в Photoshop…')
        self.recovery = dict(kind='open', render=render)
        self.save_session()
        target = self.ps.call('open', render, start=True)['target']
        self.recovery = None
        self.save_session()
        cleaned = self._ack(render)
        self.completed = target
        self.ps.foreground()
        return dict(target=target, cleaned=cleaned, seconds=round(time.monotonic()-started, 2))

    def open_adobe(self, source, lut=None, profile='camera_standard'):
        spec = importlib.util.spec_from_file_location('comparison_adobe', BUNDLE / 'comparison_adobe.py')
        adobe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adobe)
        source = Path(source).resolve(strict=True)
        if source.suffix.lower() != '.arw':
            raise ValueError('Выберите Sony ARW.')
        from development_profiles import resolve_adobe, apply_adobe_profile
        resolved = resolve_adobe(source, profile)
        started = time.monotonic()
        self.notify('Открываю RAW в Adobe Camera Raw — %s…' % resolved['label'])
        prepared = self.prefetched
        if prepared and prepared['engine'] == 'adobe' and prepared['signature'] == self.source_signature(source):
            private = Path(prepared['adobe'])
            folder = private.parent
            stat = private.stat()
            if private.is_symlink() or stat.st_nlink != 1 or stat.st_size != prepared['raw_size'] or stat.st_mtime_ns != prepared['raw_mtime_ns']:
                raise ValueError('Рабочая копия Adobe изменилась. Добавьте RAW заново.')
            # Reset only the sidecar: the background RAW copy was already verified.
            adobe.write_sidecar(private)
        else:
            folder = ROOT / 'adobe-projects' / uuid.uuid4().hex
            folder.mkdir(parents=True)
            private = adobe.adobe_copy(folder, source, folder.name)
        from lut_library import apply_xmp
        apply_xmp(private, lut)
        apply_adobe_profile(private, resolved)
        bridge.atomic_json(folder / 'project.json', dict(source=str(source), engine='adobe',
                          sha256=prepared['sha256'] if prepared and prepared.get('adobe') == str(private) else bridge.base.sha(private), profile=resolved))
        result = self.compare_call('adobeFull', dict(adobe=str(private), source=str(source), lut=lut,
            adobeProfile=resolved['camera_profile'], adobeLook=resolved.get('look_name'),
            adobeLookUUID=resolved.get('look_uuid'), adobeProfileLabel=resolved['label']))
        self.ps.foreground()
        result.update(engine='adobe', seconds=round(time.monotonic()-started, 2))
        return result

    def edit(self, target, sony_profile=None):
        if self.pending:
            if same_target(self.pending, target):
                return operation(dict(action='edit', project=target['project'], revision=target.get('revision')))
            raise RuntimeError('Уже изменяется другой снимок. Сначала примените его проявку.')
        self.ps.call('validate', target)
        self.notify('Открываю RAW и его рецепт в Sony…')
        request = dict(action='edit', project=target['project'], revision=target.get('revision'))
        if sony_profile is not None:
            request['sony_profile'] = sony_profile
        result = operation(request)
        self.pending = dict(target)
        if sony_profile is not None:
            self.pending['sony_profile'] = sony_profile
        self.completed = None
        self.save_session()
        return result

    def apply(self):
        if not self.pending:
            raise RuntimeError('Сначала нажмите «Изменить проявку».')
        target = dict(self.pending)
        initial = target.get('kind') == 'initial'
        if not initial:
            self.ps.call('validate', target)
        self.notify('Проверяю, изменились ли настройки Sony…' if not initial else 'Sony проявляет RAW с выбранными настройками…')
        started = time.monotonic()
        render = operation(dict(action='update', project=target['project'], revision=target.get('revision'), skip_unchanged=not initial))
        if render.get('unchanged'):
            self.completed = target
            self.pending = None
            self.save_session()
            self.ps.foreground()
            return dict(target=target, cleaned=True, unchanged=True, seconds=round(time.monotonic()-started, 2))
        self.last_render = render
        if initial:
            render.update(source=target['source'], sourceName=Path(target['source']).name, lut=target.get('lut'))
            self.recovery = dict(kind='open', render=render, prepare_seconds=target.get('prepare_seconds', 0))
            self.save_session()
            updated = self.ps.call('open', render, start=True)['target']
            return self._finish_apply(updated, render, started)
        self.notify('Обновляю исходный смарт-объект, сохраняя ретушь…')
        # Persist before the Photoshop call so a failed import can reuse the same render.
        self.recovery = dict(kind='replace', target=target, render=render)
        self.save_session()
        updated = self.ps.call('replace', dict(target=target, render=render))['target']
        return self._finish_apply(updated, render, started)

    def defer(self):
        if self.recovery:
            raise RuntimeError('Есть готовая проявка. Сначала повторите её импорт, чтобы не потерять результат.')
        if self.pending:
            self.notify('Сохраняю рецепт без изменения документа Photoshop…')
            operation(dict(action='checkpoint', project=self.pending['project']))
            self.pending = None
            self.save_session()
        return {'deferred': True}

    def retry_import(self):
        recovery = getattr(self, 'recovery', None)
        if not recovery:
            raise RuntimeError('Нет результата для повторного импорта.')
        started = time.monotonic()
        self.notify('Повторяю только импорт готовой проявки…')
        if recovery.get('kind') == 'open':
            updated = self.ps.call('open', recovery['render'], start=True)['target']
        else:
            updated = self.ps.call('replace', recovery)['target']
        return self._finish_apply(updated, recovery['render'], started)

    def _finish_apply(self, target, render, started):
        self.completed = target
        self.pending = None
        self.recovery = None
        self.save_session()
        cleaned = self._ack(render)
        if self.comparison and self.comparison['project'] == render['project']:
            self.finish_comparison()
        self.ps.foreground()
        return dict(target=target, cleaned=cleaned, seconds=round(time.monotonic()-started, 2))


def same_target(a, b):
    if not a or not b:
        return False
    return all(a.get(key) == b.get(key) for key in ('document', 'layer', 'project', 'revision'))
