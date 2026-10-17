# Changelog

## 0.5.1 — 2026-10-17

- Fixed DSC04755 portrait orientation: source-relative output sizes now account for EXIF rotations 5–8 before Sony export. Both 100% and 50% comparisons retain the correct 5304:7952 aspect ratio.
- Adobe resizing is proportional only. Incompatible aspect ratios fail explicitly rather than stretching the image; at most a one-pixel canvas adjustment handles rounding.
- New projects record orientation-aware full output dimensions for both direct Sony import and comparison-to-full-size workflows.
- Added a unified **Очистить кэш** button: confirmed disk cache, identified unchanged Photoshop comparison documents, their unchanged Sony RAW tabs, then Photoshop `ALLCACHES`. A clear warning covers global undo-history/clipboard loss; **Больше не показывать** persists only after confirmation and can be re-enabled from the menu.
- Modified or unidentified previews, active work/recovery, user documents, RAW projects and recipes are retained. Sony preview closure verifies the saved recipe before unloading a tab and restores the prior active tab when possible.
- Added optional `.cube` Color Lookup layers to Sony/Adobe previews and final documents; default is **Без LUT** every launch. Local library supports importing and removing entries, including initial assets. Operation snapshots preserve a chosen look after library removal.
- Included eight user-supplied LUTs and `Sony To Leica.xmp` with explicit redistribution permission. XMP is an Adobe-only preset with its own profile/Look table, never misrepresented as a Sony recipe or Camera ST.
- Added the MIT source license for Alexey Storozhilov, separate creative-asset notices, original CPython/Windows/Tcl/Tk licenses and a runtime manifest. Creative assets/runtime are not relicensed under MIT.
- Expanded regression tests and native checks for rotated RAW, preview cleanup, LUT/XMP import, full-size output and warning preferences. Release includes this version-history file as an asset.

## 0.5.0 — 2026-10-17

- Preview resolution is now 100%, 75%, 50% or a saved custom integer percentage (1–100%) of each source ARW's own usable width and height. Dimensions come from TIFF/Exif metadata, not a fixed camera resolution or Sony's last export settings.
- One comparison button starts the preview and then toggles Sony / Adobe; a single full-resolution action uses the currently shown engine.
- Opening, comparison and Apply durations remain visible after completion. Initial Sony preparation and the first Apply can be reported together, excluding manual adjustment time.
- Added **Отменить проявку** for pending/failed operations. Cancellation archives local recovery state without contacting Photoshop/Sony, deleting ready renders, or changing open documents.
- Photoshop host invalidates stale COM references after RPC/JSX errors and reconnects on the next explicit request. Mutating commands are never automatically replayed.
- Reworked the panel layout: no empty comparison placeholder, no forced window resizing, scrollable content for small windows, a fixed footer, contextual target selection and clearer error styling.
- Adobe preview decoding no longer uses the legacy medium-size cap for large percentage previews, avoiding upscaling a smaller decode.
- Added camera-independent dimension, percentage/preference, cancellation and comparison-state regressions. Native preview performance measurements are documented separately.

## 0.4.0 — 2026-10-17

Author: **Alexey Storozhilov**

Repository: https://github.com/llWHiTE/sony-raw-panel

### Workflow

- Added **Сначала настроить в Sony**. Open a private RAW copy in Sony, adjust it, then create the first Photoshop result only when **Применить** is pressed.
- Added semantic Sony-recipe comparison. Applying unchanged development settings skips TIFF export and Photoshop Smart Object replacement.
- Added a Sony / Adobe opening-engine selector. Adobe opens a full-resolution embedded RAW Smart Object with the Camera ST profile.
- Sony / Adobe comparisons support 1600 px, 3000 px and full resolution. Choosing an engine creates the full-resolution working result, independently of preview size.
- Existing retouch layers remain intact when the Sony Smart Object is updated.
- Temporary TIFFs are removed only after Photoshop confirms successful embedding. RAW copies and recipes remain available for future Sony adjustments.

### Portable application

- Added a single Windows x64 EXE containing its Python/Tk runtime; a separate Python installation is not required.
- Application paths are discovered from installed-app registrations and running programs. If discovery fails, launch Sony Edit / Photoshop manually and repeat discovery, or select their executable paths in the panel.
- Writable settings, projects and runtime files are stored in `data` beside the EXE.
- Added author credit, a GitHub link, an About dialog and a program-paths dialog.

### Verification

On the tested Windows 11 / Sony A7R V setup, the source workflow completed initial Sony preparation in 7.7 seconds, first Apply in 5.7 seconds, an unchanged Apply in 0.5 seconds, and a changed-exposure update in 4.4 seconds. These are observed timings, not guarantees for other computers or files.

Verified: original ARW hash unchanged, no TIFF before initial Apply, no render job for unchanged settings, successful update for changed settings, temporary TIFF cleanup, and full-resolution Adobe RAW Smart Object import.

### Limitations

- Requires separately installed Sony Imaging Edge Edit and Adobe Photoshop on Windows. These proprietary applications are not bundled.
- Sony mode embeds a 16-bit Sony-developed image, not a Sony RAW engine inside Camera Raw. Further Sony RAW adjustments use the retained project copy and recipe.
- The EXE is not code-signed; Windows SmartScreen may show a warning. Verify the SHA-256 checksum against the release asset.
- The GitHub repository and release exclude photographs, project data, caches, local application paths and credentials.
