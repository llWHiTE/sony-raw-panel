function sonyApplyLut(doc, lut) {
    if (!lut) return null;
    var file = new File(lut.path);
    if (!file.exists || file.length > 32 * 1024 * 1024) throw new Error('Файл LUT недоступен.');
    file.encoding = 'BINARY';
    if (!file.open('r')) throw new Error('Не удалось открыть LUT.');
    var contents;
    try { contents = file.read(); } finally { file.close(); }
    app.activeDocument = doc;
    var s = stringIDToTypeID;
    var descriptor = new ActionDescriptor();
    var reference = new ActionReference();
    reference.putClass(s('adjustmentLayer'));
    descriptor.putReference(s('null'), reference);
    var layer = new ActionDescriptor();
    layer.putString(s('name'), 'LUT — ' + lut.name);
    var lookup = new ActionDescriptor();
    lookup.putEnumerated(s('lookupType'), s('colorLookupType'), s('3DLUT'));
    lookup.putEnumerated(s('LUTFormat'), s('LUTFormatType'), s('LUTFormatCUBE'));
    lookup.putString(s('LUT3DFileName'), file.name);
    lookup.putData(s('LUT3DFileData'), contents);
    layer.putObject(s('type'), s('colorLookup'), lookup);
    descriptor.putObject(s('using'), s('adjustmentLayer'), layer);
    executeAction(s('make'), descriptor, DialogModes.NO);
    return doc.activeLayer.id;
}
