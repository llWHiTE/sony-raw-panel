from pathlib import Path
import subprocess
import unittest


class ProfileRefreshJsTests(unittest.TestCase):
    def test_only_requested_branch_replaced_and_history_rollback(self):
        script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
let history=1,next=10;
const doc={id:7,info:{caption:'Sony RAW Panel comparison: test. ready'},layers:[],historyStates:[1]};
function layer(id,name){return {id,name,visible:true,remove(){doc.layers=doc.layers.filter(x=>x!==this);history++;doc.historyStates.push(history);},move(old){doc.layers=doc.layers.filter(x=>x!==this);doc.layers.splice(doc.layers.indexOf(old),0,this);},duplicate(){const result=layer(next++,this.name);doc.layers.unshift(result);return result;}};}
const sony=layer(2,'Sony'),adobe=layer(3,'Adobe'),lut=layer(4,'LUT');adobe.visible=false;
doc.layers=[lut,adobe,sony];doc.activeLayer=sony;
Object.defineProperty(doc,'activeHistoryState',{get(){return {layers:doc.layers.slice(),history:doc.historyStates.slice(),id:history};},set(v){doc.layers=v.layers;doc.historyStates=v.history;history=v.id;}});
let wrong=false;
function temporary(){return {width:{as(){return wrong?99:796.0000000000001;}},height:{as(){return 1193;}},bitsPerChannel:'16',activeLayer:layer(99,'decoded'),close(){}};}
const context={app:{activeDocument:doc,open:temporary},File:function(p){this.path=p;},OpenDocumentType:{TIFF:'tiff'},BitsPerChannelType:{SIXTEEN:'16'},SaveOptions:{DONOTSAVECHANGES:0},ElementPlacement:{PLACEATBEGINNING:'top',PLACEBEFORE:'before'},sonyPanelDocument:()=>doc,sonyPanelLayer:(d,id)=>d.layers.find(l=>l.id===id)||null};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
context.sonyCompareHistoryID=()=>history;context.sonyCompareAdobePreview=()=>({document:temporary()});
let view={document:7,previewID:'test',sonyLayer:2,adobeLayer:3,lutLayer:4,layerCount:3,historyCount:1,historyID:1,width:796,height:1193};
view=context.sonyCompareRefresh({view,engine:'sony',sony:'ready.tif',sonyProfile:{label:'Portrait'}});
assert.strictEqual(view.adobeLayer,3);assert.strictEqual(doc.layers[0],lut);assert.strictEqual(doc.layers[1],adobe);assert.strictEqual(adobe.visible,false);assert.strictEqual(doc.layers.length,3);
const newSony=view.sonyLayer;
view=context.sonyCompareRefresh({view,engine:'adobe',adobeProfileLabel:'Adobe Color'});
assert.strictEqual(view.sonyLayer,newSony);assert.strictEqual(doc.layers[0],lut);assert.strictEqual(doc.layers[1].visible,false);assert.strictEqual(doc.layers.length,3);
const before=doc.layers.slice();wrong=true;
assert.throws(()=>context.sonyCompareRefresh({view,engine:'sony',sonyProfile:{label:'Standard'}}));assert.deepStrictEqual(doc.layers,before);
history++;
assert.throws(()=>context.sonyCompareRefresh({view,engine:'adobe'}));assert.deepStrictEqual(doc.layers,before);
'''
        result=subprocess.run(['node','-e',script,str(Path(__file__).resolve().parent/'comparison_photoshop.jsx')],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
