from pathlib import Path
import subprocess
import unittest


class LiveLutJsTests(unittest.TestCase):
    def test_cube_changes_preserve_sources_and_rollback_and_guard_history_id(self):
        script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
let counter=1,next=4,creations=0;
const doc={id:7,info:{caption:'Sony RAW Panel comparison: test. cache'},historyStates:[1],layers:[]};
function layer(id,name){return {id,name,visible:true,remove(){doc.layers=doc.layers.filter(x=>x!==this);counter++;doc.historyStates.push(counter);},move(){doc.layers=doc.layers.filter(x=>x!==this);doc.layers.unshift(this);if(this.name==='fail')throw Error('move failed');}};}
const sony=layer(2,'Sony'),adobe=layer(3,'Adobe');doc.layers=[adobe,sony];doc.activeLayer=adobe;
Object.defineProperty(doc,'activeHistoryState',{get(){return {layers:doc.layers.slice(),history:doc.historyStates.slice(),counter};},set(v){doc.layers=v.layers;doc.historyStates=v.history;counter=v.counter;}});
const context={app:{activeDocument:doc,open:()=>{throw Error('CUBE must not decode RAW');}},ElementPlacement:{PLACEATBEGINNING:'top'},
 sonyPanelDocument:()=>doc,sonyPanelLayer:(d,id)=>d.layers.find(x=>x.id===id)||null,
 sonyApplyLut:(d,lut)=>{creations++;const l=layer(next++,lut.name);d.layers.unshift(l);d.activeLayer=l;counter++;d.historyStates.push(counter);return l.id;}};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
context.sonyCompareHistoryID=()=>counter;
let view={document:7,sonyLayer:2,adobeLayer:3,previewID:'test',layerCount:2,historyCount:1,historyID:1};
view=context.sonyCompareReplaceLut({view,lut:{kind:'cube',name:'A'}});
assert.strictEqual(doc.layers.length,3);assert(view.lutLayer);assert.strictEqual(doc.layers[0].name,'A');
view=context.sonyCompareReplaceLut({view,lut:{kind:'cube',name:'B'}});
assert.strictEqual(doc.layers.length,3);assert.strictEqual(doc.layers[0].name,'B');
assert.strictEqual(view.sonyLayer,2);assert.strictEqual(view.adobeLayer,3);assert(adobe.visible);
const before=doc.layers.slice();
assert.throws(()=>context.sonyCompareReplaceLut({view,lut:{kind:'cube',name:'fail'}}));
assert.deepStrictEqual(doc.layers,before);
view=context.sonyCompareReplaceLut({view,lut:null});assert.strictEqual(doc.layers.length,2);assert.strictEqual(view.lutLayer,null);
counter++; // Same history count, different active history ID (history limit reached).
const calls=creations;
assert.throws(()=>context.sonyCompareReplaceLut({view,lut:{kind:'cube',name:'A'}}));
assert.strictEqual(creations,calls);
'''
        source=Path(__file__).resolve().parent/'comparison_photoshop.jsx'
        result=subprocess.run(['node','-e',script,str(source)],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
