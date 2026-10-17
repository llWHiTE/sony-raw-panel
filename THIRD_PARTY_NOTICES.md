# Licensing and third-party notices

Sony RAW Panel author: **Alexey Storozhilov**.
Repository: https://github.com/llWHiTE/sony-raw-panel

## Original project work

Original application source and documentation are available under the [MIT License](LICENSE), copyright (c) 2026 Alexey Storozhilov. This does not relicense the runtime or contributed creative assets described below.

## Bundled creative assets

The initial collection in `bundled-luts` (eight `.cube` files and `Sony To Leica.xmp`) was supplied by Alexey Storozhilov, who explicitly authorized redistribution with this project on 2026-10-17. The XMP retains its embedded display name, `Sony To Leica V1 [Meshna]`; filenames and embedded credits are not claims of authorship by this project.

These assets are distributed as supplied under that permission, **not under the project's MIT license**. Permission here covers redistribution with Sony RAW Panel; no separate right to sell or relicense the LUT/preset collection is asserted. Their original authors retain their rights. Users importing additional files must have the necessary rights to use and distribute them. These files are creative colour transforms/presets, not user photographs or proprietary application executables.

No transform is enabled by default. `.cube` files are applied as optional Photoshop Color Lookup layers. XMP is an Adobe Camera Raw preset, including any embedded Look table, and is applied only to a private Adobe sidecar; it is not a Sony RAW recipe.

## Portable runtime

The portable executable contains CPython 3.14, its standard library and binary modules, Tcl/Tk 8.6, and the runtime DLLs shipped with the official CPython Windows installation used for the build. Components retain their own licenses:

- [PYTHON_LICENSE.txt](PYTHON_LICENSE.txt): PSF license, incorporated-component notices, and additional conditions for the Windows binary build, including Microsoft Distributable Code.
- [TCL_LICENSE.txt](TCL_LICENSE.txt): Tcl redistribution terms.
- [TK_LICENSE.txt](TK_LICENSE.txt): Tk redistribution terms.

The extracted runtime also retains its original root `LICENSE.txt`, Tcl/Tk notices, and a `RUNTIME_MANIFEST.txt` listing bundled runtime paths. The MIT license does not supersede these terms. Microsoft Distributable Code is only redistributed for Windows and retains its original notices; the restrictions in the Python Windows-build license apply to it.

The source repository does not contain interpreter binaries. The build script packages a user-supplied official installation and excludes site-packages. Builders are responsible for the terms of the runtime they supply; do not package an arbitrary third-party installation without checking its contents and notices.

## Sony, Adobe and Windows

Adobe Photoshop and Sony Imaging Edge are separate proprietary applications, not included in this project or executable. Their names identify compatible installed applications. This is an independent project, not affiliated with or endorsed by Sony, Adobe, Leica, Ricoh or Microsoft.

The application reads the standard Windows sRGB color profile from the user's operating system. No camera firmware, Sony/Adobe application binaries, sample photographs, local RAW projects, credentials or user image data are distributed in the repository or release. Camera Raw profiles required by Photoshop are not supplied by this application; the user-provided XMP/Look asset is identified separately above.
