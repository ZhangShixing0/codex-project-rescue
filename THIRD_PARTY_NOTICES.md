# Third-party runtime notices

The application source uses Python's standard library. The portable Windows build
also bundles an unmodified CPython runtime, its required libraries, Tcl/Tk, and
PyInstaller bootloader/runtime files. These components retain their own terms.

- CPython: [upstream license and incorporated-software acknowledgements](docs/licenses/CPython-notices.rst).
  The archive additionally includes the exact `LICENSE.txt` shipped with the build's Python installation.
- Tcl and Tk: [Tcl terms](docs/licenses/Tcl-license.txt), [Tk terms](docs/licenses/Tk-license.txt).
- PyInstaller: [license and bootloader exception](docs/licenses/PyInstaller-COPYING.txt).
- SQLite: [public-domain notice](https://sqlite.org/copyright.html).

Notice sources, retained with their original text:

- https://github.com/python/cpython/blob/3.13/Doc/license.rst
- https://github.com/tcltk/tcl/blob/core-8-6-branch/license.terms
- https://github.com/tcltk/tk/blob/core-8-6-branch/license.terms
- https://github.com/pyinstaller/pyinstaller/blob/v6.16.0/COPYING.txt

`BUILD-INFO.json` in the download identifies the Python, Tcl, SQLite and PyInstaller
versions used for that build. The application's license does not replace these
third-party notices. Rebuilds with different runtimes require a fresh notice review.
