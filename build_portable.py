"""Build a single portable Windows EXE with stdlib tools and a local CPython runtime."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
import zipfile

APP_FILES = (
    'sony_panel.py', 'panel_core.py', 'bridge.py', 'bridge_v2.py', 'sony_windows.py',
    'runtime_paths.py', 'recipe_compare.py', 'app_info.py', 'comparison.py', 'comparison_adobe.py',
    'preview_settings.py', 'raw_dimensions.py', 'preview_cleanup.py', 'lut_library.py', 'lut_profile.py', 'lut_photoshop.jsx',
    'development_profiles.py', 'profile_catalog.py', 'sony-profile-catalog.json',
    'advanced_core.py', 'advanced_panel.py', 'render_cache.py', 'render_workflow.py',
    'task_scheduler.py', 'raw_queue.py', 'windows_integration.py', 'SonyRAWPanel.ico',
    'LICENSE', 'PYTHON_LICENSE.txt', 'TCL_LICENSE.txt', 'TK_LICENSE.txt',
    'panel_photoshop.jsx', 'comparison_photoshop.jsx', 'photoshop_host.ps1',
    'README.md', 'PANEL.md', 'PORTABLE.md', 'THIRD_PARTY_NOTICES.md', 'BENCHMARK.md', 'CHANGELOG.md', 'verification.py',
)


def build(source, python_home, output):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    output.mkdir(parents=True, exist_ok=True)
    payload = output / 'runtime-payload.zip'
    with zipfile.ZipFile(payload, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name in APP_FILES:
            path = source / name
            if not path.is_file():
                raise FileNotFoundError(path)
            archive.write(path, 'app/' + name)
        for path in sorted((source / 'bundled-luts').iterdir()):
            if path.is_file() and path.suffix.lower() in ('.cube', '.xmp'):
                from lut_library import validate
                validate(path)
                archive.write(path, 'app/bundled-luts/' + path.name)
        for name in ('python.exe', 'pythonw.exe', 'python314.dll', 'python3.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'LICENSE.txt'):
            archive.write(python_home / name, name)
        for directory in ('Lib', 'DLLs', 'tcl'):
            for path in sorted((python_home / directory).rglob('*')):
                if not path.is_file():
                    continue
                relative = path.relative_to(python_home)
                if any(part in ('site-packages', '__pycache__', 'test', 'tests', 'idlelib', 'turtledemo') for part in relative.parts):
                    continue
                if path.suffix in ('.pyc', '.pdb', '.lib', '.chm', '.ico') or path.name.startswith('_test') or path.name.startswith('_ctypes_test'):
                    continue
                archive.write(path, relative.as_posix())
        if not (python_home / 'tcl/tcl8.6/license.terms').exists():
            archive.write(source / 'TCL_LICENSE.txt', 'tcl/tcl8.6/license.terms')
        runtime_files = sorted(name for name in archive.namelist() if not name.startswith('app/'))
        archive.writestr('RUNTIME_MANIFEST.txt', '\n'.join(runtime_files) + '\n')
    exe = output / 'SonyRAWPanel.exe'
    csc = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
    subprocess.run([str(csc), '/nologo', '/target:winexe', '/platform:x64', '/optimize+',
        '/reference:System.Windows.Forms.dll', '/reference:System.IO.Compression.dll',
        '/win32icon:' + str(source / 'SonyRAWPanel.ico'),
        '/resource:' + str(payload) + ',SonyRawPayload', '/out:' + str(exe), str(source / 'PortableLauncher.cs')], check=True)
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    (output / 'SHA256SUMS.txt').write_text(digest + '  ' + exe.name + '\n', encoding='ascii')
    print(str(exe), exe.stat().st_size, 'bytes', digest)
    return exe


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--python-home', type=Path, default=Path(sys.base_prefix))
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parent / 'dist')
    args = parser.parse_args()
    build(Path(__file__).resolve().parent, args.python_home, args.output)
