# Changelog

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
