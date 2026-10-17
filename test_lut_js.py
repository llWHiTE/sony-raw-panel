from pathlib import Path
import subprocess
import unittest


class LutJsTests(unittest.TestCase):
    def test_profile_is_embedded_and_missing_profile_cannot_create_inert_layer(self):
        script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const files={'table.cube':'LUT_3D_SIZE 2','table.icc':'x'.repeat(36)+'acsp'+'x'.repeat(100)};
class File {
 constructor(path){this.path=path;this.exists=path in files;this.length=(files[path]||'').length;this.name=path;}
 open(){return this.exists;} read(){return files[this.path];} close(){}
}
class Descriptor {
 constructor(){this.values={};}
 putReference(k,v){this.values[k]=v;} putString(k,v){this.values[k]=v;}
 putEnumerated(k,t,v){this.values[k]=v;} putData(k,v){this.values[k]=v;}
 putObject(k,t,v){this.values[k]=v;}
}
class Reference {putClass(){}}
let calls=0,desc;
const doc={activeLayer:{id:42}};
const context={File,ActionDescriptor:Descriptor,ActionReference:Reference,
 app:{},stringIDToTypeID:x=>x,DialogModes:{NO:0},
 executeAction:(name,d)=>{calls++;desc=d;}};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
assert.strictEqual(context.sonyApplyLut(doc,null),null);
assert.throws(()=>context.sonyApplyLut(doc,{path:'table.cube',name:'test'}));
assert.strictEqual(calls,0);
files['bad.icc']='invalid';
assert.throws(()=>context.sonyApplyLut(doc,{path:'table.cube',name:'test',profile:'bad.icc'}));
assert.strictEqual(calls,0);
assert.strictEqual(context.sonyApplyLut(doc,{path:'table.cube',name:'test',profile:'table.icc'}),42);
const lookup=desc.values.using.values.type.values;
assert.strictEqual(lookup.profile,files['table.icc']);
assert.strictEqual(lookup.LUT3DFileData,files['table.cube']);
assert.strictEqual(calls,1);
'''
        source = Path(__file__).resolve().parent / 'lut_photoshop.jsx'
        result = subprocess.run(['node', '-e', script, str(source)], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
