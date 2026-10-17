import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import runtime_paths


class RuntimeRootsTests(unittest.TestCase):
    def test_development_roots_are_module_folder(self):
        with mock.patch.object(runtime_paths, "_is_frozen", return_value=False):
            self.assertEqual(runtime_paths.bundle_root(), Path(runtime_paths.__file__).resolve().parent)
            self.assertEqual(runtime_paths.data_root(), Path(runtime_paths.__file__).resolve().parent)

    def test_frozen_roots_use_bundle_and_executable_data_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            executable = base / "SonyRaw.exe"
            executable.touch()
            bundle = base / "bundle"
            bundle.mkdir()
            with (
                mock.patch.dict(os.environ, {}, clear=True),
                mock.patch.object(runtime_paths, "_is_frozen", return_value=True),
                mock.patch.object(sys, "executable", str(executable)),
                mock.patch.object(sys, "_MEIPASS", str(bundle), create=True),
            ):
                self.assertEqual(runtime_paths.bundle_root(), bundle)
                self.assertEqual(runtime_paths.data_root(), base / "data")
                self.assertTrue((base / "data").is_dir())

    def test_launcher_portable_home_wins_over_frozen_location(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "portable"
            with mock.patch.dict(os.environ, {"SONY_RAW_PORTABLE_HOME": str(home)}):
                self.assertEqual(runtime_paths.data_root(), home / "data")
                self.assertTrue((home / "data").is_dir())


class ConfigurationTests(unittest.TestCase):
    def test_config_round_trip_requires_named_existing_executables(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sony = root / "Edit.exe"
            photoshop = root / "Photoshop.exe"
            sony.touch()
            photoshop.touch()
            with mock.patch.object(runtime_paths, "data_root", return_value=root / "data"):
                written = runtime_paths.save_path_config(sony=sony, photoshop=photoshop)
                loaded = runtime_paths.load_path_config()
            self.assertEqual(written.sony, sony.resolve())
            self.assertEqual(written.photoshop, photoshop.resolve())
            self.assertEqual(loaded, written)

    def test_config_rejects_missing_or_wrong_named_executables(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "not-edit.exe"
            candidate.touch()
            with self.assertRaises(ValueError):
                runtime_paths.save_path_config(sony=candidate)

    def test_stale_config_entry_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"
            data.mkdir()
            (data / "settings.json").write_text(
                '{"sony": "C:/gone/Edit.exe", "photoshop": null}', encoding="utf-8"
            )
            with mock.patch.object(runtime_paths, "data_root", return_value=data):
                self.assertEqual(runtime_paths.load_path_config(), runtime_paths.PathConfig())


class DiscoveryTests(unittest.TestCase):
    def test_discover_sony_uses_registry_install_location(self):
        with tempfile.TemporaryDirectory() as directory:
            install = Path(directory) / "Imaging Edge"
            edit = install / "Edit" / "Edit.exe"
            edit.parent.mkdir(parents=True)
            edit.touch()
            with (
                mock.patch.object(runtime_paths, "_registry_install_locations", return_value=iter([install])),
                mock.patch.object(runtime_paths, "_running_process_paths", return_value=iter(())),
            ):
                self.assertEqual(runtime_paths.discover_sony(), edit.resolve())

    def test_discover_sony_uses_running_process_when_registry_misses(self):
        with tempfile.TemporaryDirectory() as directory:
            edit = Path(directory) / "Edit.exe"
            edit.touch()
            with (
                mock.patch.object(runtime_paths, "_registry_install_locations", return_value=iter(())),
                mock.patch.object(runtime_paths, "_running_process_paths", return_value=iter([edit])),
            ):
                self.assertEqual(runtime_paths.discover_sony(), edit.resolve())

    def test_discover_photoshop_checks_window_then_registry_and_com(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / "Photoshop.exe"
            app.touch()
            with (
                mock.patch.object(runtime_paths, "_window_process_paths", return_value=iter(())),
                mock.patch.object(runtime_paths, "_registry_photoshop_app_paths", return_value=iter(())),
                mock.patch.object(runtime_paths, "_registry_photoshop_com_servers", return_value=iter([app])),
            ):
                self.assertEqual(runtime_paths.discover_photoshop(), app.resolve())

    def test_resolve_sony_gives_actionable_russian_error(self):
        with (
            mock.patch.object(runtime_paths, "load_path_config", return_value=runtime_paths.PathConfig()),
            mock.patch.object(runtime_paths, "discover_sony", return_value=None),
        ):
            with self.assertRaisesRegex(RuntimeError, "Запустите Sony Edit вручную"):
                runtime_paths.resolve_sony()


if __name__ == "__main__":
    unittest.main()
