import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import development_profiles as profiles
import profile_catalog
import raw_dimensions
from comparison_adobe import adobe_copy


def raw(path, model):
    text = model.encode('ascii') + b'\0'
    path.write_bytes(b'II' + struct.pack('<HI', 42, 8) + struct.pack('<H', 1) +
                     struct.pack('<HHII', 272, 2, len(text), 26) + bytes(4) + text)
    return path


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = raw(self.root / 'photo.ARW', 'ILCE-7RM3')
        self.installed = self.root / 'CameraRaw'
        self.model_dir = self.installed / 'CameraProfiles/Camera/Sony ILCE-7RM3'
        self.model_dir.mkdir(parents=True)
        for name in ('Camera Standard', 'Camera Portrait', 'Camera Vivid', 'Camera Landscape'):
            (self.model_dir / ('Sony ILCE-7RM3 ' + name + '.dcp')).write_bytes(b'installed')
        directory = self.installed / 'CameraProfiles/Adobe Standard'
        directory.mkdir(parents=True)
        (directory / 'Sony ILCE-7RM3 Adobe Standard.dcp').write_bytes(b'installed')
        directory = self.installed / 'Settings/Adobe/Profiles/Adobe Raw'
        directory.mkdir(parents=True)
        for name in ('Adobe Color', 'Adobe Portrait', 'Adobe Neutral'):
            (directory / (name + '.xmp')).write_text('<x xmlns:rdf="%s" xmlns:crs="%s"><rdf:Description crs:UUID="%s" crs:CameraProfile="Adobe Standard" crs:LookTable="table" crs:Table_table="payload" crs:ConvertToGrayscale="False"/></x>' % (profiles.RDF, profiles.CRS, 'A'*32), encoding='utf-8')

    def test_metadata_model_without_loading_image_samples(self):
        self.assertEqual(raw_dimensions.camera_model(self.source), 'ILCE-7RM3')
        raw(self.source, '../outside')
        with self.assertRaises(ValueError):
            raw_dimensions.camera_model(self.source)

    def test_dynamic_catalog_contains_actual_model_profiles(self):
        options = profiles.available_adobe(self.source, [self.installed])
        self.assertEqual([x['id'] for x in options[:6]], list(profiles.ADOBE))
        self.assertIn('dcp:Camera Landscape', [x['id'] for x in options])
        self.assertIn('look:Adobe Neutral', [x['id'] for x in options])
        self.assertEqual(profiles.resolve_adobe(self.source, 'camera_pt', [self.installed])['camera_profile'], 'Camera Portrait')
        (self.model_dir / 'Sony ILCE-7RM3 Camera Vivid.dcp').unlink()
        with self.assertRaises(ValueError):
            profiles.resolve_adobe(self.source, 'camera_vv', [self.installed])

    def test_new_camera_uses_actual_st_pt_vv_names(self):
        for path in self.model_dir.glob('*.dcp'):
            path.unlink()
        for name in ('ST', 'PT', 'VV'):
            (self.model_dir / ('Sony ILCE-7RM3 Camera ' + name + '.dcp')).write_bytes(b'installed')
        for key, name in (('camera_standard', 'ST'), ('camera_pt', 'PT'), ('camera_vv', 'VV')):
            self.assertEqual(profiles.resolve_adobe(self.source, key, [self.installed])['camera_profile'], 'Camera ' + name)

    def test_real_look_parameters_not_inert_name_only(self):
        folder = self.root / 'private'; folder.mkdir()
        resolved = profiles.resolve_adobe(self.source, 'adobe_color', [self.installed])
        private = adobe_copy(folder, self.source, 'a'*32, profile=resolved)
        tree = ET.parse(private.with_suffix('.xmp'))
        params = tree.find('.//{' + profiles.CRS + '}Parameters/{' + profiles.RDF + '}Description')
        self.assertIsNotNone(params)
        self.assertEqual(params.get('{' + profiles.CRS + '}Table_table'), 'payload')
        self.assertEqual(tree.find('.//{' + profiles.CRS + '}Look/{' + profiles.RDF + '}Description').get('{' + profiles.CRS + '}Name'), 'Adobe Color')
        self.assertFalse(self.source.with_suffix('.xmp').exists())

    def test_selected_profile_overrides_preset_look_preserving_exposure(self):
        folder = self.root / 'private'; folder.mkdir()
        private = adobe_copy(folder, self.source, 'b'*32)
        sidecar = private.with_suffix('.xmp')
        tree = ET.parse(sidecar)
        desc = tree.find('.//{' + profiles.RDF + '}Description')
        desc.set('{' + profiles.CRS + '}Exposure2012', '1.25')
        desc.set('{' + profiles.CRS + '}LookTable', 'old')
        desc.set('{' + profiles.CRS + '}Table_old', 'payload')
        ET.SubElement(desc, '{' + profiles.CRS + '}Look')
        tree.write(sidecar, encoding='utf-8')
        profiles.apply_adobe_profile(private, profiles.resolve_adobe(self.source, roots=[self.installed]))
        desc = ET.parse(sidecar).find('.//{' + profiles.RDF + '}Description')
        self.assertEqual(desc.get('{' + profiles.CRS + '}Exposure2012'), '1.25')
        self.assertEqual(desc.get('{' + profiles.CRS + '}CameraProfile'), 'Camera Standard')
        self.assertNotIn('{' + profiles.CRS + '}Table_old', desc.attrib)
        self.assertIsNone(desc.find('{' + profiles.CRS + '}Look'))

    def test_catalog_cache_invalidates_on_installed_profile_change(self):
        data = self.root / 'data'; data.mkdir()
        with patch.object(profile_catalog, 'available_adobe', wraps=profiles.available_adobe) as discover:
            first = profile_catalog.catalog(self.source, data, self.root, [self.installed])
            self.assertFalse(first['cached']);self.assertEqual(discover.call_count, 1)
            second = profile_catalog.catalog(self.source, data, self.root, [self.installed])
            self.assertTrue(second['cached']);self.assertEqual(discover.call_count, 1)
            (self.model_dir / 'Sony ILCE-7RM3 Camera Clear.dcp').write_bytes(b'installed')
            third = profile_catalog.catalog(self.source, data, self.root, [self.installed])
            self.assertFalse(third['cached']);self.assertEqual(discover.call_count, 2)
        self.assertEqual(first['sony'][0]['id'], profiles.DEFAULT)
        self.assertEqual(len(first['sony']), 1)

    def test_observed_sony_profiles_override_seed_without_native_launch(self):
        data=self.root/'data';data.mkdir()
        options=[dict(id='camera_standard',code=2,label='ST'),dict(id='sony:42',code=42,label='New Look')]
        profile_catalog.remember_sony(self.source,data,options)
        result=profile_catalog.catalog(self.source,data,self.root,[self.installed])
        self.assertEqual(result['sony'], options)
        other=raw(self.root/'other.ARW','ILCE-OTHER')
        self.assertEqual(len(profile_catalog.catalog(other,data,self.root,[self.installed])['sony']),1)

    def test_preferences_accept_dynamic_ids_not_unknown_values(self):
        self.assertEqual(profiles.preference('sony:42','sony'),'sony:42')
        self.assertEqual(profiles.preference('dcp:Camera New','adobe'),'dcp:Camera New')
        self.assertEqual(profiles.preference(None,'adobe'),profiles.DEFAULT)
        self.assertEqual(profiles.preference('unknown','sony'),profiles.DEFAULT)


if __name__ == '__main__':
    unittest.main()
