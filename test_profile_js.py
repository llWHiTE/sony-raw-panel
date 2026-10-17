from pathlib import Path
import subprocess
import unittest


class ProfileJsTests(unittest.TestCase):
    def test_profile_and_look_must_match_actual_properties(self):
        script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const context={};vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
const verify=context.sonyCompareProfileVerified;
assert(verify('<crs:CameraProfile>Camera Standard</crs:CameraProfile>',{adobeProfile:'Camera Standard'}));
assert(!verify('<crs:Description>Camera Standard</crs:Description>',{adobeProfile:'Camera Standard'}));
assert(!verify('<crs:CameraProfile>Camera ST</crs:CameraProfile>',{adobeProfile:'Camera Standard'}));
assert(verify('<rdf:Description crs:CameraProfile="Camera ST"/>',{adobeProfile:'Camera ST'}));
const data={adobeProfile:'Adobe Standard',adobeLook:'Adobe Color',adobeLookUUID:'ABC123'};
const metadata='<crs:CameraProfile>Adobe Standard</crs:CameraProfile><crs:Look rdf:parseType="Resource"><crs:Name>Adobe Color</crs:Name><crs:UUID>ABC123</crs:UUID></crs:Look>';
assert(verify(metadata,data));
assert(!verify(metadata,{adobeProfile:'Adobe Standard',adobeProfileLabel:'Adobe Standard'}));
const nested='<crs:CameraProfile>Camera Standard</crs:CameraProfile><crs:Look><crs:Name>Adobe Color</crs:Name><crs:UUID>ABC123</crs:UUID><crs:Parameters><crs:CameraProfile>Adobe Standard</crs:CameraProfile></crs:Parameters></crs:Look>';
assert(!verify(nested,data));
assert(!verify(metadata.replace('Adobe Color','Adobe Portrait'),data));
assert(!verify(metadata.replace('ABC123','WRONG'),data));
assert(!verify('<crs:Name>Adobe Color</crs:Name><crs:UUID>ABC123</crs:UUID><crs:CameraProfile>Adobe Standard</crs:CameraProfile>',data));
'''
        source = Path(__file__).resolve().parent / 'comparison_photoshop.jsx'
        result = subprocess.run(['node', '-e', script, str(source)], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
