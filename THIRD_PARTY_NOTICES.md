# Third-party runtime notices

Sony RAW Panel author: Alexey Storozhilov.
Repository: https://github.com/llWHiTE/sony-raw-panel

The portable executable contains a copy of CPython 3.14, its standard library and binary modules, Tcl/Tk 8.6, and the runtime DLLs shipped with that CPython installation. CPython and bundled components retain their respective copyright and license notices. The original Python `LICENSE.txt` is included at the root of the extracted runtime and covers Python and the standard-library components listed there. Tcl/Tk license files are retained under the extracted `tcl` directory.

The runtime is redistributed from the official local Python installation used to build this release, without installing it on the recipient's computer. The source repository does not include Python binaries; the build script packages a user-supplied installation.

Adobe Photoshop and Sony Imaging Edge are separate proprietary applications, not included in this project or executable. Their names are used only to identify compatible installed applications. This is an independent project, not affiliated with or endorsed by Sony or Adobe.

The application reads the standard Windows sRGB color profile from the user's operating system. No camera firmware, Sony/Adobe application binaries, proprietary camera profiles, sample photographs or user image data are redistributed in the repository or release.
