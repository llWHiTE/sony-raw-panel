"""Optional portable diagnostics; all images are copied before Sony opens them."""
import importlib.util
import json
from pathlib import Path
import time


def self_check(runtime):
    import tkinter as tk
    import ssl
    root = tk.Tk()
    root.withdraw()
    report = dict(ok=True, data=str(runtime.data_root()), bundle=str(runtime.bundle_root()),
                  tkinter=root.tk.call('info', 'patchlevel'), ssl=ssl.OPENSSL_VERSION,
                  sony=str(runtime.discover_sony() or ''), photoshop=str(runtime.discover_photoshop() or ''))
    root.destroy()
    from recipe_compare import recipe_fingerprint
    from app_info import AUTHOR, GITHUB_URL, VERSION
    report.update(author=AUTHOR, github=GITHUB_URL, version=VERSION)
    (runtime.data_root() / 'self-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


def workflow_check(runtime, source):
    from panel_core import Controller, bridge
    from comparison import PreviewSony
    import xml.etree.ElementTree as ET
    source = Path(source)
    report = dict(ok=False)
    controller = Controller(session=runtime.data_root() / 'verification-session.json')
    try:
        before = bridge.base.sha(source)
        controller.pending = None
        controller.recovery = None
        start = time.monotonic()
        prepared = controller.open(source, first_sony=True)
        assert prepared['prepared'] and prepared['target']['kind'] == 'initial'
        assert not list(bridge.CACHE.glob('*/*.tif'))
        report['prepare_seconds'] = round(time.monotonic()-start, 2)
        initial = controller.apply()
        target = initial['target']
        report['first_apply_seconds'] = initial['seconds']
        controller.edit(target)
        before_jobs = len(list(bridge.CACHE.iterdir()))
        unchanged = controller.apply()
        assert unchanged.get('unchanged')
        assert len(list(bridge.CACHE.iterdir())) == before_jobs
        assert unchanged['target']['revision'] == target['revision']
        report['unchanged_seconds'] = unchanged['seconds']
        report['unchanged_skipped_render'] = True
        controller.edit(target)
        folder, project = bridge.project(target['project'])
        recipe = bridge.settings_path(folder,project,target['revision'])
        tree=ET.parse(recipe)
        found=False
        for parent in tree.iter('dict'):
            children=list(parent)
            for i,node in enumerate(children[:-1]):
                if node.tag=='key' and node.text=='Exposure':
                    children[i+1].text=str(int(children[i+1].text)+100)
                    found=True
        assert found
        changed=runtime.data_root()/'verification-exposure.xml'
        tree.write(changed,encoding='utf-8',xml_declaration=True)
        sony=bridge.Sony()
        sony.load_settings(changed,'SonyRAW-'+target['project']+'.ARW')
        result=controller.apply()
        assert not result.get('unchanged') and result['target']['revision'] != target['revision']
        report['changed_seconds']=result['seconds']
        report['changed_rendered']=True
        report['original_unchanged']=bridge.base.sha(source)==before
        assert report['original_unchanged']
        report['document']=result['target']
        assert not Path(controller.last_render['render']).exists()
        report['tiff_cleaned']=True
        report['ok']=True
    except Exception as error:
        report['error']=str(error)
        raise
    finally:
        (runtime.data_root()/'workflow-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        controller.ps.close()
    return report
