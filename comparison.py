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
from preview_settings import scaled_size, validate_percent
from raw_dimensions import image_size

PRESETS = {'fast': 50, 'balanced': 75, 'full': 100}


class PreviewSony(bridge.Sony):
    def preview(self, destination, expected_name, percent, on_dimensions=lambda dimensions: None, source_dimensions=None):
        dialog = self.command_dialog(41217)
        self.check_dialog_source(dialog, w.control(dialog, 1148, 'Edit'), expected_name)
        width = w.control(dialog, 1042, 'Edit')
        height = w.control(dialog, 1037, 'Edit')
        original = tuple(source_dimensions) if source_dimensions else (int(w.get_text(width)), int(w.get_text(height)))
        on_dimensions(list(original))
        new = scaled_size(*original, percent)
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
        actual = (info[256][0], info[257][0])
        if info.get(274, [1])[0] in (5, 6, 7, 8):
            actual = tuple(reversed(actual))
        if actual != new:
            raise RuntimeError('Sony preview dimensions differ from the requested dimensions: ' + str(actual))
        return dict(width=info[256][0], height=info[257][0], original=list(original),
                    percent=percent, edge=max(new) if percent < 100 else 0)


def prepare(source, percent=50, notify=lambda text: None):
    percent = validate_percent(percent)
    source_dimensions = image_size(source, oriented=True)
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
    notify('Sony: предпросмотр %d%% от исходного RAW…' % percent)
    def remember_dimensions(values):
        data['output_dimensions'] = values
        bridge.atomic_json(folder / 'project.json', data)
    dimensions = sony.preview(directory / 'sony.tif', name, percent, remember_dimensions, source_dimensions)
    data['output_dimensions'] = dimensions['original']
    bridge.atomic_json(folder / 'project.json', data)
    state = dict(version=1, id=token, project=data['id'], revision=token, source=str(source),
                 directory=str(directory), sony=str(directory/'sony.tif'), percent=percent, edge=dimensions['edge'],
                 dimensions=dimensions, created=time.time(), sony_seconds=round(time.monotonic()-started, 2))
    bridge.atomic_json(directory / 'comparison.json', state)
    return state
