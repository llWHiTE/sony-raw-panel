function sonyCompareOptions(edge, full) {
    var options = new CameraRAWOpenOptions();
    options.colorSpace = ColorSpaceType.SRGB;
    options.bitsPerChannel = BitsPerChannelType.SIXTEEN;
    // Legacy CameraRAWSize.MAXIMUM is capped below modern Sony sensor resolution.
    if (!full && edge && edge <= 2048) {
        options.size = CameraRAWSize.SMALL;
    }
    return options;
}

function sonyCompareScale(sourceWidth, sourceHeight, width, height) {
    var scale = Math.min(width / sourceWidth, height / sourceHeight);
    var scaledWidth = Math.round(sourceWidth * scale);
    var scaledHeight = Math.round(sourceHeight * scale);
    if (Math.abs(scaledWidth - width) > 1 || Math.abs(scaledHeight - height) > 1) {
        throw new Error('Пропорции Sony и Adobe отличаются. Растягивание изображения запрещено.');
    }
    return {width:scaledWidth, height:scaledHeight};
}

function sonyCompareProfileVerified(metadata, data) {
    function property(text, name, value) {
        var escaped = String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        return new RegExp('(?:[\\w.-]+:)?' + name + '\\s*=\\s*["\\\']' + escaped + '["\\\']').test(text) ||
            new RegExp('<(?:[\\w.-]+:)?' + name + '(?:\\s[^>]*)?>' + escaped + '</(?:[\\w.-]+:)?' + name + '>').test(text);
    }
    var base = data.adobeProfile || 'Camera ST';
    var lookPattern = /<(?:[\w.-]+:)?Look(?:\s[^>]*)?>[\s\S]*?<\/(?:[\w.-]+:)?Look>/;
    if (!property(metadata.replace(lookPattern, ''), 'CameraProfile', base)) return false;
    var look = metadata.match(lookPattern);
    if (data.adobeProfileLabel && !data.adobeLook && look) return false;
    if (data.adobeLook) {
        if (!look || !property(look[0], 'Name', data.adobeLook) ||
            !property(look[0], 'UUID', data.adobeLookUUID)) return false;
    }
    return true;
}

