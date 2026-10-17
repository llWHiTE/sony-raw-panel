"""Portable runtime paths and Windows application discovery.

The module intentionally uses only the Python standard library so it is safe to
import from both source and a PyInstaller executable.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from typing import Iterator, Mapping, Optional

try:  # winreg is unavailable when the module is tested off Windows.
    import winreg
except ImportError:  # pragma: no cover - exercised on non-Windows hosts
    winreg = None  # type: ignore[assignment]


_SETTINGS_FILE = "settings.json"
_SONY_KEY = r"SOFTWARE\Sony Corporation\Imaging Edge"
_PHOTOSHOP_APP_PATH = (
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Photoshop.exe"
)


@dataclass(frozen=True)
class PathConfig:
    """Validated optional overrides saved in the portable settings file."""

    sony: Optional[Path] = None
    photoshop: Optional[Path] = None


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    """Return the read-only source/bundle directory containing application files."""
    if _is_frozen():
        bundle = getattr(sys, "_MEIPASS", None)
        if bundle:
            return Path(bundle)
    return Path(__file__).resolve().parent


def data_root() -> Path:
    """Return and create the portable writable directory."""
    portable_home = os.environ.get("SONY_RAW_PORTABLE_HOME")
    if portable_home:
        root = Path(portable_home).expanduser() / "data"
    elif _is_frozen():
        root = Path(sys.executable).resolve().parent / "data"
    else:
        root = Path(__file__).resolve().parent
    root.mkdir(parents=True, exist_ok=True)
    return root


def settings_path() -> Path:
    return data_root() / _SETTINGS_FILE


def _executable_path(value: object, expected_name: str) -> Optional[Path]:
    if not isinstance(value, (str, os.PathLike)):
        return None
    try:
        path = Path(value).expanduser()
    except (TypeError, ValueError):
        return None
    if path.name.casefold() != expected_name.casefold() or not path.is_file():
        return None
    return path.resolve()


def _config_from_mapping(values: Mapping[str, object]) -> PathConfig:
    return PathConfig(
        sony=_executable_path(values.get("sony"), "Edit.exe"),
        photoshop=_executable_path(values.get("photoshop"), "Photoshop.exe"),
    )


def load_path_config() -> PathConfig:
    """Load valid entries only; a damaged or stale settings file is harmless."""
    try:
        with settings_path().open("r", encoding="utf-8") as file:
            values = json.load(file)
    except (OSError, json.JSONDecodeError):
        return PathConfig()
    return _config_from_mapping(values) if isinstance(values, dict) else PathConfig()


def save_path_config(
    *, sony: Optional[os.PathLike[str] | str] = None,
    photoshop: Optional[os.PathLike[str] | str] = None,
) -> PathConfig:
    """Persist executable overrides, rejecting nonexistent or wrongly named files."""
    config = PathConfig(
        sony=_require_executable(sony, "Edit.exe", "Sony Edit"),
        photoshop=_require_executable(photoshop, "Photoshop.exe", "Photoshop"),
    )
    destination = settings_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    payload = {
        "sony": str(config.sony) if config.sony else None,
        "photoshop": str(config.photoshop) if config.photoshop else None,
    }
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
        temporary.replace(destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return config


def _require_executable(
    value: Optional[os.PathLike[str] | str], expected_name: str, label: str
) -> Optional[Path]:
    if value is None:
        return None
    path = _executable_path(value, expected_name)
    if path is None:
        raise ValueError(
            f"{label}: укажите существующий файл с именем {expected_name}."
        )
    return path


def _registry_value(root: int, key_name: str, value_name: str, view: int) -> Optional[str]:
    if winreg is None:
        return None
    key = None
    try:
        access = winreg.KEY_READ | view
        key = winreg.OpenKey(root, key_name, 0, access)
        value, _ = winreg.QueryValueEx(key, value_name)
        return value if isinstance(value, str) else None
    except OSError:
        return None
    finally:
        if key is not None:
            winreg.CloseKey(key)


def _registry_views() -> tuple[int, ...]:
    if winreg is None:
        return ()
    views = [getattr(winreg, "KEY_WOW64_64KEY", 0), getattr(winreg, "KEY_WOW64_32KEY", 0)]
    return tuple(dict.fromkeys(views))


def _registry_install_locations() -> Iterator[Path]:
    if winreg is None:
        return
    for view in _registry_views():
        value = _registry_value(winreg.HKEY_LOCAL_MACHINE, _SONY_KEY, "InstallLocation", view)
        if value:
            yield Path(value)


def _registry_photoshop_app_paths() -> Iterator[Path]:
    if winreg is None:
        return
    roots = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
    for root in roots:
        for view in _registry_views():
            value = _registry_value(root, _PHOTOSHOP_APP_PATH, "", view)
            executable = _command_executable(value)
            if executable:
                yield executable


def _registry_photoshop_com_servers() -> Iterator[Path]:
    """Read Photoshop's COM LocalServer32 registration in both registry views."""
    if winreg is None:
        return
    for view in _registry_views():
        clsid = _registry_value(winreg.HKEY_CLASSES_ROOT, r"Photoshop.Application\CLSID", "", view)
        if not clsid:
            continue
        value = _registry_value(
            winreg.HKEY_CLASSES_ROOT, rf"CLSID\{clsid}\LocalServer32", "", view
        )
        executable = _command_executable(value)
        if executable:
            yield executable


