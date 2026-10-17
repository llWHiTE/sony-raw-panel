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
import development_profiles as profiles
ROOT = runtime.data_root()
BUNDLE = runtime.bundle_root()
spec = importlib.util.spec_from_file_location('panel_core', BUNDLE / 'panel_core.py')
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
TITLE = 'Sony RAW · Photoshop'


from advanced_panel import AdvancedPanel
from task_scheduler import Scheduler


class Panel(AdvancedPanel):
    def __init__(self, root, warmup=True, session=None):
        self.root = root
        self.events = queue.Queue()
        self.jobs = Scheduler()
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
        if (BUNDLE / 'SonyRAWPanel.ico').is_file():
            root.iconbitmap(default=str(BUNDLE / 'SonyRAWPanel.ico'))
        root.geometry('440x720+%d+40' % max(20, root.winfo_screenwidth()-480))
        root.minsize(380, 480)
        root.configure(bg='#262626')
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
        self.cleanup_warning = tk.BooleanVar(value=bool(prefs.get('cleanup_warning', True)))
        self.source_catalog = None
        self.prefetching = False
        self.sony_profile_override = None
        self.profile_preferences = prefs.get('camera_profiles', {}) if isinstance(prefs.get('camera_profiles'), dict) else {}
        self.adobe_profile = tk.StringVar(value='Camera Standard')
        self.sony_profile = tk.StringVar(value='Camera Standard')
        self.source_text = tk.StringVar(value='Добавьте RAW — профили определятся без проявки')
        self.preparation_text = tk.StringVar(value='')
        from lut_library import Library
        self.lut_library = Library(ROOT, BUNDLE)
        self.lut_text = tk.StringVar(value='Без LUT')
        self.build()
        if self.controller.comparison:
            self.lut_text.set(self.comparison_lut_label())
        self.install_drop()
        self.setup_advanced(prefs)
        root.attributes('-topmost', self.pinned.get())
        for preference in (self.preview_size, self.engine, self.first_sony, self.pinned, self.cleanup_warning):
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
        style.configure('Sony.TFrame', background='#262626')
        style.configure('Sony.TLabel', background='#262626', foreground='#e0e0e0', font=('Segoe UI', 10))
        style.configure('Muted.TLabel', background='#262626', foreground='#b5b5b5', font=('Segoe UI', 9))
        style.configure('Heading.TLabel', background='#262626', foreground='#ffffff', font=('Segoe UI Semibold', 16))
        style.configure('Sony.TButton', background='#363636', foreground='#dedede', bordercolor='#505050',
                        lightcolor='#363636', darkcolor='#363636', relief='flat', borderwidth=1,
                        focuscolor='#83baff', focusthickness=1, font=('Segoe UI', 9), padding=(10, 6))
        style.map('Sony.TButton', background=[('disabled', '#2d2d2d'), ('pressed', '#2b2b2b'), ('active', '#424242')],
                  foreground=[('disabled', '#777777')], bordercolor=[('focus', '#83baff'), ('active', '#656565'), ('disabled', '#3c3c3c')],
                  lightcolor=[('active', '#424242'), ('disabled', '#2d2d2d')], darkcolor=[('active', '#424242'), ('disabled', '#2d2d2d')])
        style.configure('Accent.TButton', background='#1473e6', foreground='#ffffff', bordercolor='#1473e6',
                        lightcolor='#1473e6', darkcolor='#1473e6', relief='flat', borderwidth=1,
                        font=('Segoe UI Semibold', 10), padding=(10, 8))
        style.map('Accent.TButton', background=[('disabled', '#333333'), ('pressed', '#0d66d0'), ('active', '#2680eb')],
                  foreground=[('disabled', '#777777')], bordercolor=[('disabled', '#3c3c3c'), ('focus', '#a6ceff')],
                  lightcolor=[('disabled', '#333333'), ('active', '#2680eb')], darkcolor=[('disabled', '#333333'), ('active', '#2680eb')])
        style.configure('TButton', background='#363636', foreground='#dedede', bordercolor='#505050',
                        lightcolor='#363636', darkcolor='#363636', relief='flat', borderwidth=1, padding=(8, 5))
        style.map('TButton', background=[('active', '#424242')], foreground=[('disabled', '#777777')])
        style.layout('Quiet.Vertical.TScrollbar', [('Vertical.Scrollbar.trough', {'sticky':'ns', 'children':
                     [('Vertical.Scrollbar.thumb', {'expand':True, 'sticky':'nswe'})]})])
        style.configure('Quiet.Vertical.TScrollbar', background='#505050', troughcolor='#262626',
                        bordercolor='#262626', lightcolor='#505050', darkcolor='#505050',
                        relief='flat', borderwidth=0, width=8, gripcount=0)
        style.map('Quiet.Vertical.TScrollbar', background=[('pressed','#727272'),('active','#626262')],
                  lightcolor=[('active','#626262')], darkcolor=[('active','#626262')])
        style.configure('Sony.TCombobox', fieldbackground='#363636', background='#363636', foreground='#e0e0e0',
                        arrowcolor='#a5a5a5', bordercolor='#505050', lightcolor='#363636', darkcolor='#363636', borderwidth=1, padding=3)
        style.map('Sony.TCombobox', fieldbackground=[('disabled', '#303030'), ('readonly', '#3b3b3b')],
                  foreground=[('disabled', '#858585'), ('readonly', '#e0e0e0')],
                  selectbackground=[('readonly', '#3b3b3b')], selectforeground=[('readonly', '#e0e0e0')])
        self.root.option_add('*TCombobox*Listbox.background', '#333333')
        self.root.option_add('*TCombobox*Listbox.foreground', '#e0e0e0')
        self.root.option_add('*TCombobox*Listbox.selectBackground', '#1473e6')
        style.configure('Sony.Horizontal.TProgressbar', troughcolor='#333333', background='#1473e6', bordercolor='#333333', lightcolor='#1473e6', darkcolor='#1473e6', thickness=4)
        style.configure('Sony.TCheckbutton', background='#262626', foreground='#b5b5b5', font=('Segoe UI', 9))
        style.map('Sony.TCheckbutton', background=[('active', '#262626')], foreground=[('disabled', '#858585')])
        footer = ttk.Frame(self.root, padding=(18, 8, 18, 12), style='Sony.TFrame')
        footer.pack(side='bottom', fill='x')
        row = ttk.Frame(footer, style='Sony.TFrame')
        row.pack(fill='x')
        ttk.Checkbutton(row, text='Поверх окон', variable=self.pinned, style='Sony.TCheckbutton',
                        command=lambda: self.root.attributes('-topmost', self.pinned.get())).pack(side='left')
        self.tools = tk.Menubutton(row, text='⋯', bg='#262626', fg='#d6d6d6', relief='flat', font=('Segoe UI', 13))
        self.tools.pack(side='right')
        self.cleanup_button = ttk.Button(row, text='Очистить кэш', style='Sony.TButton', command=self.cleanup)
        self.cleanup_button.pack(side='right', padx=(6, 10))
        menu = tk.Menu(self.tools, tearoff=False)
        menu.add_command(label='Программы и пути…', command=self.paths_dialog)
        menu.add_command(label='О программе…', command=self.about)
        menu.add_command(label='Подготовить Sony', command=self.warmup)
        menu.add_checkbutton(label='Предупреждать при очистке кэша', variable=self.cleanup_warning)
        menu.add_command(label='Обновить список документов', command=self.scan)
        menu.add_command(label='Сохранить рецепт без применения', command=self.defer)
        menu.add_separator()
        menu.add_command(label='Инструкция', command=self.help)
        self.tools.configure(menu=menu)
        self.tools_menu = menu
        credit = ttk.Frame(footer, style='Sony.TFrame')
        credit.pack(fill='x', pady=(8, 0))
        ttk.Label(credit, text=AUTHOR, style='Muted.TLabel').pack(side='left')
        link = tk.Label(credit, text='GitHub ↗', fg='#83baff', bg='#262626', cursor='hand2', font=('Segoe UI', 9))
        link.pack(side='right')
        link.bind('<Button-1>', lambda _: self.github())

        area = ttk.Frame(self.root, style='Sony.TFrame')
        area.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(area, bg='#262626', highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(area, orient='vertical', style='Quiet.Vertical.TScrollbar', command=self.canvas.yview)
        self.scrollbar = scrollbar
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        frame = ttk.Frame(self.canvas, padding=(18, 14, 12, 8), style='Sony.TFrame')
        self.content_frame = frame
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
        self.add_button = ttk.Button(frame, text='Добавить RAW…', style='Sony.TButton', command=self.add_source)
        self.add_button.pack(fill='x', pady=(0, 6))
        label(self.source_text, 'Muted.TLabel', (0, 8))
        engine_row = ttk.Frame(frame, style='Sony.TFrame')
        engine_row.pack(fill='x', pady=(0, 6))
        ttk.Label(engine_row, text='Проявка при открытии:', style='Muted.TLabel').pack(side='left')
        self.engine_choice = ttk.Combobox(engine_row, textvariable=self.engine, values=['Sony', 'Adobe'], state='readonly', width=9)
        self.engine_choice.pack(side='right')
        self.first_check = ttk.Checkbutton(frame, text='Сначала настроить в Sony', variable=self.first_sony, style='Sony.TCheckbutton')
        self.first_check.pack(anchor='w', pady=(0, 10))
        for title, variable, attribute in (('Профиль Adobe:', self.adobe_profile, 'adobe_profile_choice'),
                                            ('Профиль Sony:', self.sony_profile, 'sony_profile_choice')):
            profile_row = ttk.Frame(frame, style='Sony.TFrame')
            profile_row.pack(fill='x', pady=(0, 6))
            ttk.Label(profile_row, text=title, style='Muted.TLabel').pack(side='left')
            choice = ttk.Combobox(profile_row, textvariable=variable, values=['Camera Standard'], state='readonly', width=23)
            choice.pack(side='right', fill='x', expand=True, padx=(8, 0))
            choice.bind('<<ComboboxSelected>>', self.profile_changed)
            setattr(self, attribute, choice)
        label(self.preparation_text, 'Muted.TLabel', (0, 6))
        lut_row = ttk.Frame(frame, style='Sony.TFrame')
        lut_row.pack(fill='x', pady=(0, 8))
        ttk.Label(lut_row, text='LUT / XMP:', style='Muted.TLabel').pack(side='left')
        self.lut_choice = ttk.Combobox(lut_row, textvariable=self.lut_text, values=self.lut_options(), state='readonly', width=20)
        self.lut_choice.pack(side='left', fill='x', expand=True, padx=(8, 5))
        self.lut_choice.bind('<<ComboboxSelected>>', self.change_comparison_lut)
        self.lut_manage = ttk.Button(lut_row, text='…', style='Sony.TButton', width=3, command=self.manage_luts)
        self.lut_manage.pack(side='right')
        self.engine.trace_add('write', lambda *_: self.buttons())
        self.open_button = ttk.Button(frame, text='Открыть в Photoshop', style='Sony.TButton', command=self.choose)
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
        for combo in (self.engine_choice, self.adobe_profile_choice, self.sony_profile_choice, self.lut_choice, self.quality, self.combo):
            combo.configure(style='Sony.TCombobox')
        self.bar = ttk.Progressbar(frame, mode='indeterminate', length=280, style='Sony.Horizontal.TProgressbar')
        self.bar.pack(fill='x', pady=(12, 6))
        self.status_label = label(self.status_text, 'Muted.TLabel', (0, 4))
        self.duration_label = label(self.duration_text, 'Sony.TLabel', (3, 0))
        label(self.elapsed_text, 'Muted.TLabel', (2, 0))
        ttk.Label(frame, text='Ctrl+O — открыть · Ctrl+Enter — применить', style='Muted.TLabel').pack(anchor='w', pady=(5, 0))

    def lut_options(self):
        return ['Без LUT'] + [p.name + (' · Adobe' if p.suffix.lower() == '.xmp' else '') for p in self.lut_library.entries()]

    def selected_lut_path(self):
        if self.lut_text.get() == 'Без LUT':
            return None
        for path in self.lut_library.entries():
            label = path.name + (' · Adobe' if path.suffix.lower() == '.xmp' else '')
            if label == self.lut_text.get():
                return path
        raise ValueError('Выбранный LUT удалён. Выберите другой или «Без LUT».')

    def snapshot_lut(self, path):
        return self.lut_library.snapshot(path) if path else None

    def selected_lut(self):
        return self.snapshot_lut(self.selected_lut_path())

    def comparison_lut_label(self):
        lut = (self.controller.comparison or {}).get('lut')
        return lut['name'] + '.' + lut['kind'] + (' · Adobe' if lut['kind'] == 'xmp' else '') if lut else 'Без LUT'

    def change_comparison_lut(self, _=None):
        if not self.controller.comparison or self.busy:
            return
        try:
            path = self.selected_lut_path()
        except (OSError, ValueError) as error:
            self.lut_text.set(self.comparison_lut_label())
            self.status_text.set(str(error))
            return
        self.submit('compare_lut', lambda: self.controller.set_comparison_lut(self.snapshot_lut(path)))

    def manage_luts(self):
        if self.busy:
            return
        window = tk.Toplevel(self.root)
        window.title('Библиотека LUT / XMP')
        window.transient(self.root)
        window.attributes('-topmost', True)
        frame = ttk.Frame(window, padding=18)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='.cube — отдельный слой для Sony и Adobe.\n.xmp — пресет Camera Raw, только Adobe.\nПо умолчанию обработка выключена.').pack(anchor='w', pady=(0, 8))
        listing = tk.Listbox(frame, width=42, height=10)
        listing.pack(fill='both', expand=True)
        def refresh():
            listing.delete(0, 'end')
            for path in self.lut_library.entries():
                listing.insert('end', path.name)
            self.lut_choice.configure(values=self.lut_options())
            if self.lut_text.get() not in self.lut_options():
                self.lut_text.set('Без LUT')
        def add():
            paths = filedialog.askopenfilenames(parent=window, title='Добавить LUT / XMP', filetypes=[('LUT / Adobe preset', '*.cube *.xmp')])
            for path in paths:
                try:
                    self.lut_library.add(path)
                except (ValueError, OSError) as error:
                    messagebox.showerror(TITLE, str(error), parent=window)
            refresh()
        def remove():
            selected = listing.curselection()
            if selected:
                path = self.lut_library.entries()[selected[0]]
                if messagebox.askyesno(TITLE, 'Удалить из библиотеки: ' + path.name + '?\nИсходный файл и уже открытые документы сохранятся.', parent=window):
                    self.lut_library.remove(path)
                    refresh()
        ttk.Button(frame, text='Добавить .cube / .xmp…', command=add).pack(fill='x', pady=(8, 4))
        ttk.Button(frame, text='Удалить выбранный', command=remove).pack(fill='x', pady=4)
        ttk.Button(frame, text='Закрыть', command=window.destroy).pack(fill='x', pady=4)
        refresh()

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
            preview_mode=self.preview_mode, custom_percent=self.custom_percent, pinned=self.pinned.get(),
            cleanup_warning=self.cleanup_warning.get(), camera_profiles=self.profile_preferences,
            **self.advanced_preferences()))

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
            handled = self.native_message(message, wp, lp)
            if handled is not None:
                return handled
            if message == 0x0233:
                paths = []
                try:
                    count = shell.DragQueryFileW(wp, 0xffffffff, None, 0)
                    for i in range(min(count, 256)):
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
                from advanced_core import Deferred
                if isinstance(error, Deferred) and name.startswith('background_'):
                    self.events.put(('error', (name, str(error), time.monotonic()-started)))
                    continue
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
        self.status_label.configure(foreground='#b5b5b5')
        waiting = self.jobs.active and self.jobs.active.name.startswith('background_') and self.background_jobs
        self.status_text.set('Дождитесь окончания текущей фоновой операции; ваша команда следующая.' if waiting else 'Выполняю…')
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
        self.add_button.configure(state='normal' if idle else 'disabled')
        profile_ready = free or (idle and comparison and comparison.get('view') and not pending and not recovery)
        self.adobe_profile_choice.configure(state='readonly' if profile_ready and self.source_catalog and self.source_catalog['adobe'] else 'disabled')
        self.sony_profile_choice.configure(state='readonly' if profile_ready and self.source_catalog else 'disabled')
        self.engine_choice.configure(state='readonly' if free else 'disabled')
        self.lut_choice.configure(state='readonly' if free or (idle and comparison and comparison.get('view') and not pending and not recovery) else 'disabled')
        self.lut_manage.configure(state='normal' if free else 'disabled')
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
            look = comparison.get('lut')
            note = (' XMP только Adobe: ' if look.get('kind') == 'xmp' else ' LUT: ') + look['name'] if look else ''
            sony_label = comparison.get('sonyProfile', {}).get('label', 'сохранённый рецепт')
            adobe_label = comparison.get('adobeProfileLabel', comparison.get('adobeProfile', 'Camera Standard'))
            self.detail_text.set('Sony: %s · Adobe: %s. Профили сохранятся в полном размере.%s' % (sony_label, adobe_label, note))
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
        self.cleanup_button.configure(state='normal' if idle and not pending and not recovery else 'disabled')
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
        if not self.selected and not pending and not recovery and not comparison:
            self.edit_button.pack_forget()
            self.apply_button.pack_forget()

    def selected_profiles(self):
        result = {}
        for engine, variable in (('adobe', self.adobe_profile), ('sony', self.sony_profile)):
            options = (self.source_catalog or {}).get(engine, [])
            selected = next((item['id'] for item in options if item['label'] == variable.get()), profiles.DEFAULT)
            result[engine + '_profile'] = selected
        return result

    def set_catalog(self, catalog):
        previous = self.selected_profiles() if self.source_catalog and self.source_catalog['model'] == catalog['model'] else {}
        self.source_catalog = catalog
        stored = self.profile_preferences.get(catalog['model'], {})
        if not isinstance(stored, dict):
            stored = {}
        for engine, variable, choice in (('adobe', self.adobe_profile, self.adobe_profile_choice),
                                        ('sony', self.sony_profile, self.sony_profile_choice)):
            options = catalog[engine]
            desired = previous.get(engine + '_profile', stored.get(engine, profiles.DEFAULT))
            selected = next((item for item in options if item['id'] == desired), None)
            selected = selected or next((item for item in options if item['id'] == profiles.DEFAULT), None)
            variable.set(selected['label'] if selected else 'Профили не установлены')
            choice.configure(values=[item['label'] for item in options])
        self.source_text.set('%s · %s' % (Path(catalog['source']).name, catalog['model']))
        self.sony_profile_override = None
        self.preparation_text.set('Профили: %.0f мс%s. %s' % (catalog['seconds'] * 1000,
            ' · кэш' if catalog['cached'] else '', catalog['sony_origin']))

    def profile_changed(self, event=None):
        if self.controller.comparison and event is not None:
            engine = 'sony' if event.widget == self.sony_profile_choice else 'adobe'
            profile = self.selected_profiles()[engine + '_profile']
            self.submit('compare_profile', lambda: self.controller.set_comparison_profile(engine, profile))
            return
        if self.source_catalog:
            selected = self.selected_profiles()
            self.profile_preferences[self.source_catalog['model']] = dict(adobe=selected['adobe_profile'], sony=selected['sony_profile'])
            if event is not None and event.widget == self.sony_profile_choice:
                self.sony_profile_override = selected['sony_profile']
            row = self.raw_queue.selected() if hasattr(self, 'raw_queue') else None
            if row and Path(row['source']) == Path(self.source_catalog['source']):
                row['settings'] = dict(selected)
                self.raw_queue.save()
            self.save_preferences()

    def add_source(self):
        if self.busy:
            return
        paths = filedialog.askopenfilenames(parent=self.root, title='Добавить Sony RAW без проявки', filetypes=[('Sony RAW', '*.arw *.ARW')])
        if paths:
            self.receive_files(paths)

    def stage_source(self, path):
        engine = self.engine.get().lower()
        def work():
            catalog = self.controller.profile_catalog(Path(path))
            catalog['prefetch_engine'] = engine
            return catalog
        self.submit('profiles', work)

    def choose(self):
        if self.busy or self.controller.pending or self.controller.recovery or self.controller.comparison:
            return
        if self.source_catalog:
            self.open_path(self.source_catalog['source'])
        else:
            self.add_source()

    def open_path(self, path):
        if not self.source_catalog or Path(self.source_catalog['source']).resolve() != Path(path).resolve():
            self.stage_source(path)
            return
        selected_profiles = self.selected_profiles()
        first_sony = self.first_sony.get()
        engine = self.engine.get().lower()
        try:
            lut_path = self.selected_lut_path()
        except (OSError, ValueError) as error:
            self.status_text.set(str(error))
            return
        self.submit('open', lambda: self.controller.open(Path(path), first_sony=first_sony, engine=engine, lut=self.snapshot_lut(lut_path), **selected_profiles))

    def compare(self):
        if self.busy or self.controller.pending or self.controller.recovery:
            return
        if self.controller.comparison:
            engine = 'adobe' if self.controller.comparison.get('shown', 'sony') == 'sony' else 'sony'
            self.show_compare(engine)
            return
        if not self.source_catalog:
            self.add_source()
            return
        source = self.source_catalog['source']
        if source:
            selected_profiles = self.selected_profiles()
            percent = self.preview_percent
            try:
                lut_path = self.selected_lut_path()
            except (OSError, ValueError) as error:
                self.status_text.set(str(error))
                return
            self.submit('compare', lambda: self.controller.compare(Path(source), percent, lut=self.snapshot_lut(lut_path), **selected_profiles))

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
            selected_profile = self.sony_profile_override
            self.submit('edit', lambda: self.controller.edit(dict(target), sony_profile=selected_profile))

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
        if self.busy or self.scanning or self.controller.pending or self.controller.recovery:
            return
        def run():
            self.submit('cleanup', lambda: self.controller.cleanup(purge_all=True))
        if not self.cleanup_warning.get():
            run()
            return
        window = tk.Toplevel(self.root)
        window.title('Очистить кэш')
        window.transient(self.root)
        window.attributes('-topmost', True)
        frame = ttk.Frame(window, padding=18)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Будут закрыты неизменённые служебные превью Photoshop\nи Sony, удалён подтверждённый временный кэш.\n\nВ Photoshop очистятся кэши ВСЕХ документов, включая\nисторию отмены и буфер обмена. Это необратимо.\nРабочие документы останутся открыты; ARW и рецепты сохранятся.', wraplength=440).pack(anchor='w', pady=(0, 12))
        skip = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text='Больше не показывать', variable=skip).pack(anchor='w', pady=(0, 10))
        def confirm():
            self.cleanup_warning.set(not skip.get())
            window.destroy()
            run()
        ttk.Button(frame, text='Очистить кэш', command=confirm).pack(fill='x', pady=4)
        ttk.Button(frame, text='Отмена', command=window.destroy).pack(fill='x', pady=4)
        window.bind('<Escape>', lambda _: window.destroy())
        window.grab_set()

    def defer(self):
        if self.busy or not self.controller.pending:
            return
        if messagebox.askyesno(TITLE, 'Сохранить текущий рецепт отдельно, не обновляя Photoshop?\nДокумент останется с предыдущей проявкой.', parent=self.root):
            self.submit('defer', self.controller.defer)

    def scan(self):
        if not self.closed and not self.busy and not self.prefetching and not self.scanning and not self.controller.pending and not self.controller.recovery and not self.controller.comparison:
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
            if not self.source_catalog and self.selected.get('profile_catalog'):
                self.set_catalog(self.selected['profile_catalog'])
                self.controller.catalog = self.selected['profile_catalog']
            self.show_target()
        else:
            self.selected = None
            self.target_text.set('')
            self.document_text.set(result.get('documentName') or ('Нет открытого документа Photoshop' if result.get('running') else 'Photoshop не открыт'))
            self.detail_text.set(('Профили готовы. Откройте файл или сравните Sony / Adobe.' if self.source_catalog else 'Добавьте RAW и выберите профили перед открытием.') if not self.targets else 'В документе несколько Sony RAW. Выберите нужный в списке.')

    def drain(self):
        try:
            while True:
                event, value = self.events.get_nowait()
                if self.advanced_event(event, value):
                    continue
                if event == 'drop':
                    self.receive_files(value)
                elif event == 'progress':
                    self.status_text.set(value)
                elif event in ('done', 'error'):
                    name, result, seconds = value
                    if name == 'prefetch':
                        self.prefetching = False
                        if event == 'done':
                            self.preparation_text.set('Рабочая копия готова · %.2f с. Без открытия и проявки.' % seconds)
                        elif not self.busy:
                            self.preparation_text.set('Фоновая копия не готова: ' + str(result))
                        self.buttons()
                        continue
                    if name == 'scan':
                        self.scanning = False
                        if event == 'done':
                            self.scanned(result)
                        elif not self.last_error:
                            self.status_text.set('Photoshop недоступен или занят. Запустите его и закройте диалоги.')
                    else:
                        self.busy = False
                        self.bar.stop()
                        self.bar.configure(value=0)
                        self.elapsed_text.set('')
                        if name in ('open', 'compare', 'compare_choose', 'compare_lut', 'compare_profile', 'apply'):
                            titles = {'open': 'Открытие', 'compare': 'Подготовка сравнения', 'compare_choose': 'Открытие полного размера',
                                      'compare_lut': 'Смена LUT / XMP', 'compare_profile': 'Смена профиля', 'apply': 'Повторный импорт' if self.retrying_import else 'Применение'}
                            self.duration_text.set('%s: %.1f с%s' % (titles[name], seconds, ' · ошибка' if event == 'error' else ''))
                            if event == 'done' and self.opening_seconds:
                                self.duration_text.set('Открытие и первая проявка: %.1f с\nПрименение: %.1f с · время настройки в Sony не включено' % (self.opening_seconds+seconds, seconds))
                        if name == 'compare_lut':
                            self.lut_text.set(self.comparison_lut_label())
                        if event == 'error':
                            self.last_error = result
                            self.status_label.configure(foreground='#ff9d9d')
                            self.status_text.set(result)
                        elif name == 'profiles':
                            self.set_catalog(result)
                            self.status_text.set('RAW добавлен без проявки. Выберите профили, затем откройте или сравните.')
                            self.prefetching = True
                            source, engine = result['source'], result['prefetch_engine']
                            self.jobs.put(('prefetch', lambda source=source, engine=engine: self.controller.prefetch(Path(source), engine=engine)))
                        elif name == 'compare':
                            view = result['view']
                            self.status_text.set('Сравнение %d × %d. Переключайте Sony / Adobe и выберите проявщик.' % (view['width'],view['height']))
                        elif name == 'compare_lut':
                            self.status_text.set('XMP обновлён только в Adobe; Sony не перепроявлялся.' if result.get('adobe_rendered') else 'LUT изменён в готовом сравнении. RAW не перепроявлялся.')
                        elif name == 'compare_profile':
                            self.status_text.set('Профиль обновлён только в выбранной ветке сравнения.')
                        elif name == 'compare_show':
                            engine = (self.controller.comparison or {}).get('shown', 'sony')
                            self.status_text.set('Показан Sony.' if engine == 'sony' else 'Показан Adobe: ' + (self.controller.comparison or {}).get('adobeProfile', 'Camera ST'))
                        elif name == 'compare_close':
                            self.status_text.set('Сравнение закрыто.' if result.get('closed') else 'Изменённое сравнение оставлено открытым, его файлы сохранены.')
                            self.root.after(100, self.scan)
                        elif name == 'compare_choose':
                            if result.get('engine') == 'adobe':
                                self.status_text.set('Adobe · полный RAW-смарт-объект. Настройки — двойным щелчком по слою.')
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
                            self.status_text.set('Adobe · RAW-смарт-объект. Для коррекции дважды щёлкните по слою.')
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
                            self.status_text.set('Освобождено %.1f МБ. Превью Photoshop: %d, вкладок Sony: %d. %s%s' %
                                (result['bytes_freed']/1000000, result['previews_closed'], result['sony_closed'],
                                 'Кэш Photoshop очищен. ' if result['photoshop_purged'] else '',
                                 'Часть данных сохранена: ' + '; '.join(result['warnings']) if result['warnings'] else ''))
                            self.duration_text.set('Очистка кэша: %.1f с' % seconds)
                            if not self.controller.comparison:
                                self.document_text.set('Очистка завершена')
                                self.detail_text.set('Изменённые превью и рабочие проекты не удаляются.')
                            self.root.after(100, self.scan)
                    if event == 'done' and name in ('open', 'compare', 'edit', 'apply') and self.source_catalog:
                        try:
                            self.set_catalog(self.controller.profile_catalog(self.source_catalog['source']))
                        except (OSError, ValueError):
                            pass
                    self.after_operation(event, name, result)
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
        interval = 12 if self.foreground.kind() in ('panel', 'photoshop', 'sony') and self.root.state() != 'withdrawn' else 120
        if self.heartbeats % interval == 0:
            self.scan()
        if not self.closed:
            self.root.after(250, self.clock)

    def help(self):
        import os
        os.startfile(str(BUNDLE / 'PANEL.md'))

    def close(self):
        if self.jobs.active and self.jobs.active.name.startswith('background_') and self.background_jobs:
            self.status_text.set('Дождитесь завершения фоновой операции перед выходом.')
            return
        if self.busy:
            self.status_text.set('Дождитесь окончания операции перед закрытием панели.')
            return
        if self.controller.pending or self.controller.recovery:
            if not messagebox.askyesno(TITLE, 'Проявка ещё не применена. Закрыть панель?\nСостояние будет сохранено для следующего запуска.', parent=self.root):
                return
        self.close_advanced()
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
    parser.add_argument('raws', nargs='*', type=Path)
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
    import windows_integration as win
    mutex = k.CreateMutexW(None, False, 'Local\\' + win.channel(ROOT))
    already = C.get_last_error() == 183
    if not mutex:
        raise C.WinError(C.get_last_error())
    try:
        if already:
            core.bridge.w.wait(lambda: win.forward(ROOT, args.raws), 10, 'Панель запускается или не отвечает. Повторите отправку файлов.')
            return
        shell = C.WinDLL('shell32', use_last_error=True)
        shell.SetCurrentProcessExplicitAppUserModelID.argtypes = [core.bridge.w.W.LPCWSTR]
        shell.SetCurrentProcessExplicitAppUserModelID('AlexeyStorozhilov.SonyRAWPanel')
        root = tk.Tk()
        panel = Panel(root, warmup=not args.no_warmup)
        if args.raws:
            # Initial scan/startup may still be queued: receipt never replaces active work.
            root.after(400, lambda: panel.receive_files(args.raws))
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
