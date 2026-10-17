"""Release only identified service previews; keep modified/ambiguous work intact."""
import json
from pathlib import Path
import re
import tempfile


def records(root):
    directory = root / 'comparisons'
    if not directory.is_dir() or directory.resolve() != directory.absolute():
        return
    for folder in directory.iterdir():
        if not folder.is_dir() or folder.is_symlink() or not re.fullmatch('[a-f0-9]{32}', folder.name):
            continue
        try:
            record = folder / 'comparison.json'
            if record.is_symlink():
                continue
            data = json.loads(record.read_text(encoding='utf-8'))
            if data.get('version') == 1 and data.get('id') == folder.name:
                yield folder, data
        except (OSError, ValueError):
            continue


def remove_files(folder, ident):
    freed = 0
    skipped = 0
    for name in ('sony.tif', 'AdobeRAW-' + ident + '.ARW', 'AdobeRAW-' + ident + '.xmp', 'adobe-base.xmp'):
        path = folder / name
        if path.is_symlink() or path.resolve().parent != folder.resolve():
            skipped += 1
            continue
        try:
            if path.is_file():
                size = path.stat().st_size
                path.unlink()
                freed += size
        except OSError:
            skipped += 1
    return dict(bytes_freed=freed, skipped=skipped)


def save_prompt(w, sony, dialog):
    # Only the standard save-changes question owned by this exact Sony window.
    if w.pid(dialog) != sony.pid or w.cls(dialog) != '#32770' or w.u.GetWindow(dialog, 4) != sony.main:
        return None
    children = [h for h in w.windows(dialog) if w.u.IsWindowVisible(h)]
    buttons = {w.u.GetDlgCtrlID(h): h for h in children if w.cls(h) == 'Button'}
    if not all(ident in buttons and w.u.IsWindowEnabled(buttons[ident]) for ident in (6, 7, 2)):
        return None
    if any(w.cls(h) in ('Edit', 'ComboBox', 'msctls_progress32') for h in children):
        return None
    text = '\n'.join(w.get_text(h) for h in children if w.cls(h) == 'Static')
    if not re.search(r'(сохранить\s+изменения|save\s+(?:the\s+)?changes)', text, re.I):
        return None
    filenames = re.findall(r'[\w.-]+\.ARW\b', text, re.I)
    if len(filenames) != 1:
        return None
    return dict(name=filenames[0], no=buttons[7], cancel=buttons[2])


def close_sony_preview(bridge, sony, current, names):
    # Caller already persisted and compared the recipe against this preview's revision.
    if not re.fullmatch(r'SonyRAW-[a-f0-9]{32}\.ARW', current):
        raise ValueError('Закрывать без сохранения можно только служебное превью панели.')
    w = bridge.w
    sony.ready(30)
    if sony.active_name() != current:
        raise RuntimeError('Sony переключил снимок перед очисткой; вкладка сохранена.')
    w.post(sony.main, 0x0111, 57602)
    handled = set()

    def complete():
        dialogs = sony.dialogs()
        if dialogs:
            if len(dialogs) != 1:
                raise RuntimeError('Неизвестные окна Sony; очистка вкладки остановлена.')
            dialog = dialogs[0]
            if dialog in handled:
                return False
            prompt = save_prompt(w, sony, dialog)
            if not prompt:
                raise RuntimeError('Неизвестный диалог Sony оставлен без изменений.')
            handled.add(dialog)
            if prompt['name'] != current:
                # Our close command raced a tab change: cancel, never discard that photo.
                w.click(prompt['cancel'])
                w.wait(lambda: dialog not in sony.dialogs(), 10, 'Sony не отменил закрытие вкладки.')
                raise RuntimeError('Sony предложил сохранить другой RAW; закрытие отменено.')
            w.click(prompt['no'])
            return False
        return current not in names() and w.u.IsWindowEnabled(sony.main)

    w.wait(complete, 30, 'Sony не закрыл служебное превью.')


def release_sony(bridge, candidates, excluded=()):
    result = dict(closed=0, retained=0, warnings=[])
    if not candidates:
        return result
    sony_path = bridge.base.runtime.resolve_sony()
    if not any(bridge.w.u.IsWindowVisible(h) and Path(bridge.w.executable(bridge.w.pid(h))) == sony_path
               for h in bridge.w.windows()):
        return result
    sony = bridge.Sony()
    def names():
        return [bridge.w.get_text(h).strip().lstrip('*') for h in bridge.w.windows(sony.main)
                if bridge.w.u.GetDlgCtrlID(h) == 34101 and bridge.w.cls(h) == 'Static']
    original = sony.active_name()
    if not original:
        result['warnings'].append('Не удалось безопасно определить активную вкладку Sony; вкладки сохранены.')
        return result
    seen = set()
    try:
        for _ in range(len(names()) + 1):
            current = sony.active_name()
            if not current or current in seen:
                break
            seen.add(current)
            ident = current[8:-4] if re.fullmatch(r'SonyRAW-[a-f0-9]{32}\.ARW', current) else None
            closed = False
            if ident in candidates and ident not in excluded:
                try:
                    folder, data = bridge.project(ident)
                    bridge.validate_raw(folder, data)
                    baseline = bridge.settings_path(folder, data, candidates[ident])
                    from recipe_compare import recipes_equal
                    with tempfile.TemporaryDirectory(prefix='cleanup-recipe-', dir=bridge.ROOT) as temp:
                        recipe = Path(temp) / 'current.xml'
                        sony.save_settings(recipe, current)
                        unchanged = bool(baseline and recipes_equal(baseline, recipe))
                    if unchanged:
                        close_sony_preview(bridge, sony, current, names)
                        result['closed'] += 1
                        closed = True
                    else:
                        result['retained'] += 1
                except (OSError, ValueError, RuntimeError, TimeoutError) as error:
                    result['retained'] += 1
                    result['warnings'].append(str(error))
                    if sony.dialogs():
                        break
            if not names():
                break
            if not closed and len(names()) > 1:
                bridge.w.post(sony.main, 0x0111, 41219)
                bridge.w.wait(lambda: sony.active_name() != current, 10, 'Sony не переключил вкладку.')
            elif not closed:
                break
    finally:
        if not sony.dialogs() and original in names():
            for _ in range(len(names())):
                if sony.active_name() == original:
                    break
                previous = sony.active_name()
                bridge.w.post(sony.main, 0x0111, 41219)
                bridge.w.wait(lambda: sony.active_name() != previous, 10, 'Не удалось восстановить вкладку Sony.')
    return result
