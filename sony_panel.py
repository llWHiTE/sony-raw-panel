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
        root.title(TITLE)
        root.geometry('400x700+%d+60' % max(40, root.winfo_screenwidth()-440))
        root.minsize(380, 680)
        root.configure(bg='#20242c')
        root.attributes('-topmost', True)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.status_text = tk.StringVar(value='Подключение к Photoshop…')
        self.document_text = tk.StringVar(value='Нет открытого Sony RAW')
        self.detail_text = tk.StringVar(value='Откройте ARW или документ PSD со слоем Sony RAW.')
        self.elapsed_text = tk.StringVar(value='')
        self.target_text = tk.StringVar()
        try:
            prefs = json.loads((ROOT / 'ui-preferences.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            prefs = {}
        self.preview_size = tk.StringVar(value=prefs.get('preview_size', 'Быстро · 1600 px'))
        if self.preview_size.get() not in ('Быстро · 1600 px', 'Детальнее · 3000 px', 'Полное разрешение'):
            self.preview_size.set('Быстро · 1600 px')
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
        style.configure('Sony.TButton', font=('Segoe UI', 10), padding=(12, 9))
        style.configure('Accent.TButton', background='#5393ce', foreground='#ffffff', font=('Segoe UI Semibold', 11), padding=(12, 11))
        style.map('Accent.TButton', background=[('disabled', '#3e4a58'), ('active', '#67a3db')])
        style.configure('Sony.TCheckbutton', background='#20242c', foreground='#aeb7c6', font=('Segoe UI', 9))
        frame = ttk.Frame(self.root, padding=18, style='Sony.TFrame')
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Sony RAW', style='Heading.TLabel').pack(anchor='w')
        ttk.Label(frame, text='Настоящая проявка Sony → Photoshop', style='Muted.TLabel').pack(anchor='w', pady=(2, 16))
        engine_row = ttk.Frame(frame, style='Sony.TFrame')
        engine_row.pack(fill='x', pady=(0, 5))
        ttk.Label(engine_row, text='Проявка при открытии:', style='Muted.TLabel').pack(side='left')
        self.engine_choice = ttk.Combobox(engine_row, textvariable=self.engine, values=['Sony', 'Adobe'], state='readonly', width=9)
        self.engine_choice.pack(side='right')
        self.first_check = ttk.Checkbutton(frame, text='Сначала настроить в Sony', variable=self.first_sony, style='Sony.TCheckbutton')
        self.first_check.pack(anchor='w', pady=(0, 8))
        self.engine.trace_add('write', lambda *_: self.buttons())
        self.open_button = ttk.Button(frame, text='＋  Открыть RAW…', style='Sony.TButton', command=self.choose)
        self.open_button.pack(fill='x')
        compare_row = ttk.Frame(frame, style='Sony.TFrame')
        compare_row.pack(fill='x', pady=(7, 0))
        self.compare_button = ttk.Button(compare_row, text='Сравнить…', style='Sony.TButton', command=self.compare)
        self.compare_button.pack(side='left')
        self.quality = ttk.Combobox(compare_row, textvariable=self.preview_size, state='readonly', width=22,
            values=['Быстро · 1600 px', 'Детальнее · 3000 px', 'Полное разрешение'])
        self.quality.pack(side='right', padx=(7, 0), fill='x', expand=True)
        self.compare_frame = ttk.Frame(frame, style='Sony.TFrame')
        self.compare_frame.pack(fill='x')
        self.compare_switch = ttk.Frame(self.compare_frame, style='Sony.TFrame')
        self.sony_view = ttk.Button(self.compare_switch, text='Показать Sony', command=lambda: self.show_compare('sony'))
        self.sony_view.pack(side='left', fill='x', expand=True)
        self.adobe_view = ttk.Button(self.compare_switch, text='Adobe · Camera ST', command=lambda: self.show_compare('adobe'))
        self.adobe_view.pack(side='left', fill='x', expand=True, padx=(5, 0))
        self.use_sony = ttk.Button(self.compare_frame, text='Использовать Sony · полный размер', command=lambda: self.choose_engine('sony'))
        self.use_adobe = ttk.Button(self.compare_frame, text='Использовать Adobe · полный RAW', command=lambda: self.choose_engine('adobe'))
        self.cancel_compare = ttk.Button(self.compare_frame, text='Закрыть сравнение', command=self.close_compare)
        ttk.Label(frame, textvariable=self.document_text, style='Sony.TLabel', wraplength=340).pack(anchor='w', pady=(18, 4))
        self.combo = ttk.Combobox(frame, state='readonly', textvariable=self.target_text)
        self.combo.pack(fill='x', pady=(0, 5))
        self.combo.bind('<<ComboboxSelected>>', self.select)
        ttk.Label(frame, textvariable=self.detail_text, style='Muted.TLabel', wraplength=340).pack(anchor='w', pady=(0, 12))
        self.edit_button = ttk.Button(frame, text='Изменить проявку в Sony', style='Sony.TButton', command=self.edit)
        self.edit_button.pack(fill='x', pady=(0, 7))
        self.apply_button = ttk.Button(frame, text='Применить в Photoshop', style='Accent.TButton', command=self.apply)
        self.apply_button.pack(fill='x')
        self.bar = ttk.Progressbar(frame, mode='indeterminate', length=280)
        self.bar.pack(fill='x', pady=(15, 6))
        ttk.Label(frame, textvariable=self.status_text, style='Muted.TLabel', wraplength=340).pack(anchor='w')
        ttk.Label(frame, textvariable=self.elapsed_text, style='Muted.TLabel').pack(anchor='w', pady=(3, 5))
        credit = ttk.Frame(frame, style='Sony.TFrame')
        credit.pack(fill='x', side='bottom', pady=(8, 0))
        ttk.Label(credit, text=AUTHOR, style='Muted.TLabel').pack(side='left')
        link = tk.Label(credit, text='GitHub ↗', fg='#81b8ec', bg='#20242c', cursor='hand2', font=('Segoe UI', 9))
        link.pack(side='right')
        link.bind('<Button-1>', lambda _: self.github())
        footer = ttk.Frame(frame, style='Sony.TFrame')
        footer.pack(fill='x', side='bottom', pady=(8, 0))
        ttk.Checkbutton(footer, text='Поверх окон', variable=self.pinned, style='Sony.TCheckbutton',
                        command=lambda: self.root.attributes('-topmost', self.pinned.get())).pack(side='left')
        self.tools = tk.Menubutton(footer, text='⋯', bg='#20242c', fg='#d8dce4', relief='flat', font=('Segoe UI', 13))
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

    def save_preferences(self, *_):
        core.bridge.atomic_json(ROOT / 'ui-preferences.json', dict(engine=self.engine.get(),
            first_sony=self.first_sony.get(), preview_size=self.preview_size.get(), pinned=self.pinned.get()))

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
            try:
                result = function()
                self.events.put(('done', (name, result)))
            except Exception as error:
                logs = ROOT / 'panel-logs'
                logs.mkdir(exist_ok=True)
                with (logs / 'panel.log').open('a', encoding='utf-8') as f:
                    f.write('\n' + time.strftime('%Y-%m-%d %H:%M:%S ') + name + '\n' + traceback.format_exc())
                self.events.put(('error', (name, str(error))))

    def submit(self, name, function):
        if self.busy:
            return False
        self.busy = True
        self.started = time.monotonic()
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
        self.engine_choice.configure(state='readonly' if idle and not pending and not recovery and not comparison else 'disabled')
        self.first_check.configure(state='normal' if idle and self.engine.get() == 'Sony' and not pending and not comparison else 'disabled')
        self.compare_button.configure(state='normal' if idle and not pending and not recovery and not comparison else 'disabled')
        self.quality.configure(state='readonly' if idle and not comparison else 'disabled')
        for button in (self.sony_view, self.adobe_view, self.use_sony, self.use_adobe):
            button.configure(state='normal' if idle and comparison and comparison.get('view') and not recovery else 'disabled')
        self.cancel_compare.configure(state='normal' if idle and comparison and not recovery else 'disabled')
        if comparison:
            if not self.compare_switch.winfo_manager():
                self.compare_switch.pack(fill='x', pady=(10, 5))
                self.use_sony.pack(fill='x', pady=3)
                self.use_adobe.pack(fill='x', pady=3)
                self.cancel_compare.pack(fill='x', pady=3)
                self.edit_button.pack_forget()
                self.apply_button.pack_forget()
                self.root.geometry('400x780')
                self.root.minsize(380, 760)
            if recovery:
                self.apply_button.pack(fill='x', before=self.bar)
            else:
                self.apply_button.pack_forget()
            self.document_text.set('Сравнение · ' + str(comparison['edge'] or 'полное') + (' px' if comparison['edge'] else ''))
            self.detail_text.set('Предпросмотр. Выбор ниже создаст рабочий документ в полном разрешении.')
        elif self.compare_switch.winfo_manager():
            for widget in (self.compare_switch, self.use_sony, self.use_adobe, self.cancel_compare):
                widget.pack_forget()
            self.edit_button.pack(fill='x', pady=(0, 7), before=self.bar)
            self.apply_button.pack(fill='x', before=self.bar)
            self.root.geometry('400x700')
            self.root.minsize(380, 680)
        self.open_button.configure(state='normal' if idle and not pending and not recovery and not comparison else 'disabled')
        self.edit_button.configure(state='normal' if idle and (self.selected or pending) and not recovery and not comparison else 'disabled')
        self.apply_button.configure(state='normal' if idle and (pending or recovery) else 'disabled',
                                    text='Повторить импорт в Photoshop' if recovery else 'Применить в Photoshop')
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
        if self.busy or self.controller.pending or self.controller.recovery or self.controller.comparison:
            return
        source = filedialog.askopenfilename(parent=self.root, title='Сравнить Sony / Adobe Camera ST', filetypes=[('Sony RAW', '*.arw *.ARW')])
        if source:
            edge = {'Быстро · 1600 px':1600, 'Детальнее · 3000 px':3000, 'Полное разрешение':0}[self.preview_size.get()]
            self.submit('compare', lambda: self.controller.compare(Path(source), edge))

    def show_compare(self, engine):
        self.submit('compare_show', lambda: self.controller.show_comparison(engine))

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
                    name, result = value
                    if name == 'scan':
                        self.scanning = False
                        if event == 'done':
                            self.scanned(result)
                        else:
                            self.status_text.set('Photoshop занят. Закройте его диалог и повторите команду.')
                    else:
                        self.busy = False
                        self.bar.stop()
                        if event == 'error':
                            self.status_text.set(result)
                        elif name == 'compare':
                            view = result['view']
                            self.status_text.set('Сравнение %d × %d. Переключайте Sony / Adobe и выберите проявщик.' % (view['width'],view['height']))
                        elif name == 'compare_show':
                            self.status_text.set('Показан выбранный вариант. Рабочий RAW остаётся полноразмерным.')
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
            self.elapsed_text.set('Ctrl+O — открыть · Ctrl+Enter — применить')
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
