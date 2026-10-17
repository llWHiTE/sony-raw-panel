import argparse
import ctypes as C
import importlib.util
import json
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import traceback

SOURCE = Path(__file__).resolve().parent
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))
import runtime_paths as runtime
from app_info import AUTHOR, GITHUB_URL, VERSION
import preview_settings as preview
ROOT = runtime.data_root()
BUNDLE = runtime.bundle_root()
spec = importlib.util.spec_from_file_location('panel_core', BUNDLE / 'panel_core.py')
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
TITLE = 'Sony RAW · Photoshop'


class Panel:
    def __init__(self, root, warmup=True, session=None):
        self.root = root
        self.events = queue.Queue()
        self.jobs = queue.Queue()
        self.controller = core.Controller(lambda text: self.events.put(('progress', text)), session=session)
        self.busy = False
        self.scanning = False
        self.targets = []
        self.selected = None
        self.last_state = {}
        self.closed = False
        self.started = 0
        self.heartbeats = 0
        self.last_error = None
        self.opening_seconds = 0
        self.retrying_import = False
        self.wrap_labels = []
        root.title(TITLE)
        root.geometry('440x720+%d+40' % max(20, root.winfo_screenwidth()-480))
        root.minsize(380, 480)
        root.configure(bg='#20242c')
        root.attributes('-topmost', True)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.status_text = tk.StringVar(value='Подключение к Photoshop…')
        self.document_text = tk.StringVar(value='Нет открытого Sony RAW')
        self.detail_text = tk.StringVar(value='Откройте ARW или документ PSD со слоем Sony RAW.')
        self.elapsed_text = tk.StringVar(value='')
        self.duration_text = tk.StringVar(value='')
        self.target_text = tk.StringVar()
        try:
            prefs = json.loads((ROOT / 'ui-preferences.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            prefs = {}
        if not isinstance(prefs, dict):
            prefs = {}
        percent, self.custom_percent, self.preview_mode = preview.preferences(prefs)
        self.preview_percent = percent
        self.preview_size = tk.StringVar(value=preview.custom_label(percent) if self.preview_mode == 'custom' else preview.PRESETS[percent])
        self.engine = tk.StringVar(value='Adobe' if prefs.get('engine') == 'Adobe' else 'Sony')
        self.first_sony = tk.BooleanVar(value=bool(prefs.get('first_sony', False)))
        self.pinned = tk.BooleanVar(value=bool(prefs.get('pinned', True)))
        self.build()
        self.install_drop()
        root.attributes('-topmost', self.pinned.get())
        for preference in (self.preview_size, self.engine, self.first_sony, self.pinned):
            preference.trace_add('write', self.save_preferences)
        root.bind('<Control-o>', lambda _: self.choose())
        root.bind('<Control-Return>', lambda _: self.apply())
        threading.Thread(target=self.worker, daemon=True).start()
        root.after(60, self.drain)
        root.after(200, self.startup if warmup else self.scan)
        root.after(250, self.clock)
        if self.controller.pending:
            self.document_text.set('Продолжить начатую коррекцию')
            self.detail_text.set(self.controller.pending.get('name', 'Sony RAW'))
        self.buttons()

    def build(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Sony.TFrame', background='#20242c')
        style.configure('Sony.TLabel', background='#20242c', foreground='#e5e7eb', font=('Segoe UI', 10))
        style.configure('Muted.TLabel', background='#20242c', foreground='#aeb7c6', font=('Segoe UI', 9))
        style.configure('Heading.TLabel', background='#20242c', foreground='#ffffff', font=('Segoe UI Semibold', 17))
        style.configure('Sony.TButton', background='#303845', foreground='#e5e7eb', bordercolor='#454f60', font=('Segoe UI', 10), padding=(10, 8))
        style.map('Sony.TButton', background=[('disabled', '#272d36'), ('active', '#414e61')], foreground=[('disabled', '#7e8999')])
        style.configure('Accent.TButton', background='#5393ce', foreground='#ffffff', font=('Segoe UI Semibold', 11), padding=(10, 10))
        style.map('Accent.TButton', background=[('disabled', '#303845'), ('active', '#67a3db')], foreground=[('disabled', '#7e8999')])
        style.configure('Sony.TCheckbutton', background='#20242c', foreground='#aeb7c6', font=('Segoe UI', 9))
        style.map('Sony.TCheckbutton', background=[('active', '#20242c')], foreground=[('disabled', '#7e8999')])
        footer = ttk.Frame(self.root, padding=(18, 8, 18, 12), style='Sony.TFrame')
        footer.pack(side='bottom', fill='x')
        row = ttk.Frame(footer, style='Sony.TFrame')
        row.pack(fill='x')
        ttk.Checkbutton(row, text='Поверх окон', variable=self.pinned, style='Sony.TCheckbutton',
                        command=lambda: self.root.attributes('-topmost', self.pinned.get())).pack(side='left')
        self.tools = tk.Menubutton(row, text='⋯', bg='#20242c', fg='#d8dce4', relief='flat', font=('Segoe UI', 13))
        self.tools.pack(side='right')
        menu = tk.Menu(self.tools, tearoff=False)
        menu.add_command(label='Программы и пути…', command=self.paths_dialog)
        menu.add_command(label='О программе…', command=self.about)
        menu.add_command(label='Подготовить Sony', command=self.warmup)
        menu.add_command(label='Очистить подтверждённый кэш', command=self.cleanup)
        menu.add_command(label='Обновить список документов', command=self.scan)
        menu.add_command(label='Сохранить рецепт без применения', command=self.defer)
        menu.add_separator()
        menu.add_command(label='Инструкция', command=self.help)
        self.tools.configure(menu=menu)
        credit = ttk.Frame(footer, style='Sony.TFrame')
        credit.pack(fill='x', pady=(8, 0))
        ttk.Label(credit, text=AUTHOR, style='Muted.TLabel').pack(side='left')
        link = tk.Label(credit, text='GitHub ↗', fg='#81b8ec', bg='#20242c', cursor='hand2', font=('Segoe UI', 9))
        link.pack(side='right')
        link.bind('<Button-1>', lambda _: self.github())

        area = ttk.Frame(self.root, style='Sony.TFrame')
        area.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(area, bg='#20242c', highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(area, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        frame = ttk.Frame(self.canvas, padding=(18, 14, 12, 8), style='Sony.TFrame')
        self.content_window = self.canvas.create_window((0, 0), window=frame, anchor='nw')
        frame.bind('<Configure>', lambda _: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        def resize(event):
            self.canvas.itemconfigure(self.content_window, width=event.width)
            for label in self.wrap_labels:
                label.configure(wraplength=max(240, event.width-36))
        self.canvas.bind('<Configure>', resize)
        self.root.bind('<MouseWheel>', lambda event: self.canvas.yview_scroll(-int(event.delta/120), 'units') if self.canvas.winfo_height() < frame.winfo_height() else None)
        def label(variable, style_name, pady):
            widget = ttk.Label(frame, textvariable=variable, style=style_name, wraplength=360)
            widget.pack(anchor='w', fill='x', pady=pady)
            self.wrap_labels.append(widget)
            return widget
        ttk.Label(frame, text='Sony RAW', style='Heading.TLabel').pack(anchor='w')
        ttk.Label(frame, text='Проявка Sony и Adobe в Photoshop', style='Muted.TLabel').pack(anchor='w', pady=(2, 14))
        engine_row = ttk.Frame(frame, style='Sony.TFrame')
        engine_row.pack(fill='x', pady=(0, 6))
        ttk.Label(engine_row, text='Проявка при открытии:', style='Muted.TLabel').pack(side='left')
        self.engine_choice = ttk.Combobox(engine_row, textvariable=self.engine, values=['Sony', 'Adobe'], state='readonly', width=9)
        self.engine_choice.pack(side='right')
        self.first_check = ttk.Checkbutton(frame, text='Сначала настроить в Sony', variable=self.first_sony, style='Sony.TCheckbutton')
        self.first_check.pack(anchor='w', pady=(0, 10))
        self.engine.trace_add('write', lambda *_: self.buttons())
        self.open_button = ttk.Button(frame, text='Открыть RAW…', style='Sony.TButton', command=self.choose)
        self.open_button.pack(fill='x')
        quality_row = ttk.Frame(frame, style='Sony.TFrame')
        quality_row.pack(fill='x', pady=(12, 6))
        ttk.Label(quality_row, text='Предпросмотр:', style='Muted.TLabel').pack(side='left')
        self.quality = ttk.Combobox(quality_row, textvariable=self.preview_size, state='readonly', width=22, values=self.preview_options())
        self.quality.pack(side='right', padx=(8, 0), fill='x', expand=True)
        self.quality.bind('<<ComboboxSelected>>', self.select_quality)
        self.compare_button = ttk.Button(frame, text='Сравнить Sony / Adobe…', style='Sony.TButton', command=self.compare)
        self.compare_button.pack(fill='x')
        self.compare_frame = ttk.Frame(frame, style='Sony.TFrame')
        self.use_current = ttk.Button(self.compare_frame, text='Использовать показанную проявку', style='Sony.TButton', command=self.choose_current)
        self.use_current.pack(fill='x', pady=(6, 0))
        self.cancel_compare = ttk.Button(self.compare_frame, text='Закрыть сравнение', style='Sony.TButton', command=self.close_compare)
        self.cancel_compare.pack(fill='x', pady=(6, 0))
        self.document_label = label(self.document_text, 'Sony.TLabel', (14, 4))
        self.combo = ttk.Combobox(frame, state='readonly', textvariable=self.target_text)
        self.combo.bind('<<ComboboxSelected>>', self.select)
        self.detail_label = label(self.detail_text, 'Muted.TLabel', (0, 10))
        self.edit_button = ttk.Button(frame, text='Изменить проявку в Sony', style='Sony.TButton', command=self.edit)
        self.edit_button.pack(fill='x', pady=(0, 6))
        self.apply_button = ttk.Button(frame, text='Применить в Photoshop', style='Accent.TButton', command=self.apply)
        self.apply_button.pack(fill='x')
        self.cancel_button = ttk.Button(frame, text='Отменить проявку', style='Sony.TButton', command=self.cancel)
        self.bar = ttk.Progressbar(frame, mode='indeterminate', length=280)
        self.bar.pack(fill='x', pady=(12, 6))
        self.status_label = label(self.status_text, 'Muted.TLabel', (0, 4))
        label(self.duration_text, 'Sony.TLabel', (3, 0))
        label(self.elapsed_text, 'Muted.TLabel', (2, 0))
        ttk.Label(frame, text='Ctrl+O — открыть · Ctrl+Enter — применить', style='Muted.TLabel').pack(anchor='w', pady=(5, 0))

    def preview_options(self):
        return list(preview.PRESETS.values()) + [preview.custom_label(self.custom_percent), preview.CUSTOM]

    def select_quality(self, _=None):
        value = self.preview_size.get()
        if value == preview.CUSTOM:
            self.custom_quality()
            return
        for percent, text in preview.PRESETS.items():
            if value == text:
                self.preview_percent, self.preview_mode = percent, 'preset'
                break
        else:
            self.preview_percent, self.preview_mode = self.custom_percent, 'custom'
        self.save_preferences()

    def custom_quality(self):
        previous = preview.custom_label(self.preview_percent) if self.preview_mode == 'custom' else preview.PRESETS[self.preview_percent]
        self.preview_size.set(previous)
        window = tk.Toplevel(self.root)
        window.title('Свой процент предпросмотра')
        window.transient(self.root)
        window.attributes('-topmost', True)
        frame = ttk.Frame(window, padding=18)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Масштаб каждой стороны от размеров выбранного RAW.\n50% ширины и высоты = 25% числа пикселей.').pack(anchor='w', pady=(0, 10))
        value = tk.StringVar(value=str(self.custom_percent))
        entry = ttk.Spinbox(frame, from_=1, to=100, textvariable=value, width=8)
        entry.pack(anchor='w')
        error_text = tk.StringVar()
        ttk.Label(frame, textvariable=error_text, foreground='#a73825').pack(anchor='w', pady=6)
        def save():
            try:
                percent = preview.validate_percent(value.get())
            except ValueError as error:
                error_text.set(str(error))
                return
            self.preview_percent = self.custom_percent = percent
            self.preview_mode = 'custom'
            self.quality.configure(values=self.preview_options())
            self.preview_size.set(preview.custom_label(percent))
            self.save_preferences()
            window.destroy()
        ttk.Button(frame, text='Сохранить и использовать', command=save).pack(fill='x', pady=4)
        ttk.Button(frame, text='Отмена', command=window.destroy).pack(fill='x', pady=4)
        window.bind('<Return>', lambda _: save())
        window.bind('<Escape>', lambda _: window.destroy())
        entry.focus_set()
        entry.selection_range(0, 'end')
        window.grab_set()

    def save_preferences(self, *_):
        core.bridge.atomic_json(ROOT / 'ui-preferences.json', dict(engine=self.engine.get(),
            first_sony=self.first_sony.get(), preview_percent=self.preview_percent,
            preview_mode=self.preview_mode, custom_percent=self.custom_percent, pinned=self.pinned.get()))

    def startup(self):
        # Capture Tk values on the UI thread.
        selected_sony = self.engine.get() == 'Sony'
        def work():
            config = runtime.load_path_config()
            sony = config.sony or runtime.discover_sony()
            photoshop = config.photoshop or runtime.discover_photoshop()
            runtime.save_path_config(sony=sony, photoshop=photoshop)
            if sony and selected_sony:
                self.controller.warmup()
            return dict(sony=str(sony) if sony else None, photoshop=str(photoshop) if photoshop else None)
        self.submit('startup', work)

    def github(self):
        import webbrowser
        webbrowser.open(GITHUB_URL)

    def about(self):
        messagebox.showinfo('О программе', 'Sony RAW Panel ' + VERSION + '\n\nАвтор: ' + AUTHOR + '\n' + GITHUB_URL +
            '\n\nНезависимый проект. Adobe и Sony не включены и требуются отдельно.\nДанные и настройки: ' + str(ROOT), parent=self.root)

    def paths_dialog(self):
        if self.busy:
            return
        config = runtime.load_path_config()
        window = tk.Toplevel(self.root)
        window.title('Программы и пути')
        window.transient(self.root)
        window.attributes('-topmost', True)
        frame = ttk.Frame(window, padding=18)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Sony Edit: ' + str(config.sony or 'не найден'), wraplength=480).pack(anchor='w', pady=5)
        ttk.Label(frame, text='Photoshop: ' + str(config.photoshop or 'не найден'), wraplength=480).pack(anchor='w', pady=5)
        ttk.Label(frame, text='Если программа не найдена, запустите её самостоятельно\nи нажмите «Найти заново». Изменять реестр не требуется.', wraplength=480).pack(anchor='w', pady=10)
        def rescan():
            window.destroy()
            self.submit('discover', lambda: self.discover_paths())
        ttk.Button(frame, text='Найти заново', command=rescan).pack(fill='x', pady=4)
        def select_exe(kind):
            selected = filedialog.askopenfilename(parent=window, title='Выберите '+('Edit.exe' if kind=='sony' else 'Photoshop.exe'), filetypes=[('Программы','*.exe')])
            if selected:
                try:
                    current = runtime.load_path_config()
                    runtime.save_path_config(sony=selected if kind=='sony' else current.sony,
                                             photoshop=selected if kind=='photoshop' else current.photoshop)
                    window.destroy()
                    self.paths_dialog()
                except ValueError as error:
                    messagebox.showerror('Неверный путь',str(error),parent=window)
        ttk.Button(frame, text='Выбрать Sony Edit вручную…', command=lambda:select_exe('sony')).pack(fill='x', pady=4)
        ttk.Button(frame, text='Выбрать Photoshop вручную…', command=lambda:select_exe('photoshop')).pack(fill='x', pady=4)
        ttk.Button(frame, text='Закрыть', command=window.destroy).pack(fill='x',pady=4)

    @staticmethod
    def discover_paths():
        sony, photoshop = runtime.discover_sony(), runtime.discover_photoshop()
        runtime.save_path_config(sony=sony, photoshop=photoshop)
        return dict(sony=str(sony) if sony else None, photoshop=str(photoshop) if photoshop else None)

    def install_drop(self):
        w = core.bridge.w
        shell = C.WinDLL('shell32', use_last_error=True)
        shell.DragAcceptFiles.argtypes = [w.W.HWND, w.W.BOOL]
        shell.DragQueryFileW.argtypes = [w.W.HANDLE, w.W.UINT, w.W.LPWSTR, w.W.UINT]
        shell.DragFinish.argtypes = [w.W.HANDLE]
        u = w.u
        u.GetWindowLongPtrW.argtypes = [w.W.HWND, C.c_int]
        u.GetWindowLongPtrW.restype = C.c_ssize_t
        u.SetWindowLongPtrW.argtypes = [w.W.HWND, C.c_int, C.c_ssize_t]
        u.SetWindowLongPtrW.restype = C.c_ssize_t
        u.CallWindowProcW.argtypes = [C.c_ssize_t, w.W.HWND, w.W.UINT, w.W.WPARAM, w.W.LPARAM]
        u.CallWindowProcW.restype = C.c_ssize_t
        self.root.update_idletasks()
        self.drop_hwnd = u.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        self.old_wndproc = u.GetWindowLongPtrW(self.drop_hwnd, -4)
        callback_type = C.WINFUNCTYPE(C.c_ssize_t, w.W.HWND, w.W.UINT, w.W.WPARAM, w.W.LPARAM)
        @callback_type
        def dropped(hwnd, message, wp, lp):
            if message == 0x0233:
                paths = []
                try:
                    count = shell.DragQueryFileW(wp, 0xffffffff, None, 0)
                    for i in range(min(count, 2)):
                        length = shell.DragQueryFileW(wp, i, None, 0)
                        text = C.create_unicode_buffer(length+1)
                        shell.DragQueryFileW(wp, i, text, length+1)
                        paths.append(text.value)
                    self.events.put(('drop', paths))
                finally:
                    shell.DragFinish(wp)
                return 0
            return u.CallWindowProcW(self.old_wndproc, hwnd, message, wp, lp)
        self.drop_callback = dropped
        u.SetWindowLongPtrW(self.drop_hwnd, -4, C.cast(dropped, C.c_void_p).value)
        shell.DragAcceptFiles(self.drop_hwnd, True)

    def worker(self):
        while True:
            job = self.jobs.get()
            if job is None:
                self.controller.ps.close()
                return
            name, function = job
            started = time.monotonic()
            try:
                result = function()
                self.events.put(('done', (name, result, time.monotonic()-started)))
            except Exception as error:
                logs = ROOT / 'panel-logs'
                logs.mkdir(exist_ok=True)
                with (logs / 'panel.log').open('a', encoding='utf-8') as f:
                    f.write('\n' + time.strftime('%Y-%m-%d %H:%M:%S ') + name + '\n' + traceback.format_exc())
                self.events.put(('error', (name, str(error), time.monotonic()-started)))

    def submit(self, name, function):
        if self.busy:
            return False
        self.busy = True
        self.started = time.monotonic()
        pending = self.controller.pending or {}
        recovery = self.controller.recovery or {}
        self.opening_seconds = pending.get('prepare_seconds', 0) if name == 'apply' and not recovery else 0
        self.retrying_import = name == 'apply' and bool(recovery)
        self.last_error = None
        self.status_label.configure(foreground='#aeb7c6')
        self.status_text.set('Выполняю…')
        self.bar.start(12)
        self.buttons()
        self.jobs.put((name, function))
        return True

    def buttons(self):
        idle = not self.busy and not self.scanning
        pending = self.controller.pending
        recovery = self.controller.recovery
        comparison = self.controller.comparison
        free = idle and not pending and not recovery and not comparison
        self.engine_choice.configure(state='readonly' if free else 'disabled')
        self.first_check.configure(state='normal' if free and self.engine.get() == 'Sony' else 'disabled')
        ready_compare = bool(comparison and comparison.get('view'))
        shown = (comparison or {}).get('shown', 'sony')
        self.compare_button.configure(state='normal' if free or (idle and ready_compare and not recovery) else 'disabled',
            text=('Сейчас Sony · показать Adobe' if shown == 'sony' else 'Сейчас Adobe · показать Sony') if ready_compare else 'Сравнить Sony / Adobe…')
        self.quality.configure(state='readonly' if free else 'disabled')
        self.use_current.configure(state='normal' if idle and ready_compare and not recovery else 'disabled',
            text='Использовать %s · полный размер' % ('Sony' if shown == 'sony' else 'Adobe RAW'))
        self.cancel_compare.configure(state='normal' if idle and comparison and not recovery else 'disabled')
        if comparison:
            if not self.compare_frame.winfo_manager():
                self.compare_frame.pack(fill='x', after=self.compare_button)
            self.edit_button.pack_forget()
            if not recovery:
                self.apply_button.pack_forget()
            percent = comparison.get('percent')
            size = ('%d%% от RAW' % percent) if percent else 'предыдущий предпросмотр'
            view = comparison.get('view') or {}
            pixels = ' · %d × %d' % (view['width'], view['height']) if view.get('width') else ''
            self.document_text.set('Сравнение: ' + size + pixels)
            self.detail_text.set('Переключайте одной кнопкой. Выбранная проявка откроется в полном разрешении.')
        else:
            self.compare_frame.pack_forget()
            if not self.edit_button.winfo_manager():
                self.edit_button.pack(fill='x', pady=(0, 6), before=self.bar)
        if not comparison or recovery:
            if not self.apply_button.winfo_manager():
                self.apply_button.pack(fill='x', before=self.bar)
        if pending or recovery or (comparison and self.last_error):
            if not self.cancel_button.winfo_manager():
                self.cancel_button.pack(fill='x', pady=(6, 0), before=self.bar)
        else:
            self.cancel_button.pack_forget()
        self.cancel_button.configure(state='normal' if idle else 'disabled')
        self.open_button.configure(state='normal' if free else 'disabled')
        self.edit_button.configure(state='normal' if idle and (self.selected or pending) and not recovery and not comparison else 'disabled')
        self.apply_button.configure(state='normal' if idle and (pending or recovery) else 'disabled',
                                    text='Повторить импорт в Photoshop' if recovery else 'Применить в Photoshop')
        if len(self.targets) > 1 and not comparison:
            if not self.combo.winfo_manager():
                self.combo.pack(fill='x', pady=(0, 5), before=self.detail_label)
        else:
            self.combo.pack_forget()
        self.combo.configure(state='readonly' if idle and not pending and not recovery and len(self.targets)>1 else 'disabled')

    def choose(self):
        if self.busy or self.controller.pending or self.controller.recovery or self.controller.comparison:
            return
        path = filedialog.askopenfilename(parent=self.root, title='Открыть Sony RAW',
                                          filetypes=[('Sony RAW', '*.arw *.ARW')])
        if path:
            self.open_path(path)

    def open_path(self, path):
        first_sony = self.first_sony.get()
        engine = self.engine.get().lower()
        self.submit('open', lambda: self.controller.open(Path(path), first_sony=first_sony, engine=engine))

    def compare(self):
        if self.busy or self.controller.pending or self.controller.recovery:
            return
        if self.controller.comparison:
            engine = 'adobe' if self.controller.comparison.get('shown', 'sony') == 'sony' else 'sony'
            self.show_compare(engine)
            return
        source = filedialog.askopenfilename(parent=self.root, title='Сравнить Sony / Adobe Camera ST', filetypes=[('Sony RAW', '*.arw *.ARW')])
        if source:
            percent = self.preview_percent
            self.submit('compare', lambda: self.controller.compare(Path(source), percent))

    def show_compare(self, engine):
        self.submit('compare_show', lambda: self.controller.show_comparison(engine))

    def choose_current(self):
        if self.controller.comparison:
            self.choose_engine(self.controller.comparison.get('shown', 'sony'))

    def choose_engine(self, engine):
        self.submit('compare_choose', lambda: self.controller.choose_comparison(engine))

    def close_compare(self):
        self.submit('compare_close', self.controller.finish_comparison)

    def select(self, _=None):
        index = self.combo.current()
        self.selected = dict(self.targets[index]) if 0 <= index < len(self.targets) else None
        self.show_target()
        self.buttons()

    def show_target(self):
        target = self.controller.pending or self.selected
        if target:
            source = target.get('source', '')
            name = Path(source).name if source else target.get('name', 'Sony RAW').replace('Sony RAW — ', '')
            self.document_text.set(('Проявка: ' if self.controller.pending else '') + name)
            self.detail_text.set('Меняйте настройки в Sony, затем примените результат.' if self.controller.pending else
                                 'Смарт-объект найден. Слой ретуши можно оставить выбранным.')

    def edit(self):
        target = self.controller.pending or self.selected
        if target:
            self.submit('edit', lambda: self.controller.edit(dict(target)))

    def apply(self):
        if self.controller.recovery:
            self.submit('apply', self.controller.retry_import)
        elif self.controller.pending:
            self.submit('apply', self.controller.apply)

    def cancel(self):
        if self.busy or self.scanning:
            return
        if messagebox.askyesno(TITLE, 'Отменить текущую операцию и освободить панель?\n\nОригинал и документы Photoshop не будут изменены.\nГотовая проявка и данные восстановления останутся на диске.', parent=self.root):
            self.submit('cancel', self.controller.cancel)

    def warmup(self):
        self.submit('warmup', self.controller.warmup)

    def cleanup(self):
        self.submit('cleanup', lambda: core.operation({'action': 'cleanup'}))

    def defer(self):
        if self.busy or not self.controller.pending:
            return
        if messagebox.askyesno(TITLE, 'Сохранить текущий рецепт отдельно, не обновляя Photoshop?\nДокумент останется с предыдущей проявкой.', parent=self.root):
            self.submit('defer', self.controller.defer)

    def scan(self):
        if not self.closed and not self.busy and not self.scanning and not self.controller.pending and not self.controller.recovery and not self.controller.comparison:
            self.scanning = True
            self.jobs.put(('scan', self.controller.status))

    def scanned(self, result):
        self.last_state = result
        old = self.selected
        self.targets = result.get('targets', [])
        self.combo.configure(values=[t.get('name', 'Sony RAW') for t in self.targets])
        index = next((i for i,t in enumerate(self.targets) if old and core.same_target(t, old)), -1)
        if index < 0:
            index = next((i for i,t in enumerate(self.targets) if t['layer']==result.get('selectedLayer')), 0 if len(self.targets)==1 else -1)
        if index >= 0:
            self.combo.current(index)
            self.selected = dict(self.targets[index])
            self.show_target()
        else:
            self.selected = None
            self.target_text.set('')
            self.document_text.set(result.get('documentName') or 'Photoshop не открыт')
            self.detail_text.set('Нажмите «Открыть RAW».' if not self.targets else 'В документе несколько Sony RAW. Выберите нужный в списке.')

    def drain(self):
        try:
            while True:
                event, value = self.events.get_nowait()
                if event == 'drop':
                    if self.busy or self.controller.pending or self.controller.recovery or self.controller.comparison:
                        self.status_text.set('Сначала завершите текущую проявку.')
                    elif len(value) != 1 or Path(value[0]).suffix.lower() != '.arw' or not Path(value[0]).is_file():
                        self.status_text.set('Перетащите один файл Sony ARW.')
                    else:
                        self.open_path(value[0])
                elif event == 'progress':
                    self.status_text.set(value)
                elif event in ('done', 'error'):
                    name, result, seconds = value
                    if name == 'scan':
                        self.scanning = False
                        if event == 'done':
                            self.scanned(result)
                        elif not self.last_error:
                            self.status_text.set('Photoshop недоступен или занят. Запустите его и закройте диалоги.')
                    else:
                        self.busy = False
                        self.bar.stop()
                        self.elapsed_text.set('')
                        if name in ('open', 'compare', 'compare_choose', 'apply'):
                            titles = {'open': 'Открытие', 'compare': 'Подготовка сравнения', 'compare_choose': 'Открытие полного размера',
                                      'apply': 'Повторный импорт' if self.retrying_import else 'Применение'}
                            self.duration_text.set('%s: %.1f с%s' % (titles[name], seconds, ' · ошибка' if event == 'error' else ''))
                            if event == 'done' and self.opening_seconds:
                                self.duration_text.set('Открытие и первая проявка: %.1f с\nПрименение: %.1f с · время настройки в Sony не включено' % (self.opening_seconds+seconds, seconds))
                        if event == 'error':
                            self.last_error = result
                            self.status_label.configure(foreground='#efad96')
                            self.status_text.set(result)
                        elif name == 'compare':
                            view = result['view']
                            self.status_text.set('Сравнение %d × %d. Переключайте Sony / Adobe и выберите проявщик.' % (view['width'],view['height']))
                        elif name == 'compare_show':
                            engine = (self.controller.comparison or {}).get('shown', 'sony')
                            self.status_text.set('Показан Sony.' if engine == 'sony' else 'Показан Adobe Camera ST.')
                        elif name == 'compare_close':
                            self.status_text.set('Сравнение закрыто.' if result.get('closed') else 'Изменённое сравнение оставлено открытым, его файлы сохранены.')
                            self.root.after(100, self.scan)
                        elif name == 'compare_choose':
                            if result.get('engine') == 'adobe':
                                self.status_text.set('Adobe Camera ST · полный RAW-смарт-объект. Настройки — двойным щелчком по слою.')
                            else:
                                self.selected = dict(result['target'])
                                self.status_text.set('Sony · рабочий документ в полном разрешении. Уменьшение не перенесено в результат.')
                            self.root.after(100, self.scan)
                        elif name == 'edit':
                            self.status_text.set('Настройте изображение в Sony, затем нажмите «Применить».')
                            self.show_target()
                        elif name == 'open' and result.get('prepared'):
                            self.show_target()
                            self.status_text.set('Настройте RAW в Sony и нажмите «Применить». Первый экспорт пропущен.')
                        elif name == 'open' and result.get('engine') == 'adobe':
                            self.status_text.set('Adobe Camera ST · RAW-смарт-объект. Для коррекции дважды щёлкните по слою.')
                            self.root.after(100, self.scan)
                        elif name in ('open', 'apply'):
                            self.selected = dict(result['target'])
                            self.show_target()
                            if result.get('unchanged'):
                                self.status_text.set('Изображение уже актуально. TIFF и перепроявка не потребовались (%.1f с).' % result['seconds'])
                            else:
                                self.status_text.set('Готово за %.1f с. %s' % (result['seconds'],
                                    'Временный TIFF удалён.' if result['cleaned'] else 'Кэш занят; очистится позже.'))
                            self.scanning = True
                            self.jobs.put(('scan', self.controller.status))
                        elif name == 'cancel':
                            self.selected = None
                            self.targets = []
                            self.opening_seconds = 0
                            self.document_text.set('Операция отменена')
                            self.detail_text.set('Можно открыть другой RAW. Данные отменённой операции сохранены.')
                            self.status_text.set('Отменено без изменения исходника и документов Photoshop.')
                        elif name == 'defer':
                            self.status_text.set('Рецепт сохранён отдельно. Photoshop не изменён.')
                            self.root.after(100, self.scan)
                        elif name in ('startup', 'discover'):
                            missing = [label for key,label in (('sony','Sony Edit'),('photoshop','Photoshop')) if not result.get(key)]
                            self.status_text.set('Не найдены: ' + ', '.join(missing) + '. Запустите программы вручную и повторите поиск через ⋯.' if missing else 'Sony Edit и Photoshop найдены. Можно открывать RAW.')
                        elif name == 'warmup':
                            self.status_text.set('Sony готов. Откройте RAW или выберите его документ в Photoshop.')
                        elif name == 'cleanup':
                            self.status_text.set('Освобождено %.1f МБ. Неподтверждённых заданий: %d.' %
                                                 (result['bytes_freed']/1000000, result['skipped']))
                    self.buttons()
        except queue.Empty:
            pass
        if not self.closed:
            self.root.after(70, self.drain)

    def clock(self):
        self.heartbeats += 1
        if self.busy:
            self.elapsed_text.set('%.0f с · не переключайте снимок в Sony' % (time.monotonic()-self.started))
        else:
            self.elapsed_text.set('')
        if self.heartbeats % 12 == 0:
            self.scan()
        if not self.closed:
            self.root.after(250, self.clock)

    def help(self):
        import os
        os.startfile(str(BUNDLE / 'PANEL.md'))

    def close(self):
        if self.busy:
            self.status_text.set('Дождитесь окончания операции перед закрытием панели.')
            return
        if self.controller.pending or self.controller.recovery:
            if not messagebox.askyesno(TITLE, 'Проявка ещё не применена. Закрыть панель?\nСостояние будет сохранено для следующего запуска.', parent=self.root):
                return
        self.closed = True
        self.jobs.put(None)
        for task in self.root.tk.call('after', 'info'):
            self.root.after_cancel(task)
        core.bridge.w.u.SetWindowLongPtrW(self.drop_hwnd, -4, self.old_wndproc)
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-warmup', action='store_true')
    parser.add_argument('--self-check', action='store_true')
    parser.add_argument('--verify-raw', type=Path)
    args = parser.parse_args()
    if args.self_check or args.verify_raw:
        from verification import self_check, workflow_check
        try:
            if args.verify_raw:
                workflow_check(runtime, args.verify_raw)
            else:
                self_check(runtime)
        except Exception:
            (ROOT / 'verification-error.log').write_text(traceback.format_exc(), encoding='utf-8')
            return 1
        return 0
    k = core.bridge.w.k
    mutex = k.CreateMutexW(None, False, 'Local\\SonyRawFloatingPanel')
    already = C.get_last_error() == 183
    if not mutex:
        raise C.WinError(C.get_last_error())
    try:
        if already:
            u = core.bridge.w.u
            u.FindWindowW.argtypes = [core.bridge.w.W.LPCWSTR, core.bridge.w.W.LPCWSTR]
            u.FindWindowW.restype = core.bridge.w.W.HWND
            h = u.FindWindowW(None, TITLE)
            if h:
                u.IsIconic.argtypes = [core.bridge.w.W.HWND]
                u.ShowWindow.argtypes = [core.bridge.w.W.HWND, C.c_int]
                u.SetForegroundWindow.argtypes = [core.bridge.w.W.HWND]
                if u.IsIconic(h):
                    u.ShowWindow(h, 9)
                u.SetForegroundWindow(h)
            return
        root = tk.Tk()
        Panel(root, warmup=not args.no_warmup)
        root.mainloop()
    finally:
        k.CloseHandle(mutex)


if __name__ == '__main__':
    try:
        sys.exit(main() or 0)
    except Exception:
        error_text = traceback.format_exc()
        (ROOT / 'startup-error.log').write_text(error_text, encoding='utf-8')
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror('Sony RAW Panel', 'Не удалось запустить панель. Подробности: ' + str(ROOT / 'startup-error.log') + '\n\n' + error_text.splitlines()[-1], parent=root)
        root.destroy()
        sys.exit(1)
