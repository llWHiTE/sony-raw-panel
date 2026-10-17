"""Independent comparison branches and opt-in speculative Sony jobs."""
from contextlib import contextmanager
import ctypes as C
from pathlib import Path
import time
import uuid


class Deferred(RuntimeError):
    """A background operation is unsafe now; retry only at a later idle point."""


class AdvancedController:
    @contextmanager
    def sony_lane(self):
        b = self.bridge
        handle = b.w.k.CreateMutexW(None, False, 'Local\\SonyRawPrototypeRender')
        error = C.get_last_error()
        try:
            if not handle or error == 183:
                raise RuntimeError('Другая операция Sony выполняется.')
            yield
        finally:
            if handle:
                b.w.k.CloseHandle(handle)

    def set_comparison_profile(self, engine, profile):
        from render_workflow import prepare_sony, adobe_request, commit_adobe, discard_adobe, stage
        state = self.comparison
        if engine not in ('sony', 'adobe') or not state or not state.get('view') or self.pending or self.recovery:
            raise RuntimeError('Профиль можно менять только в готовом сравнении.')
        selected = (state.get('sonyProfile') or {}).get('id') if engine == 'sony' else state.get('adobeProfileID')
        if selected == profile:
            return dict(unchanged=True, seconds=0)
        self.compare_call('check', state['view'])
        started = time.monotonic()
        self.timings = {}
        candidate = dict(state)
        original = baseline_bytes = None
        sidecar = Path(state['adobe']).with_suffix('.xmp')
        baseline = Path(state['directory']) / 'adobe-base.xmp'
        if engine == 'sony':
            try:
                with self.sony_lane():
                    result = prepare_sony(self, Path(state['source']), state['percent'], profile, previous=state)
            except Exception:
                folder, data = self.bridge.project(state['project'])
                revision = data.get('active_revision')
                if revision and revision != state['revision']:
                    self.restore_failed_profile(dict(state, revision=revision), state)
                raise
            candidate.update(sony=result['sony'], sonyProfile=result['sonyProfile'], revision=result['revision'])
        else:
            from comparison_adobe import write_sidecar
            from development_profiles import resolve_adobe, apply_adobe_profile, restore_adobe_profile
            from lut_library import apply_xmp
            from render_cache import safe_file
            if not safe_file(sidecar) or not safe_file(baseline):
                raise RuntimeError('Создайте новое сравнение с независимой базой Adobe.')
            original, baseline_bytes = sidecar.read_bytes(), baseline.read_bytes()
            try:
                resolved = resolve_adobe(state['adobe'], profile)
                write_sidecar(state['adobe'])
                apply_adobe_profile(state['adobe'], resolved)
                new_baseline = sidecar.read_bytes()
                apply_xmp(state['adobe'], state.get('lut'))
                baseline.write_bytes(new_baseline)
                restore_adobe_profile(state['adobe'], baseline)
                candidate.update(adobeProfile=resolved['camera_profile'], adobeLook=resolved.get('look_name'),
                                 adobeLookUUID=resolved.get('look_uuid'), adobeProfileLabel=resolved['label'], adobeProfileID=profile)
                candidate = adobe_request(self, candidate)
            except Exception:
                sidecar.write_bytes(original)
                baseline.write_bytes(baseline_bytes)
                raise
        try:
            with stage(self, engine + '_refresh_com'):
                response = self.compare_call('refresh', dict(candidate, engine=engine))
        except Exception:
            if original is not None:
                sidecar.write_bytes(original)
                baseline.write_bytes(baseline_bytes)
                discard_adobe(candidate)
            elif candidate.get('revision') != state['revision']:
                # Restore only our own candidate, never discard a newer manual change.
                self.restore_failed_profile(candidate, state)
            raise
        if engine == 'adobe':
            commit_adobe(self, candidate)
        else:
            # Put the prepared image back under the original preview's safe allowlisted name.
            import shutil
            try:
                shutil.copy2(candidate['sony'], state['sony'])
                from preview_cleanup import remove_files
                remove_files(Path(candidate['sony']).parent, Path(candidate['sony']).parent.name)
                candidate['sony'] = state['sony']
            except OSError:
                self.notify('Профиль применён; служебный TIFF оставлен в отдельной папке.')
            state['sony'] = candidate['sony']
        for key in ('sonyProfile', 'revision', 'adobeProfile', 'adobeLook', 'adobeLookUUID', 'adobeProfileLabel', 'adobeProfileID'):
            if key in candidate:
                state[key] = candidate[key]
        state['view'] = response['comparison']
        state['timings'] = dict(self.timings)
        if engine == 'sony':
            self.invalidate_prepared_full()
        self.save_session()
        return dict(seconds=round(time.monotonic() - started, 3), engine=engine, unchanged=False)

    def restore_failed_profile(self, candidate, previous):
        from render_workflow import _guard_live
        try:
            with self.sony_lane():
                b = self.bridge
                folder, data = b.project(candidate['project'])
                sony = b.Sony()
                _guard_live(self, sony, folder, data, candidate['revision'])
                b.activate(sony, folder, data, previous['revision'])
        except (OSError, ValueError, RuntimeError, TimeoutError):
            self.notify('Профиль не заменён в сравнении. Проверьте текущий рецепт Sony перед продолжением.')

    def invalidate_prepared_full(self):
        value = self.full_prepared
        if value and hasattr(self, 'render_cache'):
            self.render_cache.pins.discard(value.get('settings_key'))
        self.full_prepared = None
        if value and not self.recovery:
            try:
                # Only an explicitly speculative, unconsumed job can be discarded here.
                import json
                folder = self.bridge.child(self.bridge.CACHE, value['token'])
                record = folder / 'job.json'
                data = json.loads(record.read_text(encoding='utf-8'))
                if data.get('speculative') and data.get('status') == 'ready':
                    target = folder / ('SonyRAW-' + data['project'] + '-' + value['token'] + '.tif')
                    from render_cache import safe_file
                    if safe_file(target):
                        target.unlink()
                        data['status'] = 'cleaned'
                        self.bridge.atomic_json(record, data)
            except (OSError, ValueError, KeyError):
                pass

    def background_allowed(self):
        from windows_integration import w
        if self.pending or self.recovery:
            raise Deferred('Есть незавершённая ручная коррекция.')
        foreground = w.u.GetForegroundWindow()
        if foreground:
            import os
            process = w.pid(foreground)
            active_exe = Path(w.executable(process)).name.lower()
            if process != os.getpid() and active_exe != 'photoshop.exe':
                raise Deferred('Другая программа активна; фоновая проявка отложена.')
        mains = [h for h in w.windows() if w.cls(h).startswith('Afx:') and w.u.GetMenu(h) and
                 Path(w.executable(w.pid(h))).name.lower() == 'edit.exe']
        if len(mains) != 1 or not w.u.IsWindowEnabled(mains[0]) or w.u.IsIconic(mains[0]):
            raise Deferred('Sony закрыт, свёрнут или занят; фоновая проявка отложена.')
        sony = self.bridge.Sony()
        name = sony.active_name()
        # Never switch an unowned tab, even if Sony itself considers it unmodified.
        owned = set()
        if self.comparison:
            owned.add('SonyRAW-' + self.comparison['project'] + '.ARW')
        owned.update('SonyRAW-' + value['project'] + '.ARW' for value in self.prepared_sources.values() if value.get('project'))
        if name and name not in owned:
            raise Deferred('В Sony открыт другой снимок; фоновая проявка отложена.')
        if name:
            from render_workflow import _guard_live
            ident = name[8:-4]
            folder, data = self.bridge.project(ident)
            revision = data.get('active_revision')
            if revision:
                try:
                    _guard_live(self, sony, folder, data, revision)
                except RuntimeError as error:
                    raise Deferred(str(error)) from error
        # Recheck foreground after recipe inspection, just before dispatch.
        foreground = w.u.GetForegroundWindow()
        if foreground and Path(w.executable(w.pid(foreground))).name.lower() == 'edit.exe':
            raise Deferred('Sony получил фокус; задача отложена.')

    def prepare_full_sony(self, comparison_id):
        from render_workflow import full_sony, cache_for
        state = self.comparison
        if not state or state['id'] != comparison_id:
            raise Deferred('Сравнение уже изменилось.')
        with self.sony_lane():
            self.background_allowed()
            result = full_sony(self, state, background=True)
        from render_cache import digest
        result['render_sha256'] = digest(result['render'])
        import json
        job = self.bridge.child(self.bridge.CACHE, result['token']) / 'job.json'
        record = json.loads(job.read_text(encoding='utf-8'))
        record['speculative'] = True
        self.bridge.atomic_json(job, record)
        self.full_prepared = dict(result, comparison_id=comparison_id)
        if result.get('settings_key'):
            cache_for(self).pins.add(result['settings_key'])
        self.save_session()
        return result

    def obtain_full_sony(self, state):
        # Old persisted comparisons without dimensions remain compatible.
        if not state.get('dimensions'):
            import panel_core
            return panel_core.operation(dict(action='update', project=state['project'], revision=state['revision']))
        from render_workflow import full_sony, _guard_live
        with self.sony_lane():
            folder, data = self.bridge.project(state['project'])
            prepared = self.full_prepared
            if prepared and prepared.get('comparison_id') == state['id'] and prepared.get('revision') == state['revision']:
                _guard_live(self, self.bridge.Sony(), folder, data, state['revision'])
                try:
                    path = Path(prepared['render'])
                    from render_cache import safe_file, digest
                    job = self.bridge.child(self.bridge.CACHE, prepared['token'])
                    import json
                    record = json.loads((job / 'job.json').read_text(encoding='utf-8'))
                    from render_workflow import sony_key
                    recipe = self.bridge.settings_path(folder, data, state['revision'])
                    expected_key = sony_key(self, folder, data, recipe, state['dimensions']['original'])
                    expected_path = job / ('SonyRAW-' + state['project'] + '-' + prepared['token'] + '.tif')
                    if isinstance(record, dict) and safe_file(path) and path == expected_path and record.get('version') == 2 and record.get('token') == prepared['token'] and record.get('status') == 'ready' and record.get('project') == state['project'] and digest(path) == prepared.get('render_sha256') and expected_key == prepared.get('settings_key'):
                        self.bridge.settings_path(folder, data, prepared['token'])
                        self.bridge.base.tiff_info(path)
                        return dict(prepared)
                except (OSError, ValueError, KeyError, TypeError):
                    # A lost/corrupt speculative job is a miss, not a broken manual import.
                    self.notify('Предварительный Sony недоступен; результат будет подготовлен заново.')
            return full_sony(self, state)

    def prepare_next_preview(self, source, percent, profile, project):
        from render_workflow import prepare_sony
        with self.sony_lane():
            self.background_allowed()
            self.timings = {}
            previous = self.comparison
            state = prepare_sony(self, Path(source), percent, profile, project)
            if previous:
                folder, data = self.bridge.project(previous['project'])
                self.bridge.activate(self.bridge.Sony(), folder, data, previous['revision'])
            # No Photoshop calls in speculative work. Entry remains reusable in render cache.
            state['closed'] = True
            self.bridge.atomic_json(Path(state['directory']) / 'comparison.json', state)
            from preview_cleanup import remove_files
            remove_files(Path(state['directory']), state['id'])
            return dict(preview_ready=True)

    def current_context(self, target=None, source=None):
        state = self.comparison or self.pending or (self.recovery or {}).get('render') or target or {}
        result = dict(source=state.get('source') or source, project=state.get('project'), revision=state.get('revision') or state.get('token'))
        if result['project']:
            folder, data = self.bridge.project(result['project'])
            result['source'] = data['source']
            result['folder'] = str(folder)
            recipe = self.bridge.settings_path(folder, data, result['revision'])
            result['recipe'] = str(recipe) if recipe else None
        return result
