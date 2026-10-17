from pathlib import Path
import json
import subprocess
import unittest


class GeometryJS(unittest.TestCase):
    def test_aspect_ratio_and_purge_target_without_real_document_changes(self):
        source=Path(__file__).resolve().parent/'comparison_photoshop.jsx'
        script='''const fs=require('fs'),vm=require('vm'),assert=require('assert');
const app={displayDialogs:'normal',purge:(target)=>{assert.strictEqual(target,'ALL');app.purged=true;}};
const context={app,DialogModes:{NO:'no'},PurgeTarget:{ALLCACHES:'ALL'},sonyPanelJSON:JSON.stringify};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
let r=context.sonyCompareScale(5304,7952,2652,3976);assert.strictEqual(r.width,2652);assert.strictEqual(r.height,3976);
assert.throws(()=>context.sonyCompareScale(5304,7952,3976,2652));
r=context.sonyCompareScale(6001,4001,1980,1320);assert.strictEqual(r.width,1980);
const result=JSON.parse(context.sonyCompareCall('purge',{}));assert(result.purged);assert(app.purged);assert.strictEqual(app.displayDialogs,'normal');
console.log('geometry and explicit full purge passed');'''
        result=subprocess.run(['node','-e',script,str(source)],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
