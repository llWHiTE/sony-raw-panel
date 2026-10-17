import hashlib
import re
from pathlib import Path
import shutil


def adobe_copy(folder, source, ident, expected_sha=None):
    if not re.fullmatch(r'[a-f0-9]{32}', ident):
        raise ValueError('Invalid comparison identifier.')
    def digest(path):
        with path.open('rb') as f:
            return hashlib.file_digest(f, 'sha256').hexdigest()
    before = source.stat()
    expected_sha = expected_sha or digest(source)
    destination = folder / ('AdobeRAW-' + ident + '.ARW')
    sidecar = destination.with_suffix('.xmp')
    if destination.resolve() == source.resolve() or destination.is_symlink() or sidecar.is_symlink():
        raise ValueError('Adobe input must be an independent private copy.')
    if sidecar.exists() and sidecar.stat().st_nlink != 1:
        raise ValueError('Adobe sidecar must not be a hard link.')
    if not destination.exists():
        shutil.copy2(source, destination)
    if destination.stat().st_nlink != 1 or digest(destination) != expected_sha or source.stat().st_mtime_ns != before.st_mtime_ns:
        raise ValueError('Adobe RAW copy verification failed.')
    # This sidecar belongs only to an independent comparison copy, never the user's RAW.
    xmp = '''<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description rdf:about="" xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
 crs:Version="18.6" crs:ProcessVersion="15.4" crs:WhiteBalance="As Shot"
 crs:Exposure2012="0" crs:Contrast2012="0" crs:Highlights2012="0" crs:Shadows2012="0" crs:Whites2012="0" crs:Blacks2012="0"
 crs:Texture="0" crs:Clarity2012="0" crs:Dehaze="0" crs:Vibrance="0" crs:Saturation="0"
 crs:CameraProfile="Camera ST" crs:ToneCurveName2012="Linear" crs:HasSettings="True" crs:HasCrop="False"
 crs:LensProfileEnable="0" crs:AutoLateralCA="0" crs:AutoTone="False" crs:AutoExposure="False">
 <crs:ToneCurvePV2012><rdf:Seq><rdf:li>0, 0</rdf:li><rdf:li>255, 255</rdf:li></rdf:Seq></crs:ToneCurvePV2012>
 </rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>'''
    destination.with_suffix('.xmp').write_text(xmp, encoding='utf-8')
    return destination
