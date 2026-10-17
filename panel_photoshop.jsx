function sonyPanelJSON(value) {
    if (value === null || typeof value === 'undefined') return 'null';
    if (typeof value === 'boolean' || typeof value === 'number') return String(value);
    if (typeof value === 'string') return '"' + value.replace(/[\\"\x00-\x1f]/g, function (c) {
        return '\\u' + ('0000' + c.charCodeAt(0).toString(16)).slice(-4);
    }) + '"';
    var items = [], key;
    if (value instanceof Array) {
        for (key = 0; key < value.length; key++) items.push(sonyPanelJSON(value[key]));
        return '[' + items.join(',') + ']';
    }
    for (key in value) if (value.hasOwnProperty(key)) items.push(sonyPanelJSON(key) + ':' + sonyPanelJSON(value[key]));
    return '{' + items.join(',') + '}';
}

function sonyPanelReference(layer) {
    if (layer.typename !== 'ArtLayer' || layer.kind !== LayerKind.SMARTOBJECT) return null;
    var ref = new ActionReference();
    ref.putIdentifier(charIDToTypeID('Lyr '), layer.id);
    var desc = executeActionGet(ref).getObjectValue(stringIDToTypeID('smartObject'));
    if (desc.hasKey(stringIDToTypeID('linked')) && desc.getBoolean(stringIDToTypeID('linked'))) return null;
    var name = desc.getString(stringIDToTypeID('fileReference'));
    var match = /^SonyRAW-([a-f0-9]{32})(?:-([a-f0-9]{32}))?\.tif$/i.exec(name);
    if (!match) return null;
    return {project: match[1].toLowerCase(), revision: match[2] ? match[2].toLowerCase() : null};
}

function sonyPanelLayers(container, output) {
    for (var i = 0; i < container.layers.length; i++) {
        var layer = container.layers[i];
        if (layer.typename === 'LayerSet') sonyPanelLayers(layer, output);
        else {
            var reference = sonyPanelReference(layer);
            if (reference) {
                reference.layer = layer.id;
                reference.name = layer.name;
                output.push(reference);
            }
        }
    }
}

function sonyPanelDocument(id) {
    for (var i = 0; i < app.documents.length; i++) if (app.documents[i].id === id) return app.documents[i];
    throw new Error('Исходный документ закрыт. Откройте его в Photoshop перед применением.');
}

function sonyPanelLayer(container, id) {
    for (var i = 0; i < container.layers.length; i++) {
        var layer = container.layers[i];
        if (layer.id === id) return layer;
        if (layer.typename === 'LayerSet') {
            var nested = sonyPanelLayer(layer, id);
            if (nested) return nested;
        }
    }
    return null;
}

function sonyPanelTarget(data) {
    var doc = sonyPanelDocument(data.document);
    var previous = app.activeDocument;
    try {
        app.activeDocument = doc;
        var layer = sonyPanelLayer(doc, data.layer);
        if (!layer) throw new Error('Слой Sony RAW удалён. Проявка не будет применена к другому слою.');
        var ref = sonyPanelReference(layer);
        if (!ref || ref.project !== data.project || ref.revision !== data.revision) {
            throw new Error('Содержимое Sony-слоя изменилось после начала коррекции. Повторная замена отменена.');
        }
        return {doc: doc, layer: layer, reference: ref};
    } finally { app.activeDocument = previous; }
}

function sonyPanelDescribe(doc, layer) {
    var target = sonyPanelReference(layer);
    target.document = doc.id;
    target.documentName = doc.name;
    target.layer = layer.id;
    target.name = layer.name;
    return target;
}

function sonyPanelCall(action, data) {
    var dialogs = app.displayDialogs;
    try {
        if (action === 'status') {
            var targets = [], documentName = null, selectedLayer = null, documentID = null;
            if (app.documents.length) {
                var active = app.activeDocument;
                documentName = active.name;
                documentID = active.id;
                selectedLayer = active.activeLayer.id;
                sonyPanelLayers(active, targets);
                for (var i = 0; i < targets.length; i++) {
                    targets[i].document = active.id;
                    targets[i].documentName = active.name;
                }
            }
            return sonyPanelJSON({ok: true, running: true, document: documentID, documentName: documentName,
                selectedLayer: selectedLayer, targets: targets});
        }
        if (action === 'validate') {
            sonyPanelTarget(data);
            return sonyPanelJSON({ok: true});
        }
        app.displayDialogs = DialogModes.NO;
        if (action === 'open') {
            var file = new File(data.render);
            if (!file.exists) throw new Error('Временный TIFF не найден.');
            var doc = app.open(file, OpenDocumentType.TIFF, true);
            if (doc.mode !== DocumentMode.RGB || doc.bitsPerChannel !== BitsPerChannelType.SIXTEEN) {
                throw new Error('Photoshop не создал 16-битный RGB-документ.');
            }
            if (doc.colorProfileName !== 'sRGB IEC61966-2.1') {
                doc.convertProfile('sRGB IEC61966-2.1', Intent.RELATIVECOLORIMETRIC, true, false);
            }
            var info = sonyPanelReference(doc.activeLayer);
            if (!info || info.project !== data.project || info.revision !== data.token) {
                throw new Error('Не удалось проверить встроенный Sony-смарт-объект.');
            }
            doc.activeLayer.name = 'Sony RAW — ' + (data.sourceName || data.project.substring(0, 8));
            doc.info.caption = 'Sony RAW Panel\nOriginal: ' + (data.source || '') + '\nProject: ' + data.project +
                '\nKeep the original ARW and the sony-raw-prototype/projects folder.';
            return sonyPanelJSON({ok: true, target: sonyPanelDescribe(doc, doc.activeLayer)});
        }
        if (action === 'replace') {
            var target = sonyPanelTarget(data.target);
            app.activeDocument = target.doc;
            var previousLayer = target.doc.activeLayer;
            var name = target.layer.name;
            var file = new File(data.render.render);
            if (!file.exists) throw new Error('Готовый TIFF больше не существует.');
            try {
                target.doc.activeLayer = target.layer;
                var replacement = new ActionDescriptor();
                replacement.putPath(charIDToTypeID('null'), file);
                executeAction(stringIDToTypeID('placedLayerReplaceContents'), replacement, DialogModes.NO);
                var ref = sonyPanelReference(target.doc.activeLayer);
                if (target.doc.activeLayer.id !== data.target.layer || !ref ||
                    ref.project !== data.render.project || ref.revision !== data.render.token) {
                    throw new Error('Photoshop не подтвердил обновление Sony-смарт-объекта.');
                }
                target.doc.activeLayer.name = name;
                var updated = sonyPanelDescribe(target.doc, target.doc.activeLayer);
            } finally { target.doc.activeLayer = previousLayer; }
            return sonyPanelJSON({ok: true, target: updated});
        }
        throw new Error('Неизвестная команда Photoshop: ' + action);
    } catch (e) {
        return sonyPanelJSON({ok: false, error: e.message});
    } finally { app.displayDialogs = dialogs; }
}
