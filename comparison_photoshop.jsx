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

function sonyCompareCall(action, data) {
    var dialogs = app.displayDialogs;
    var adobe = null, sony = null;
    try {
        app.displayDialogs = DialogModes.NO;
        if (action === 'build') {
            sony = app.open(new File(data.sony), OpenDocumentType.TIFF);
            var width = sony.width.as('px'), height = sony.height.as('px');
            sony.activeLayer.name = 'Sony — Imaging Edge';
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
            var profileVerified = /CameraProfile[=\s][\s\S]{0,40}Camera ST/.test(adobeMetadata) || adobeMetadata.indexOf('>Camera ST<') >= 0;
            if (!profileVerified) throw new Error('Camera Raw не подтвердил профиль Camera ST. Сравнение отменено, чтобы не показывать неверно подписанный вариант.');
            if (adobe.colorProfileName !== 'sRGB IEC61966-2.1') {
                adobe.convertProfile('sRGB IEC61966-2.1', Intent.RELATIVECOLORIMETRIC, true, false);
            }
            adobe.resizeImage(UnitValue(width, 'px'), UnitValue(height, 'px'), undefined, ResampleMethod.BICUBIC);
            adobe.activeLayer.duplicate(sony, ElementPlacement.PLACEATBEGINNING);
            adobe.close(SaveOptions.DONOTSAVECHANGES); adobe = null;
            app.activeDocument = sony;
            var adobeLayer = sony.activeLayer;
            adobeLayer.name = 'Adobe — Camera ST';
            var sonyLayer = sony.layers[1];
            var reference = {document: sony.id, sonyLayer: sonyLayer.id, adobeLayer: adobeLayer.id,
                             width: width, height: height, adobeDecodedSize: nativeAdobeSize, profileVerified: profileVerified};
            adobeLayer.visible = false;
            sony.info.caption = 'Sony / Adobe comparison preview. Choose an engine in the Sony RAW panel to create a full-resolution working document.';
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
            if (!/CameraProfile[=\s][\s\S]{0,40}Camera ST/.test(profile) && profile.indexOf('>Camera ST<') < 0) {
                throw new Error('Camera Raw не подтвердил Camera ST для рабочего документа.');
            }
            var actual = [Math.round(doc.width.as('px')), Math.round(doc.height.as('px'))].sort(function(a,b){return a-b;});
            var expected = data.dimensions ? data.dimensions.original.slice(0).sort(function(a,b){return a-b;}) : actual;
            if (actual[0] !== expected[0] || actual[1] !== expected[1]) {
                throw new Error('Camera Raw не выдал полное исходное разрешение: ' + actual.join(' × ') + ', ожидалось ' + expected.join(' × ') + '. Рабочий документ не подтверждён.');
            }
            doc.activeLayer.name = 'Adobe RAW — Camera ST';
            adobe = null;
            return sonyPanelJSON({ok:true, document:doc.id, width:doc.width.as('px'), height:doc.height.as('px'), kind:String(doc.activeLayer.kind), embeddedRaw:true, profileVerified:true});
        }
        if (action === 'close') {
            var doc = sonyPanelDocument(data.document);
            var previousDocument = app.activeDocument;
            var previousDocumentID = previousDocument.id;
            app.activeDocument = doc;
            if (data.modified || (data.historyCount !== undefined && data.historyCount !== doc.historyStates.length) ||
                doc.layers.length !== 2 || !sonyPanelLayer(doc,data.sonyLayer) || !sonyPanelLayer(doc,data.adobeLayer)) {
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
