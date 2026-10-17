"""Opt-in Windows shortcuts, context visibility and bounded file-only IPC."""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

import sony_windows as w

WM_COPYDATA = 0x004A
WM_HOTKEY = 0x0312
MAGIC = 0x53525038
MAX_BYTES = 256 * 1024
DEFAULT_KEYS = {'edit': 'Ctrl+Alt+Shift+S', 'apply': 'Ctrl+Alt+Shift+Enter', 'toggle': 'Ctrl+Alt+Shift+P'}


class CopyData(C.Structure):
    _fields_ = [('dwData', C.c_size_t), ('cbData', W.DWORD), ('lpData', C.c_void_p)]


def channel(root):
    return 'SonyRawPanel-' + hashlib.sha256(str(Path(root).resolve()).casefold().encode('utf-8')).hexdigest()[:24]


def encode_paths(paths):
    values = [str(Path(path).resolve(strict=True)) for path in paths]
    if len(values) > 256 or any(Path(path).suffix.lower() != '.arw' or not Path(path).is_file() for path in values):
        raise ValueError('Передайте не более 256 существующих ARW.')
    payload = json.dumps(dict(version=1, files=values), ensure_ascii=True).encode('ascii')
    if len(payload) > MAX_BYTES:
        raise ValueError('Список файлов слишком большой.')
    return payload


def decode_paths(payload):
    if not payload or len(payload) > MAX_BYTES:
        raise ValueError('Invalid IPC size.')
    data = json.loads(payload.decode('ascii'))
    if not isinstance(data, dict) or data.get('version') != 1 or set(data) != {'version', 'files'}:
        raise ValueError('Invalid file-only IPC protocol.')
    paths = data['files']
    if not isinstance(paths, list) or len(paths) > 256 or any(not isinstance(p, str) or not Path(p).is_absolute() for p in paths):
        raise ValueError('Invalid IPC paths.')
    encode_paths(paths)
    return paths


def set_channel(hwnd, name):
    w.u.SetPropW.argtypes = [W.HWND, W.LPCWSTR, W.HANDLE]
    if not w.u.SetPropW(hwnd, name, 1):
        raise C.WinError(C.get_last_error())


def clear_channel(hwnd, name):
    w.u.RemovePropW.argtypes = [W.HWND, W.LPCWSTR]
    w.u.RemovePropW(hwnd, name)


def forward(root, paths):
    w.u.GetPropW.argtypes = [W.HWND, W.LPCWSTR]
    w.u.GetPropW.restype = W.HANDLE
    name = channel(root)
    hwnd = next((h for h in w.windows() if w.u.GetPropW(h, name)), None)
    if not hwnd:
        return False
    payload = encode_paths(paths)
    buffer = C.create_string_buffer(payload)
    data = CopyData(MAGIC, len(payload), C.cast(buffer, C.c_void_p))
    return bool(w.send(hwnd, WM_COPYDATA, 0, C.addressof(data)))


def hotkey(value):
    parts = value.upper().split('+')
    if len(set(parts)) != len(parts) or len(parts) < 2:
        raise ValueError('Укажите сочетание, например Ctrl+Alt+Shift+S.')
    modifiers = 0
    for part in parts[:-1]:
        if part not in ('CTRL', 'ALT', 'SHIFT', 'WIN'):
            raise ValueError('Неизвестный модификатор клавиши.')
        modifiers |= {'CTRL': 2, 'ALT': 1, 'SHIFT': 4, 'WIN': 8}[part]
    key = parts[-1]
    vk = 13 if key == 'ENTER' else ord(key) if len(key) == 1 and key.isascii() and key.isalnum() else None
    if vk is None:
        raise ValueError('Используйте букву, цифру или Enter.')
    return modifiers | 0x4000, vk