def _command_executable(value: Optional[str]) -> Optional[Path]:
    if not value:
        return None
    command = value.strip()
    if command.startswith('"'):
        end = command.find('"', 1)
        candidate = command[1:end] if end > 1 else ""
    else:
        marker = command.casefold().find(".exe")
        candidate = command[: marker + 4] if marker >= 0 else command
    return Path(candidate) if candidate else None


def _query_process_image(pid: int) -> Optional[Path]:
    if os.name != "nt":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    process_query_limited_information = 0x1000
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return None
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return Path(buffer.value)
    finally:
        kernel32.CloseHandle(handle)


def _running_process_paths() -> Iterator[Path]:
    """Enumerate Windows processes and obtain each image through QueryFullProcessImageNameW."""
    if os.name != "nt":
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    invalid_handle = ctypes.c_void_p(-1).value
    if snapshot == invalid_handle:
        return
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return
        while True:
            image = _query_process_image(entry.th32ProcessID)
            if image:
                yield image
            entry.dwSize = ctypes.sizeof(entry)
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)


def _window_process_paths() -> Iterator[Path]:
    """Return executables behind visible top-level windows (used for Photoshop)."""
    if os.name != "nt":
        return
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    seen: set[int] = set()
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = (callback_type, wintypes.LPARAM)
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = (
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    )
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD

    @callback_type
    def visit(window: int, _unused: int) -> bool:
        if not user32.IsWindowVisible(window):
            return True
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(process_id))
        if process_id.value:
            seen.add(process_id.value)
        return True

    user32.EnumWindows(visit, 0)
    for process_id in seen:
        image = _query_process_image(process_id)
        if image:
            yield image


def _first_valid(candidates: Iterator[Path], expected_name: str) -> Optional[Path]:
    seen: set[str] = set()
    for candidate in candidates:
        path = _executable_path(candidate, expected_name)
        if path and str(path).casefold() not in seen:
            seen.add(str(path).casefold())
            return path
    return None


def _sony_candidates() -> Iterator[Path]:
    for installation in _registry_install_locations():
        yield installation / "Edit.exe"
        yield installation / "Edit" / "Edit.exe"
    yield from _running_process_paths()


def discover_sony() -> Optional[Path]:
    """Discover Sony Imaging Edge Edit from the registry or a running process."""
    return _first_valid(_sony_candidates(), "Edit.exe")


def _photoshop_candidates() -> Iterator[Path]:
    yield from _window_process_paths()
    yield from _registry_photoshop_app_paths()
    yield from _registry_photoshop_com_servers()


def discover_photoshop() -> Optional[Path]:
    """Discover Photoshop from its visible window, App Paths, or COM registration."""
    return _first_valid(_photoshop_candidates(), "Photoshop.exe")


def resolve_sony() -> Path:
    """Return configured/discovered Sony Edit or a next-step Russian error."""
    config = load_path_config()
    if config.sony:
        return config.sony
    discovered = discover_sony()
    if discovered:
        return discovered
    raise RuntimeError(
        "Sony Imaging Edge Edit не найден. Запустите Sony Edit вручную, затем повторите попытку."
    )


def resolve_photoshop() -> Optional[Path]:
    """Return the configured or discovered Photoshop executable when available."""
    config = load_path_config()
    return config.photoshop or discover_photoshop()


# Short aliases for consumers that treat the file as a generic path configuration API.
load_config = load_path_config
save_config = save_path_config
