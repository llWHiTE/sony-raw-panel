import importlib.util
from pathlib import Path
import time
import sys

SOURCE = Path(__file__).resolve().parent
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))
import runtime_paths as runtime
ROOT = runtime.data_root()
BUNDLE = runtime.bundle_root()
spec = importlib.util.spec_from_file_location('compare_base', BUNDLE / 'bridge_v2.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
w = bridge.w
PRESETS = {'fast': 1600, 'balanced': 3000, 'full': 0}


def scaled_size(width, height, long_edge):
    if width <= 0 or height <= 0 or long_edge < 0:
        raise ValueError('Invalid preview dimensions.')
    factor = min(1, long_edge / max(width, height)) if long_edge else 1
    return max(1, round(width * factor)), max(1, round(height * factor))


class PreviewSony(bridge.Sony):
    def preview(self, destination, expected_name, edge, on_dimensions=lambda dimensions: None):
        dialog = self.command_dialog(41217)
        self.check_dialog_source(dialog, w.control(dialog, 1148, 'Edit'), expected_name)
        width = w.control(dialog, 1042, 'Edit')
        height = w.control(dialog, 1037, 'Edit')
        original = (int(w.get_text(width)), int(w.get_text(height)))
        on_dimensions(list(original))
        new = scaled_size(*original, edge)
        self.navigate(dialog, destination.parent)
        w.select(w.control(dialog, 1136, 'ComboBox'), 1)
        bit = w.control(dialog, 1700, 'Button')
        w.wait(lambda: w.u.IsWindowEnabled(bit), 10, 'Sony TIFF controls not ready.')
        w.click(bit)
        w.wait(lambda: w.send(bit, 0x00f0) == 1, 5, 'Sony did not select 16-bit TIFF.')
        w.select(w.control(dialog, 1303, 'ComboBox'), 1)
        w.set_text(width, str(new[0]))
        w.set_text(height, str(new[1]))
        w.set_text(w.control(dialog, 1148, 'Edit'), destination.name)
        self.submit(dialog)
        self.finish_dialog(dialog, 300, allow_progress=True)
        w.wait(lambda: destination.is_file() and destination.stat().st_size > 0, 300, 'Sony preview was not exported.')
        info = bridge.base.tiff_info(destination)
        # Restore the export controls before any full-size working render is requested.
        restore = self.command_dialog(41217)
        try:
            self.check_dialog_source(restore, w.control(restore, 1148, 'Edit'), expected_name)
            w.set_text(w.control(restore, 1042, 'Edit'), str(original[0]))
            w.set_text(w.control(restore, 1037, 'Edit'), str(original[1]))
        finally:
            if w.u.IsWindow(restore) and w.u.IsWindowVisible(restore):
                w.click(w.control(restore, 2, 'Button'))
                self.finish_dialog(restore, 15)
        bridge.base.embed_srgb(destination)
        actual = sorted((info[256][0], info[257][0]))
        if actual != sorted(new):
            raise RuntimeError('Sony preview dimensions differ from the requested dimensions: ' + str(actual))
        return dict(width=info[256][0], height=info[257][0], original=list(original), edge=edge)


def prepare(source, edge, notify=lambda text: None):
    if edge not in PRESETS.values():
        raise ValueError('Unsupported comparison size.')
    bridge.PROJECTS.mkdir(exist_ok=True)
    bridge.CACHE.mkdir(exist_ok=True)
    started = time.monotonic()
    folder, data = bridge.new_project(source)
    sony = PreviewSony()
    bridge.activate(sony, folder, data)
    token = bridge.uuid.uuid4().hex
    directory = ROOT / 'comparisons' / token
    directory.mkdir(parents=True)
    name = 'SonyRAW-' + data['id'] + '.ARW'
    recipe = bridge.snapshot_recipe(sony, folder, data, token)
    data['active_revision'] = token
    bridge.atomic_json(folder / 'project.json', data)
    notify('Sony: уменьшенная проявка для сравнения…' if edge else 'Sony: полноразмерная проявка для сравнения…')
    def remember_dimensions(values):
        data['output_dimensions'] = values
        bridge.atomic_json(folder / 'project.json', data)
    dimensions = sony.preview(directory / 'sony.tif', name, edge, remember_dimensions)
    data['output_dimensions'] = dimensions['original']
    bridge.atomic_json(folder / 'project.json', data)
    state = dict(version=1, id=token, project=data['id'], revision=token, source=str(source),
                 directory=str(directory), sony=str(directory/'sony.tif'), edge=edge,
                 dimensions=dimensions, created=time.time(), sony_seconds=round(time.monotonic()-started, 2))
    bridge.atomic_json(directory / 'comparison.json', state)
    return state
