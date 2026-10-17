import argparse
import ctypes as C
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import traceback

SOURCE = Path(__file__).resolve().parent
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))
import runtime_paths as runtime
ROOT = runtime.data_root()
BUNDLE = runtime.bundle_root()
spec = importlib.util.spec_from_file_location('sony_windows', BUNDLE / 'sony_windows.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
SONY = None


def log(message):
    print(time.strftime('%H:%M:%S'), message, flush=True)


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def tiff_info(path):
    with path.open('rb') as f:
        header = f.read(8)
        if len(header) != 8 or header[:2] not in (b'II', b'MM'):
            raise ValueError('Not a TIFF file')
        endian = '<' if header[:2] == b'II' else '>'
        magic, offset = struct.unpack(endian + 'HI', header[2:])
        if magic != 42:
            raise ValueError('Unexpected TIFF version')
        f.seek(offset)
        count = struct.unpack(endian + 'H', f.read(2))[0]
        entries = [f.read(12) for _ in range(count)]
        tags = {}
        for entry in entries:
            tag, kind, n = struct.unpack(endian + 'HHI', entry[:8])
            if tag not in (256, 257, 258, 259, 262, 274, 277, 305, 34675):
                continue
            size = {1: 1, 2: 1, 3: 2, 4: 4, 7: 1}.get(kind)
            if size is None or n * size > 4_000_000:
                raise ValueError('Unexpected TIFF tag')
            if n * size <= 4:
                data = entry[8:8 + n * size]
            else:
                f.seek(struct.unpack(endian + 'I', entry[8:])[0])
                data = f.read(n * size)
            if len(data) != n * size:
                raise ValueError('Incomplete TIFF')
            if kind == 2:
                tags[tag] = data.rstrip(b'\0').decode('ascii', errors='replace')
            elif kind in (3, 4):
                tags[tag] = list(struct.unpack(endian + str(n) + ('H' if kind == 3 else 'I'), data))
            else:
                tags[tag] = {'bytes': len(data)}
        if tags.get(258) != [16, 16, 16] or tags.get(262) != [2] or tags.get(277) != [3]:
            raise ValueError('Expected 16-bit RGB TIFF')
        if not str(tags.get(305, '')).startswith('Edit '):
            raise ValueError('TIFF is not marked as a Sony Edit export')
        return tags


def embed_srgb(path):
    profile_path = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/spool/drivers/color/sRGB Color Space Profile.icm'
    profile = profile_path.read_bytes()
    if profile[36:40] != b'acsp' or b'sRGB IEC61966-2.1' not in profile:
        raise ValueError('The bundled sRGB profile is invalid.')
    with path.open('r+b') as f:
        header = f.read(8)
        endian = '<' if header[:2] == b'II' else '>'
        old_ifd = struct.unpack(endian + 'I', header[4:])[0]
        f.seek(old_ifd)
        n = struct.unpack(endian + 'H', f.read(2))[0]
        entries = [f.read(12) for _ in range(n)]
        next_ifd = f.read(4)
        if any(struct.unpack(endian + 'H', e[:2])[0] == 34675 for e in entries):
            raise ValueError('Sony exported an unexpected embedded profile; refusing to replace it.')
        f.seek(0, 2)
        if f.tell() % 2:
            f.write(b'\0')
        profile_offset = f.tell()
        f.write(profile)
        if f.tell() % 2:
            f.write(b'\0')
        new_ifd = f.tell()
        entries.append(struct.pack(endian + 'HHII', 34675, 7, len(profile), profile_offset))
        entries.sort(key=lambda e: struct.unpack(endian + 'H', e[:2])[0])
        f.write(struct.pack(endian + 'H', len(entries)))
        for entry in entries:
            f.write(entry)
        f.write(next_ifd)
        f.flush()
        f.seek(4)
        f.write(struct.pack(endian + 'I', new_ifd))
    return tiff_info(path)


class Sony:
    def __init__(self):
        sony_path = Path(SONY) if SONY else runtime.resolve_sony()
        def locate():
            candidates = []
            for h in w.windows():
                if w.u.IsWindowVisible(h) and w.u.GetMenu(h) and w.cls(h).startswith('Afx:'):
                    if Path(w.executable(w.pid(h))) == sony_path:
                        candidates.append(h)
            if len(candidates) > 1:
                raise RuntimeError('More than one Sony Edit main window is open.')
            return candidates[0] if candidates else None

        self.main = locate()
        if not self.main:
            if not sony_path.is_file():
                raise RuntimeError('Sony Edit executable not found: ' + str(sony_path))
            subprocess.Popen([str(sony_path)], cwd=str(sony_path.parent))
            self.main = w.wait(locate, 60, 'Sony Edit did not start.')
        self.pid = w.pid(self.main)
        if not w.u.IsWindowEnabled(self.main) or self.dialogs():
            raise RuntimeError('Close modal dialogs in Sony Edit, then run the script again. No existing dialog was dismissed.')

    def dialogs(self):
        return [h for h in w.windows() if w.pid(h) == self.pid and w.cls(h) == '#32770' and w.u.IsWindowVisible(h)]

    def error_text(self):
        return ' | '.join(w.text(h) for d in self.dialogs() for h in [d] + w.windows(d) if w.text(h))

    def progress(self, dialog):
        return w.text(dialog) in ('Сохранить изображения', 'Saving Images', 'Save Images') or any(
            w.cls(h) == 'msctls_progress32' for h in w.windows(dialog))

    def ready(self, seconds=180, allow_progress=False):
        def check():
            dialogs = self.dialogs()
            if any(not (allow_progress and self.progress(d)) for d in dialogs):
                raise RuntimeError('Sony requires attention: ' + self.error_text())
            return not dialogs and w.u.IsWindowEnabled(self.main)
        w.wait(check, seconds, 'Sony Edit did not return to its main window.')

    def command_state(self, command):
        u = w.u
        u.GetSubMenu.argtypes = [w.W.HMENU, C.c_int]
        u.GetSubMenu.restype = w.W.HMENU
        u.GetMenuItemCount.argtypes = [w.W.HMENU]
        u.GetMenuItemID.argtypes = [w.W.HMENU, C.c_int]
        u.GetMenuItemID.restype = w.W.UINT
        root = u.GetMenu(self.main)
        def locate(menu, popup_index=None):
            for i in range(u.GetMenuItemCount(menu)):
                if u.GetMenuItemID(menu, i) == command:
                    return menu, popup_index
                sub = u.GetSubMenu(menu, i)
                found = locate(sub, i) if sub else None
                if found:
                    return found
            return None
        found = locate(root)
        if not found:
            return -1
        menu, index = found
        # WM_INITMENUPOPUP accepts a popup, never the root menu bar.
        if index is not None:
            w.send(self.main, 0x0117, menu, index)
        return u.GetMenuState(menu, command, 0)

    def command_dialog(self, command):
        self.ready()
        state = self.command_state(command)
        if state == -1 or state & 3:
            raise RuntimeError('Sony menu command is unavailable: ' + str(command))
        w.post(self.main, 0x0111, command)

        def check():
            for d in self.dialogs():
                if any(w.u.GetDlgCtrlID(h) in (1148, 1001) and w.cls(h) == 'Edit' for h in w.windows(d)):
                    return d
            return None
        return w.wait(check, 30, 'Expected file dialog did not appear: ' + str(command))

    def submit(self, dialog):
        w.click(w.control(dialog, 1, 'Button'))

    def finish_dialog(self, dialog, seconds=180, allow_progress=False):
        def check():
            other = [h for h in self.dialogs() if h != dialog and not (allow_progress and self.progress(h))]
            if other:
                raise RuntimeError('Sony requires attention: ' + self.error_text())
            return not w.u.IsWindow(dialog) or not w.u.IsWindowVisible(dialog)
        w.wait(check, seconds, 'Sony file dialog did not close.')
        self.ready(seconds, allow_progress)

    def open(self, path):
        dialog = self.command_dialog(57601)
        w.set_text(w.control(dialog, 1148, 'Edit'), str(path))
        self.submit(dialog)
        self.finish_dialog(dialog)
        def opened():
            labels = [w.get_text(h).strip().lstrip('*') for h in w.windows(self.main)
                      if w.u.GetDlgCtrlID(h) == 34101 and w.cls(h) == 'Static']
            state = self.command_state(41217)
            return path.name in labels and state != -1 and not (state & 3)
        w.wait(opened, 120, 'Sony RAW processing did not become available.')

    def navigate(self, dialog, folder):
        # Sony rejects an absolute output filename, but accepts an existing folder.
        w.set_text(w.control(dialog, 1148, 'Edit'), str(folder))
        self.submit(dialog)
        def check():
            if any(h != dialog for h in self.dialogs()):
                raise RuntimeError('Sony folder navigation failed: ' + self.error_text())
            combo = w.control(dialog, 1137, 'ComboBox')
            index = w.send(combo, 0x0147)
            if index > 1000:
                return False
            length = w.send(combo, 0x0149, index)
            if length > 32767:
                return False
            b = C.create_unicode_buffer(length + 1)
            w.send(combo, 0x0148, index, C.addressof(b))
            return b.value.casefold() == folder.name.casefold()
        w.wait(check, 15, 'Sony did not navigate to the private cache folder.')

    def export(self, destination):
        dialog = self.command_dialog(41217)
        self.navigate(dialog, destination.parent)
        kind = w.control(dialog, 1136, 'ComboBox')
        w.select(kind, 1)
        time.sleep(0.3)
        bit = w.control(dialog, 1700, 'Button')
        w.wait(lambda: w.u.IsWindowEnabled(bit), 10, 'Sony did not enable TIFF 16-bit output.')
        w.click(bit)
        w.wait(lambda: w.send(bit, 0x00F0) == 1, 5, 'Sony did not select 16-bit output.')
        w.select(w.control(dialog, 1303, 'ComboBox'), 1)
        w.set_text(w.control(dialog, 1148, 'Edit'), destination.name)
        self.submit(dialog)
        self.finish_dialog(dialog, 300, allow_progress=True)
        last = [0, 0.0]
        def stable():
            if not destination.is_file():
                return False
            size = destination.stat().st_size
            if size != last[0]:
                last[:] = [size, time.monotonic()]
                return False
            if size and time.monotonic() - last[1] >= 2:
                return tiff_info(destination)
            return False
        return w.wait(stable, 300, 'Sony did not produce a complete TIFF.')

    def save_settings(self, destination):
        dialog = self.command_dialog(37395)
        w.set_text(w.control(dialog, 1001, 'Edit'), str(destination))
        self.submit(dialog)
        self.finish_dialog(dialog, 30)
        w.wait(lambda: destination.is_file() and destination.stat().st_size > 0, 15, 'Sony settings XML was not created.')


def run(source):
    source = source.resolve(strict=True)
    if source.suffix.lower() != '.arw' or not source.is_file():
        raise ValueError('Choose a Sony .ARW file.')
    cache = ROOT / 'cache'
    cache.mkdir(exist_ok=True)
    if shutil.disk_usage(cache).free < source.stat().st_size + 1_200_000_000:
        raise RuntimeError('At least 1.2 GB plus the RAW size must be free on the cache drive.')
    job = Path(tempfile.mkdtemp(prefix='render-', dir=cache))
    log('Cache: ' + str(job))
    before = sha(source)
    copied = job / 'source.ARW'
    shutil.copy2(source, copied)
    if sha(copied) != before:
        raise RuntimeError('RAW copy verification failed.')
    log('Opening a verified RAW copy in Sony Edit')
    sony = Sony()
    sony.open(copied)
    target = job / 'sony-render.tif'
    log('Rendering TIFF: 16-bit RGB, sRGB')
    tags = sony.export(target)
    settings = job / 'sony-settings.xml'
    log('Saving Sony development settings')
    sony.save_settings(settings)
    log('Embedding the sRGB profile without changing image samples')
    tags = embed_srgb(target)
    after = sha(source)
    copy_after = sha(copied)
    if before != after or before != copy_after:
        raise RuntimeError('RAW hash changed; output not delivered. Inspect the cache.')
    manifest = dict(source=str(source), source_sha256=before, raw_copy=str(copied),
                    output=str(target), settings=str(settings), color_space='sRGB IEC61966-2.1',
                    tiff=tags, original_unchanged=True, copy_unchanged=True,
                    created=time.strftime('%Y-%m-%dT%H:%M:%S%z'))
    (job / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    log('Verified; handing TIFF to Photoshop')
    return target


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', type=Path, required=True)
    args = parser.parse_args()
    response = args.request.with_suffix('.result.txt')
    mutex = None
    try:
        mutex = w.k.CreateMutexW(None, False, 'Local\\SonyRawPrototypeRender')
        if not mutex:
            raise C.WinError(C.get_last_error())
        if C.get_last_error() == 183:
            raise RuntimeError('Another Sony RAW render is already running.')
        source = Path(args.request.read_text(encoding='utf-8-sig').strip())
        output = run(source)
        response.write_text('OK\n' + str(output), encoding='utf-8')
        return 0
    except Exception as exc:
        traceback.print_exc()
        response.write_text('ERROR\n' + str(exc), encoding='utf-8')
        return 1
    finally:
        if mutex:
            w.k.CloseHandle(mutex)


if __name__ == '__main__':
    sys.exit(main())
