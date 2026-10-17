"""Bounded, content-addressed derived-image cache. Never owns RAW projects."""
from contextlib import contextmanager
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
import uuid

SCHEMA = 1
KEY = re.compile(r'[a-f0-9]{64}\Z')


def _windows_version(path):
    import ctypes as C
    from ctypes import wintypes as W
    class Basic(C.Structure):
        _fields_ = [('created', C.c_longlong), ('accessed', C.c_longlong), ('written', C.c_longlong),
                    ('changed', C.c_longlong), ('attributes', W.DWORD)]
    k = C.WinDLL('kernel32', use_last_error=True)
    k.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE]
    k.CreateFileW.restype = W.HANDLE
    k.GetFileInformationByHandleEx.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD]
    k.DeviceIoControl.argtypes = [W.HANDLE, W.DWORD, C.c_void_p, W.DWORD, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p]
    k.CloseHandle.argtypes = [W.HANDLE]
    handle = k.CreateFileW(str(path), 0x80, 7, None, 3, 0, None)
    if handle == C.c_void_p(-1).value:
        raise OSError('Cannot verify file version.')
    try:
        info = Basic()
        changed = info.changed if k.GetFileInformationByHandleEx(handle, 0, C.byref(info), C.sizeof(info)) else None
        record = C.create_string_buffer(4096)
        length = W.DWORD()
        if k.DeviceIoControl(handle, 0x000900eb, None, 0, record, len(record), C.byref(length), None):
            data = record.raw[:length.value]
            major = int.from_bytes(data[4:6], 'little')
            offset = 24 if major == 2 else 40 if major == 3 else None
            if offset is not None and len(data) >= offset + 8:
                return changed, int.from_bytes(data[offset:offset + 8], 'little', signed=True)
    finally:
        k.CloseHandle(handle)
    return changed, None


def signature(path):
    path = Path(path)
    st = path.stat()
    changed, version = st.st_ctime_ns, None
    if os.name == 'nt':
        # Windows can coalesce even ChangeTime across rapid writes. NTFS USN changes
        # after a writer closes; on volumes without it, verify contents, not a clock.
        changed, version = _windows_version(path)
        if version is None:
            with path.open('rb') as stream:
                version = hashlib.file_digest(stream, 'sha256').hexdigest()
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns, changed, version)


@lru_cache(maxsize=256)
def _digest(path, stamp):
    with Path(path).open('rb') as stream:
        result = hashlib.file_digest(stream, 'sha256').hexdigest()
    if signature(path) != stamp:
        raise ValueError('Файл изменился во время проверки.')
    return result


def digest(path):
    path = Path(path).resolve(strict=True)
    return _digest(str(path), signature(path))


def key_for(settings):
    return hashlib.sha256(json.dumps(dict(schema=SCHEMA, **settings), sort_keys=True,
                                     separators=(',', ':'), ensure_ascii=True).encode('ascii')).hexdigest()


def safe_file(path):
    path = Path(path)
    return path.is_file() and path.resolve() == path.absolute() and path.stat().st_nlink == 1


def atomic(path, data):
    temporary = path.with_name(uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class RenderCache:
    def __init__(self, root, limit=5_000_000_000):
        self.directory = Path(root) / 'render-cache'
        self.directory.mkdir(exist_ok=True)
        if self.directory.resolve() != self.directory.absolute():
            raise ValueError('Каталог кэша перенаправлен.')
        self.limit = max(0, int(limit))
        self.pins = set()

    def folder(self, key):
        if not isinstance(key, str) or not KEY.fullmatch(key):
            raise ValueError('Invalid render cache key.')
        folder = self.directory / key
        if folder.resolve() != folder.absolute():
            raise ValueError('Redirected cache entry.')
        return folder

    def get(self, key):
        if not key or not self.limit:
            return None
        try:
            folder = self.folder(key)
            manifest = folder / 'entry.json'
            if not safe_file(manifest):
                return None
            data = json.loads(manifest.read_text(encoding='utf-8'))
            if not isinstance(data, dict) or data.get('schema') != SCHEMA or data.get('key') != key or not data.get('complete'):
                return None
            image = folder / 'image.tif'
            if not safe_file(image) or digest(image) != data['sha256']:
                return None
            data['accessed'] = time.time()
            atomic(manifest, data)
            return dict(data, path=str(image))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def put(self, key, image, metadata):
        if not self.limit or Path(image).stat().st_size > self.limit:
            return None
        existing = self.get(key)
        if existing:
            return existing
        folder = self.folder(key)
        temporary = self.directory / ('writing-' + uuid.uuid4().hex)
        temporary.mkdir()
        try:
            if shutil.disk_usage(self.directory).free < Path(image).stat().st_size + 900_000_000:
                return None
            shutil.copy2(image, temporary / 'image.tif')
            data = dict(schema=SCHEMA, key=key, complete=True, sha256=digest(temporary / 'image.tif'),
                        bytes=(temporary / 'image.tif').stat().st_size, accessed=time.time(), metadata=metadata)
            atomic(temporary / 'entry.json', data)
            if folder.exists():
                if key in self.pins:
                    return None
                self._remove(folder)
            temporary.replace(folder)
        finally:
            if temporary.exists():
                self._remove(temporary)
        self.pins.add(key)
        try:
            self.trim()
            return self.get(key)
        finally:
            self.pins.discard(key)

    @contextmanager
    def lease(self, key):
        already = key in self.pins
        self.pins.add(key)
        try:
            yield self.get(key)
        finally:
            if not already:
                self.pins.discard(key)

    def copy(self, key, target):
        with self.lease(key) as data:
            if not data:
                return None
            target = Path(target)
            if target.exists() and not safe_file(target):
                raise ValueError('Redirected render destination.')
            shutil.copy2(data['path'], target)
            if digest(target) != data['sha256']:
                raise ValueError('Копия кэша не прошла проверку.')
            return data

    def _remove(self, folder):
        if folder.parent != self.directory or folder.resolve() != folder.absolute():
            raise ValueError('Unsafe cache deletion.')
        # Refuse unexpected contents rather than recursively deleting arbitrary trees.
        paths = list(folder.iterdir())
        if any(p.name not in ('image.tif', 'entry.json') or not safe_file(p) for p in paths):
            return False
        for path in paths:
            path.unlink()
        folder.rmdir()
        return True

    def trim(self, clear=False):
        entries = []
        for folder in self.directory.iterdir():
            if not KEY.fullmatch(folder.name) or folder.resolve() != folder.absolute():
                continue
            try:
                data = json.loads((folder / 'entry.json').read_text(encoding='utf-8'))
                entries.append((float(data['accessed']), folder, (folder / 'image.tif').stat().st_size))
            except (OSError, ValueError, KeyError, TypeError):
                continue
        total = sum(size for _, _, size in entries)
        freed = 0
        for _, folder, size in sorted(entries):
            if folder.name not in self.pins and (clear or total > self.limit):
                if self._remove(folder):
                    total -= size
                    freed += size
        return dict(bytes=total, bytes_freed=freed, pinned=len(self.pins))
