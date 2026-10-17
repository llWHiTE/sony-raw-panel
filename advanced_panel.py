"""Queue, background policies and Windows quality-of-life controls for the Tk panel."""
import ctypes as C
import json
from pathlib import Path
import time
import tkinter as tk
from tkinter import messagebox, ttk

from raw_queue import RawQueue
import windows_integration as win


class AdvancedPanel:
    def setup_advanced(self, prefs):
        self.raw_queue = RawQueue(self.controller.session.parent)
        self.background_jobs = set()
        self.background_retry = 0
        self.manual_hidden = False
        self.auto_hidden = False
        self.compact = tk.BooleanVar(value=bool(prefs.get('compact', False)))
        self.context_only = tk.BooleanVar(value=bool(prefs.get('context_only', False)))
        self.pre_render = tk.BooleanVar(value=bool(prefs.get('pre_render', False)))
        self.next_preview = tk.BooleanVar(value=bool(prefs.get('next_preview', False)))
        self.hotkeys_enabled = bool(prefs.get('hotkeys_enabled', False))
        self.hotkey_values = prefs.get('hotkeys', dict(win.DEFAULT_KEYS))
        self.cache_limit = max(0, int(prefs.get('cache_limit', 5_000_000_000)))
        self.controller.cache_limit = self.cache_limit
        self.foreground = win.Foreground(self.drop_hwnd)
        self.hotkeys = win.Hotkeys(self.drop_hwnd)
        self.channel_name = win.channel(self.controller.session.parent)
        win.set_channel(self.drop_hwnd, self.channel_name)
        try:
            self.hotkeys.configure(self.hotkeys_enabled, self.hotkey_values)
        except ValueError as error:
            self.hotkeys_enabled = False
            self.status_text.set(str(error))
        menu = self.tools_menu
        menu.add_separator()
        menu.add_checkbutton(label='Компактная панель', variable=self.compact, command=self.layout_compact)
        menu.add_checkbutton(label='Показывать только в Photoshop / Sony', variable=self.context_only)
        menu.add_command(label='Очередь RAW…', command=self.queue_dialog)
        menu.add_checkbutton(label='Готовить полный Sony заранее', variable=self.pre_render)
        menu.add_checkbutton(label='Готовить превью следующего кадра', variable=self.next_preview)
        menu.add_command(label='Кэш готовых изображений…', command=self.cache_dialog)
        menu.add_command(label='Глобальные горячие клавиши…', command=self.hotkey_dialog)
        menu.add_command(label='Подключить «Отправить» Проводника', command=lambda: self.sendto('install'))
        menu.add_command(label='Удалить «Отправить» Проводника', command=lambda: self.sendto('remove'))
        menu.add_command(label='Текущий кадр…', command=self.context_menu)
        self.document_label.bind('<Button-3>', self.context_menu)
        self.source_label = None
        for child in self.content_frame.winfo_children():
            try:
                if str(child.cget('textvariable')) == str(self.source_text):
                    self.source_label = child
                    child.bind('<Button-3>', self.context_menu)
            except tk.TclError:
                pass
        self.compact_pack = {}
        self.queue_bar = ttk.Frame(self.content_frame, style='Sony.TFrame')
        self.queue_text = tk.StringVar()
        ttk.Button(self.queue_bar, text='‹', width=3, style='Sony.TButton', command=lambda: self.queue_step(-1)).pack(side='left')
        ttk.Button(self.queue_bar, textvariable=self.queue_text, style='Sony.TButton', command=self.queue_dialog).pack(side='left', fill='x', expand=True, padx=4)
        ttk.Button(self.queue_bar, text='›', width=3, style='Sony.TButton', command=lambda: self.queue_step(1)).pack(side='right')
        self.refresh_queue()
        for variable in (self.compact, self.context_only, self.pre_render, self.next_preview):
            variable.trace_add('write', self.save_preferences)
        if self.compact.get():
            self.layout_compact()
        self.root.after(600, self.advanced_tick)

    def advanced_preferences(self):
        if not hasattr(self, 'compact'):
            return {}
        return dict(compact=self.compact.get(), context_only=self.context_only.get(), pre_render=self.pre_render.get(),
                    next_preview=self.next_preview.get(), cache_limit=self.cache_limit,
                    hotkeys_enabled=self.hotkeys_enabled, hotkeys=self.hotkey_values)

    def native_message(self, message, wp, lp):
        if message == win.WM_COPYDATA:
            try:
                data = C.cast(lp, C.POINTER(win.CopyData)).contents
                if data.dwData != win.MAGIC or not 0 < data.cbData <= win.MAX_BYTES:
                    return 0
                self.events.put(('ipc', C.string_at(data.lpData, data.cbData)))
                return 1
            except (ValueError, OSError):
                return 0
        if message == win.WM_HOTKEY:
            keys = getattr(self, 'hotkeys', None)
            if keys and wp in keys.registered:
                self.events.put(('hotkey', keys.registered[wp]))
            return 0
        return None

    def advanced_event(self, event, value):
        if event == 'ipc':
            try:
                paths = win.decode_paths(value)
                self.show_panel()
                if paths:
                    self.receive_files(paths)
            except (OSError, ValueError) as error:
                self.status_text.set(str(error))
            return True
        if event == 'hotkey':
            self.global_action(value)
            return True
        if event in ('done', 'error') and value[0].startswith('background_'):
            name, result, seconds = value
            self.background_jobs.discard(name)
            self.background_retry = time.monotonic() + (15 if event == 'error' else 2)
            if name == 'background_full':
                self.preparation_text.set('Полный Sony готов заранее · %.1f с' % seconds if event == 'done' else 'Фоновый Sony отложен: ' + str(result))
            elif name == 'background_next':
                item_id = result.get('item_id') if event == 'done' else None
                row = next((item for item in self.raw_queue.items if item['id'] == item_id), None)
                if row:
                    row['status'] = 'preview_ready' if event == 'done' and result.get('preview_ready') else 'copy_ready' if event == 'done' else 'waiting'
                    if event == 'done' and result.get('project'):
                        row['project'] = result['project']
                    if event == 'done' and result.get('settings'):
                        row['settings'] = result['settings']
                    self.raw_queue.save()
            return True
        return False

    def refresh_queue(self):
        if not hasattr(self, 'queue_bar'):
            return
        items = self.raw_queue.items
        index = next((i + 1 for i, item in enumerate(items) if item['id'] == self.raw_queue.current), 0)
        self.queue_text.set('Кадр %d из %d · очередь' % (index, len(items)))
        if len(items) > 1 and not self.queue_bar.winfo_manager():
            self.queue_bar.pack(fill='x', after=self.add_button, pady=(0, 6))
        elif len(items) <= 1:
            self.queue_bar.pack_forget()

    def activate_queue_row(self, row):
        if self.busy or self.prefetching or self.controller.pending or self.controller.recovery or self.controller.comparison:
            self.status_text.set('Сначала завершите текущую операцию или сравнение.')
            return False
        self.raw_queue.select(row['id'])
        self.jobs.cancel('next')
        self.background_jobs.discard('background_next')
        self.preview_percent = row.get('percent', self.preview_percent)
        import preview_settings as preview
        self.preview_size.set(preview.PRESETS.get(self.preview_percent, preview.custom_label(self.preview_percent)))
        self.stage_source(row['source'])
        self.refresh_queue()
        return True

    def queue_step(self, delta):
        items = self.raw_queue.items
        index = next((i for i, row in enumerate(items) if row['id'] == self.raw_queue.current), -1)
        if 0 <= index + delta < len(items):
            self.activate_queue_row(items[index + delta])

    def receive_files(self, paths):
        try:
            rows = self.raw_queue.add(paths)
        except (OSError, ValueError) as error:
            self.status_text.set(str(error))
            return
        if not rows:
            return
        for row in rows:
            row.setdefault('percent', self.preview_percent)
        self.raw_queue.save()
        self.refresh_queue()
        if not self.busy and not self.prefetching and not self.controller.pending and not self.controller.recovery and not self.controller.comparison:
            self.raw_queue.select(rows[0]['id'])
            self.stage_source(rows[0]['source'])
        else:
            self.status_text.set('Добавлено в очередь: %d. Текущая работа не изменена.' % len(rows))

    def after_operation(self, event, name, result):
        if name == 'context' and event == 'done':
            self.present_context(result)
        if name == 'compare_profile' and self.controller.comparison:
            state = self.controller.comparison
            self.adobe_profile.set(state.get('adobeProfileLabel', 'Camera Standard'))
            self.sony_profile.set(state.get('sonyProfile', {}).get('label', 'Camera Standard'))
            if event == 'done' and self.source_catalog:
                selected = self.selected_profiles()
                self.profile_preferences[self.source_catalog['model']] = dict(adobe=selected['adobe_profile'], sony=selected['sony_profile'])
                self.save_preferences()
        row = self.raw_queue.selected()
        if name == 'profiles' and event == 'done' and not self.controller.comparison:
            if self.selected:
                self.show_target()
            else:
                self.document_text.set('Добавленный RAW ещё не открыт')
                self.detail_text.set('Выберите профили, затем откройте файл или создайте сравнение.')
        if row and name == 'profiles' and event == 'done' and self.source_catalog and Path(row['source']) == Path(self.source_catalog['source']):
            for engine, variable in (('adobe', self.adobe_profile), ('sony', self.sony_profile)):
                desired = row.get('settings', {}).get(engine + '_profile')
                option = next((item for item in self.source_catalog[engine] if item['id'] == desired), None)
                if option:
                    variable.set(option['label'])
        if row and name in ('profiles', 'compare', 'compare_profile', 'open', 'compare_choose'):
            row['status'] = 'error' if event == 'error' else 'done' if name in ('open', 'compare_choose') else 'ready'
            if self.source_catalog and Path(row['source']) == Path(self.source_catalog['source']):
                row['settings'] = self.selected_profiles()
                row['percent'] = self.preview_percent
            self.raw_queue.save()
        if name in ('compare_profile', 'compare_close', 'compare_choose', 'cancel'):
            self.jobs.cancel('full')
            self.background_jobs.discard('background_full')
        self.refresh_queue()
        if self.compact.get():
            self.layout_compact()

    def advanced_tick(self):
        if self.closed:
            return
        kind = self.foreground.kind()
        if self.context_only.get() and not self.manual_hidden:
            if kind == 'other' and self.root.state() == 'normal':
                self.root.withdraw()
                self.auto_hidden = True
            elif kind in ('photoshop', 'sony', 'panel') and self.auto_hidden:
                self.root.deiconify()
                self.auto_hidden = False
        if not self.busy and not self.prefetching and not self.scanning and not self.background_jobs and time.monotonic() >= self.background_retry:
            if not self.source_catalog and not self.controller.comparison and not self.controller.pending and not self.controller.recovery and self.raw_queue.selected():
                self.stage_source(self.raw_queue.selected()['source'])
            else:
                self.schedule_background()
        self.root.after(600, self.advanced_tick)

    def schedule_background(self):
        c = self.controller
        if c.pending or c.recovery:
            return
        state = c.comparison
        if self.pre_render.get() and state and state.get('view') and not c.full_prepared:
            ident = state['id']
            self.background_jobs.add('background_full')
            self.preparation_text.set('Фоном готовится полный Sony; ручная команда будет следующей.')
            self.jobs.put(('background_full', lambda: c.prepare_full_sony(ident)), priority=10, key='full')
            return
        row = self.raw_queue.next()
        if not row or row.get('status') in ('done', 'preview_ready'):
            return
        render = self.next_preview.get() and self.cache_limit > 0
        if row.get('status') == 'copy_ready' and not render:
            return
        source, percent = row['source'], row.get('percent', self.preview_percent)
        settings = dict(row.get('settings', {}))
        preferences = {model: dict(value) for model, value in self.profile_preferences.items() if isinstance(value, dict)}
        ident = row['id']
        def work():
            catalog = c.profile_catalog(source)
            chosen = dict(settings)
            for engine in ('sony', 'adobe'):
                chosen.setdefault(engine + '_profile', preferences.get(catalog['model'], {}).get(engine, 'camera_standard'))
            profile = chosen['sony_profile']
            prepared = c.prefetch(source)
            if not any(item['id'] == profile for item in catalog['sony']):
                raise ValueError('Профиль следующего кадра недоступен для этой камеры.')
            if render:
                result = c.prepare_next_preview(source, percent, profile, prepared['project'])
                return dict(result, item_id=ident, settings=chosen)
            return dict(prepared, item_id=ident, settings=chosen)
        self.background_jobs.add('background_next')
        self.preparation_text.set('Фоном: %s следующего кадра.' % ('превью Sony' if render else 'проверенная RAW-копия'))
        self.jobs.put(('background_next', work), priority=20, key='next')

    def show_panel(self):
        self.manual_hidden = self.auto_hidden = False
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def global_action(self, action):
        if action == 'toggle':
            if self.root.state() == 'withdrawn' or self.root.state() == 'iconic':
                self.show_panel()
            else:
                self.manual_hidden = True
                self.root.withdraw()
            return
        kind = self.foreground.kind()
        if self.busy or kind not in ('panel', 'photoshop', 'sony'):
            return
        if action == 'apply':
            if self.controller.pending or self.controller.recovery:
                self.apply()
        elif action == 'edit' and kind in ('panel', 'photoshop') and not self.controller.comparison:
            def work():
                status = self.controller.status()
                targets = status.get('targets', [])
                chosen = next((t for t in targets if t['layer'] == status.get('selectedLayer')), None)
                chosen = chosen or (targets[0] if len(targets) == 1 else None)
                if not chosen:
                    raise ValueError('Выберите однозначный Sony RAW-объект в Photoshop.')
                return self.controller.edit(chosen)
            self.submit('edit', work)

    def layout_compact(self):
        keep = {self.source_label, self.open_button, self.compare_button, self.compare_frame, self.document_label,
                self.edit_button, self.apply_button, self.cancel_button, self.bar, self.status_label, self.duration_label, self.queue_bar}
        if self.compact.get():
            first = not self.compact_pack
            if first:
                self.normal_geometry = self.root.geometry()
                self.normal_order = [(child, child.pack_info()) for child in self.content_frame.pack_slaves()]
            for child in self.content_frame.winfo_children():
                if child not in keep and child.winfo_manager():
                    self.compact_pack[child] = child.pack_info()
                    child.pack_forget()
            self.root.minsize(380, 300)
            if first:
                self.root.geometry('440x440')
        else:
            # Pack in the original visual order, not at the end after still-visible controls.
            if self.compact_pack:
                for child in self.content_frame.pack_slaves():
                    child.pack_forget()
                for child, stored in self.normal_order:
                    info = dict(stored)
                    info.pop('in', None)
                    child.pack(**info)
            self.compact_pack.clear()
            self.root.minsize(380, 480)
            self.root.geometry(getattr(self, 'normal_geometry', '440x720'))
            self.buttons()
        self.canvas.yview_moveto(0)

    def queue_dialog(self):
        window = tk.Toplevel(self.root)
        window.title('Очередь RAW')
        window.transient(self.root)
        frame = ttk.Frame(window, padding=12)
        frame.pack(fill='both', expand=True)
        listing = tk.Listbox(frame, width=65, height=12, exportselection=False)
        listing.pack(fill='both', expand=True)
        def refresh():
            listing.delete(0, 'end')
            for item in self.raw_queue.items:
                labels = {'waiting': 'ожидает', 'copy_ready': 'копия готова', 'preview_ready': 'превью готово',
                          'ready': 'кадр выбран', 'done': 'открыт', 'error': 'ошибка', 'running': 'выполняется'}
                listing.insert('end', ('● ' if item['id'] == self.raw_queue.current else '') + Path(item['source']).name + ' — ' + labels.get(item['status'], item['status']))
        def selected():
            indices = listing.curselection()
            return self.raw_queue.items[indices[0]] if indices else None
        def use():
            row = selected()
            if not row:
                return
            if self.activate_queue_row(row):
                window.destroy()
        def move(delta):
            row = selected()
            if row:
                self.raw_queue.move(row['id'], delta)
                refresh()
        def remove():
            row = selected()
            if row:
                try:
                    self.raw_queue.remove(row['id'])
                    refresh()
                except ValueError as error:
                    messagebox.showinfo('Очередь', str(error), parent=window)
        for text, command in (('Выбрать кадр', use), ('Выше', lambda: move(-1)), ('Ниже', lambda: move(1)),
                              ('Убрать из очереди', remove), ('Добавить RAW…', self.add_source)):
            ttk.Button(frame, text=text, command=command).pack(fill='x', pady=2)
        refresh()

    def context_menu(self, event=None):
        source = (self.source_catalog or {}).get('source')
        self.context_position = (event.x_root, event.y_root) if event else (self.root.winfo_rootx()+30, self.root.winfo_rooty()+60)
        source_clicked = event is not None and event.widget == self.source_label
        if not source_clicked and not self.busy and not self.controller.comparison and not self.controller.pending and not self.controller.recovery:
            def work():
                status = self.controller.status()
                targets = status.get('targets', [])
                target = next((t for t in targets if t['layer'] == status.get('selectedLayer')), None)
                target = target or (targets[0] if len(targets) == 1 else None)
                return self.controller.current_context(target, source)
            self.submit('context', work)
            return
        try:
            context = self.controller.current_context(None if source_clicked else self.selected, source)
        except (OSError, ValueError, RuntimeError) as error:
            self.status_text.set(str(error))
            return
        self.present_context(context)

    def present_context(self, context):
        menu = tk.Menu(self.root, tearoff=False)
        def reveal(path, select=False):
            try:
                win.reveal(path, select)
            except (OSError, ValueError) as error:
                self.status_text.set(str(error))
        def copy():
            self.root.clipboard_clear()
            self.root.clipboard_append(context['source'])
        if context.get('source'):
            menu.add_command(label='Показать оригинал в Проводнике', command=lambda: reveal(context['source'], True))
            menu.add_command(label='Скопировать путь оригинала', command=copy)
        if context.get('folder'):
            menu.add_command(label='Открыть папку Sony-проекта', command=lambda: reveal(context['folder']))
        menu.add_command(label='Связь RAW / проект / рецепт', command=lambda: messagebox.showinfo('Текущий кадр', '\n'.join('%s: %s' % (k, v or '—') for k, v in context.items()), parent=self.root))
        menu.tk_popup(*self.context_position)

    def sendto(self, action):
        try:
            win.shortcut(action)
            self.status_text.set('«Отправить» подключено.' if action == 'install' else 'Ярлык «Отправить» удалён.')
        except (OSError, ValueError, RuntimeError) as error:
            messagebox.showerror('Проводник', str(error), parent=self.root)

    def cache_dialog(self):
        window = tk.Toplevel(self.root)
        window.title('Кэш готовых изображений')
        frame = ttk.Frame(window, padding=14)
        frame.pack(fill='both', expand=True)
        value = tk.StringVar(value=str(self.cache_limit / 1_000_000_000))
        ttk.Label(frame, text='Лимит, ГБ (0 — отключить). RAW и рецепты не удаляются.').pack()
        ttk.Entry(frame, textvariable=value).pack(fill='x', pady=8)
        def save_limit():
            try:
                limit = float(value.get().replace(',', '.'))
                if not 0 <= limit <= 1000:
                    raise ValueError()
                self.cache_limit = int(limit * 1_000_000_000)
                self.controller.cache_limit = self.cache_limit
                self.save_preferences()
                def trim():
                    from render_workflow import cache_for
                    cache = cache_for(self.controller)
                    cache.limit = self.cache_limit
                    return cache.trim()
                self.submit('cache_limit', trim)
                window.destroy()
            except ValueError:
                messagebox.showerror('Кэш', 'Введите число от 0 до 1000.', parent=window)
        def clear():
            from render_workflow import cache_for
            self.submit('render_cache_clear', lambda: cache_for(self.controller).trim(clear=True))
            window.destroy()
        ttk.Button(frame, text='Сохранить лимит', command=save_limit).pack(fill='x')
        ttk.Button(frame, text='Удалить незакреплённые изображения', command=clear).pack(fill='x', pady=4)

    def hotkey_dialog(self):
        window = tk.Toplevel(self.root)
        window.title('Глобальные горячие клавиши')
        window.transient(self.root)
        frame = ttk.Frame(window, padding=14)
        frame.pack(fill='both', expand=True)
        enabled = tk.BooleanVar(value=self.hotkeys_enabled)
        ttk.Checkbutton(frame, text='Включить глобальные сочетания', variable=enabled).pack(anchor='w')
        variables = {}
        for name, title in (('edit', 'Открыть проявку в Sony'), ('apply', 'Применить в Photoshop'), ('toggle', 'Показать / скрыть панель')):
            ttk.Label(frame, text=title).pack(anchor='w', pady=(8, 0))
            variables[name] = tk.StringVar(value=self.hotkey_values[name])
            ttk.Entry(frame, textvariable=variables[name], width=35).pack(fill='x')
        def save():
            values = {k: v.get() for k, v in variables.items()}
            try:
                self.hotkeys.configure(enabled.get(), values)
            except ValueError as error:
                messagebox.showerror('Горячие клавиши', str(error), parent=window)
                return
            self.hotkeys_enabled, self.hotkey_values = enabled.get(), values
            self.save_preferences()
            window.destroy()
        ttk.Button(frame, text='Сохранить', command=save).pack(fill='x', pady=(12, 0))

    def close_advanced(self):
        if self.background_jobs and self.jobs.active and self.jobs.active.name.startswith('background_'):
            self.status_text.set('Дождитесь завершения фонового экспорта перед выходом.')
        self.hotkeys.close()
        win.clear_channel(self.drop_hwnd, self.channel_name)