class Hotkeys:
    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.registered = {}
        self.config = None
        w.u.RegisterHotKey.argtypes = [W.HWND, C.c_int, W.UINT, W.UINT]
        w.u.UnregisterHotKey.argtypes = [W.HWND, C.c_int]

    def close(self):
        for ident in self.registered:
            w.u.UnregisterHotKey(self.hwnd, ident)
        self.registered.clear()

    def configure(self, enabled, config=None):
        values = config or DEFAULT_KEYS
        parsed = {name: hotkey(values[name]) for name in DEFAULT_KEYS}
        if len(set(parsed.values())) != len(parsed):
            raise ValueError('Горячие клавиши должны различаться.')
        previous = self.config
        self.close()
        try:
            if enabled:
                for ident, (name, (modifiers, vk)) in enumerate(parsed.items(), 0x5100):
                    if not w.u.RegisterHotKey(self.hwnd, ident, modifiers, vk):
                        raise ValueError('Сочетание занято другой программой: ' + values[name])
                    self.registered[ident] = name
            self.config = (enabled, dict(values))
        except Exception:
            self.close()
            self.config = None
            if previous:
                self.configure(*previous)
            raise


class Foreground:
    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.cache = {}
        self.paths = {}
        w.u.GetForegroundWindow.restype = W.HWND
        w.u.IsIconic.argtypes = [W.HWND]

    def kind(self):
        hwnd = w.u.GetForegroundWindow()
        process = w.pid(hwnd) if hwnd else 0
        if process == os.getpid():
            return 'panel'
        now = time.monotonic()
        stamp, name = self.cache.get(process, (0, ''))
        if now - stamp > 2:
            name = Path(w.executable(process)).name.lower() if process else ''
            self.cache[process] = now, name
        import runtime_paths
        config = runtime_paths.load_path_config()
        expected = config.photoshop if name == 'photoshop.exe' else config.sony if name == 'edit.exe' else None
        if not expected and name in ('photoshop.exe', 'edit.exe'):
            expected = self.paths.get(name)
            if not expected:
                try:
                    expected = runtime_paths.resolve_photoshop() if name == 'photoshop.exe' else runtime_paths.resolve_sony()
                    self.paths[name] = expected
                except RuntimeError:
                    return 'other'
        if not expected or Path(w.executable(process)) != expected:
            return 'other'
        return 'photoshop' if name == 'photoshop.exe' else 'sony'


def reveal(path, select=False):
    path = Path(path).resolve(strict=True)
    if select:
        subprocess.Popen(['explorer.exe', '/select,' + str(path)])
    else:
        os.startfile(str(path))


def launcher():
    value = os.environ.get('SONY_RAW_LAUNCHER')
    if not value or not Path(value).is_file():
        raise ValueError('«Отправить» подключается из portable EXE. Запустите SonyRAWPanel.exe.')
    return Path(value).resolve()


def shortcut(action, folder=None):
    """Manage only our exact per-portable shortcut. No registry or elevation."""
    exe = launcher()
    tag = channel(exe.parent)
    description = 'Sony RAW Panel SendTo ' + tag
    # A folder override is used for isolated tests only.
    base = "$folder=" + ("'" + str(Path(folder)).replace("'", "''") + "'" if folder else "[Environment]::GetFolderPath('SendTo')")
    script = base + ";$shell=New-Object -ComObject WScript.Shell;$path=Join-Path $folder 'Sony RAW Panel.lnk';"
    script += "$exists=Test-Path -LiteralPath $path;$link=$shell.CreateShortcut($path);"
    q = lambda value: "'" + str(value).replace("'", "''") + "'"
    script += "if($exists -and $link.Description -ne " + q(description) + "){throw 'SendTo shortcut belongs to another location; remove or rename it manually.'};"
    if action == 'install':
        script += "$link.TargetPath=" + q(exe) + ";$link.WorkingDirectory=" + q(exe.parent) + ";$link.Description=" + q(description) + ";$link.Save();"
    elif action == 'remove':
        script += "if($exists){Remove-Item -LiteralPath $path};"
    else:
        raise ValueError('Invalid shortcut action.')
    import base64
    encoded = base64.b64encode(("$ErrorActionPreference='Stop';" + script).encode('utf-16le')).decode('ascii')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                            capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError('Не удалось изменить «Отправить». Проверьте, нет ли чужого одноимённого ярлыка.')