function sonyCompareCall(action, data) {
    var dialogs = app.displayDialogs;
    var adobe = null, sony = null;
    try {
        app.displayDialogs = DialogModes.NO;
        if (action === 'build') {
            sony = app.open(new File(data.sony), OpenDocumentType.TIFF);
            var width = sony.width.as('px'), height = sony.height.as('px');
            sony.activeLayer.name = 'Sony — ' + (data.sonyProfile ? data.sonyProfile.label : 'Imaging Edge');
            adobe = app.open(new File(data.adobe), sonyCompareOptions(data.edge, false));
            var nativeAdobeSize = [adobe.width.as('px'), adobe.height.as('px')];
            if (nativeAdobeSize[0] < width || nativeAdobeSize[1] < height) {
                adobe.close(SaveOptions.DONOTSAVECHANGES);
                adobe = app.open(new File(data.adobe), sonyCompareOptions(0, true));
                nativeAdobeSize = [adobe.width.as('px'), adobe.height.as('px')];
                if (nativeAdobeSize[0] < width || nativeAdobeSize[1] < height) {
                    throw new Error('Adobe RAW меньше запрошенного предпросмотра. Увеличение превью не выполняется.');
                }
            }
            var adobeMetadata = adobe.xmpMetadata.rawData;
            var expectedProfile = data.adobeProfile || 'Camera ST';
            var profileVerified = sonyCompareProfileVerified(adobeMetadata, data);
            if (!profileVerified) throw new Error('Camera Raw не подтвердил выбранный профиль: ' + (data.adobeProfileLabel || expectedProfile));
            if (adobe.colorProfileName !== 'sRGB IEC61966-2.1') {
                adobe.convertProfile('sRGB IEC61966-2.1', Intent.RELATIVECOLORIMETRIC, true, false);
            }
            var scaled = sonyCompareScale(nativeAdobeSize[0], nativeAdobeSize[1], width, height);
            adobe.resizeImage(UnitValue(scaled.width, 'px'), undefined, undefined, ResampleMethod.BICUBIC);
            if (adobe.width.as('px') !== width || adobe.height.as('px') !== height) {
                adobe.resizeCanvas(UnitValue(width, 'px'), UnitValue(height, 'px'), AnchorPosition.MIDDLECENTER);
            }
            adobe.activeLayer.duplicate(sony, ElementPlacement.PLACEATBEGINNING);
            adobe.close(SaveOptions.DONOTSAVECHANGES); adobe = null;
            app.activeDocument = sony;
            var adobeLayer = sony.activeLayer;
            adobeLayer.name = 'Adobe — ' + (data.adobeProfileLabel || expectedProfile) + (data.lut && data.lut.kind === 'xmp' ? ' / ' + data.lut.name : '');
            var sonyLayer = sony.layers[1];
            var reference = {document: sony.id, sonyLayer: sonyLayer.id, adobeLayer: adobeLayer.id,
                             width: width, height: height, adobeDecodedSize: nativeAdobeSize, profileVerified: profileVerified, previewID:data.id};
            adobeLayer.visible = false;
            if (data.lut && data.lut.kind === 'cube') reference.lutLayer = sonyApplyLut(sony, data.lut);
            reference.layerCount = sony.layers.length;
            sony.info.caption = 'Sony RAW Panel comparison: ' + data.id + '. Choose an engine in the panel to create a full-resolution working document.';
            reference.historyCount = sony.historyStates.length;
            return sonyPanelJSON({ok:true, comparison:reference});
        }
        if (action === 'inspect') {
            var inspected = sonyPanelDocument(data.document);
            return sonyPanelJSON({ok:true, historyCount:inspected.historyStates.length});
        }
        if (action === 'show') {
            var doc = sonyPanelDocument(data.document);
            app.activeDocument = doc;
            var a = sonyPanelLayer(doc, data.adobeLayer), s = sonyPanelLayer(doc, data.sonyLayer);
            if (!a || !s) throw new Error('Слои сравнения удалены.');
            var modified = data.modified || (data.historyCount !== undefined && data.historyCount !== doc.historyStates.length);
            a.visible = data.engine === 'adobe'; s.visible = true;
            return sonyPanelJSON({ok:true, historyCount:doc.historyStates.length, modified:modified});
        }
        if (action === 'adobeFull') {
            var doc = app.open(new File(data.adobe), sonyCompareOptions(0, true), true);
            adobe = doc;
            if (doc.activeLayer.kind !== LayerKind.SMARTOBJECT || doc.bitsPerChannel !== BitsPerChannelType.SIXTEEN) {
                throw new Error('Adobe RAW не открылся как 16-битный смарт-объект.');
            }
            var rawRef = new ActionReference(); rawRef.putIdentifier(charIDToTypeID('Lyr '), doc.activeLayer.id);
            var rawInfo = executeActionGet(rawRef).getObjectValue(stringIDToTypeID('smartObject'));
            var rawName = rawInfo.getString(stringIDToTypeID('fileReference'));
            if (!/\.ARW$/i.test(rawName) || (rawInfo.hasKey(stringIDToTypeID('linked')) && rawInfo.getBoolean(stringIDToTypeID('linked')))) {
                throw new Error('Adobe не подтвердил встроенный исходный RAW.');
            }
            var profile = doc.xmpMetadata.rawData;
            var fullProfile = data.adobeProfile || 'Camera ST';
            if (!sonyCompareProfileVerified(profile, data)) {
                throw new Error('Camera Raw не подтвердил выбранный профиль: ' + fullProfile);
            }
            var actual = [Math.round(doc.width.as('px')), Math.round(doc.height.as('px'))];
            var expected = data.dimensions ? data.dimensions.original.slice(0) : actual;
            if (actual[0] !== expected[0] || actual[1] !== expected[1]) {
                throw new Error('Camera Raw не выдал полное исходное разрешение: ' + actual.join(' × ') + ', ожидалось ' + expected.join(' × ') + '. Рабочий документ не подтверждён.');
            }
            doc.activeLayer.name = 'Adobe RAW — ' + (data.adobeProfileLabel || fullProfile);
            var rawKind = String(doc.activeLayer.kind);
            if (data.lut && data.lut.kind === 'cube') sonyApplyLut(doc, data.lut);
            adobe = null;
            return sonyPanelJSON({ok:true, document:doc.id, width:doc.width.as('px'), height:doc.height.as('px'), kind:rawKind, embeddedRaw:true, profileVerified:true, adobeProfile:fullProfile, adobeLook:data.adobeLook || null, adobeProfileLabel:data.adobeProfileLabel || fullProfile});
        }
        if (action === 'purge') {
            app.purge(PurgeTarget.ALLCACHES);
            return sonyPanelJSON({ok:true, purged:true});
        }
        if (action === 'close') {
            var exists = false;
            for (var i = 0; i < app.documents.length; i++) {
                if (app.documents[i].id === data.document) exists = true;
            }
            if (!exists) return sonyPanelJSON({ok:true, absent:true});
            var doc = sonyPanelDocument(data.document);
            var previousDocument = app.activeDocument;
            var previousDocumentID = previousDocument.id;
            app.activeDocument = doc;
            if (!data.previewID || doc.info.caption.indexOf('Sony RAW Panel comparison: ' + data.previewID + '.') !== 0 ||
                data.modified || (data.historyCount !== undefined && data.historyCount !== doc.historyStates.length) ||
                doc.layers.length !== (data.layerCount || 2) || !sonyPanelLayer(doc,data.sonyLayer) || !sonyPanelLayer(doc,data.adobeLayer) ||
                (data.lutLayer && !sonyPanelLayer(doc,data.lutLayer))) {
                app.activeDocument = previousDocument;
                throw new Error('Документ сравнения изменён; он оставлен открытым.');
            }
            doc.close(SaveOptions.DONOTSAVECHANGES);
            if (previousDocumentID !== data.document) app.activeDocument = previousDocument;
            return sonyPanelJSON({ok:true});
        }
        throw new Error('Неизвестная команда сравнения.');
    } catch(e) {
        if (adobe) adobe.close(SaveOptions.DONOTSAVECHANGES);
        if (action==='build' && sony) sony.close(SaveOptions.DONOTSAVECHANGES);
        return sonyPanelJSON({ok:false,error:e.message});
    } finally { app.displayDialogs = dialogs; }
}
