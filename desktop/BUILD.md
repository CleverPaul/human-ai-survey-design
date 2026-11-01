# Windows desktop application

For a user, open `dist/SurveyDesignLab.exe`. No Python, Conda, Gurobi license,
web server, or external browser is required. This is a native Windows window
with an embedded QtWebEngine view. Survey data and computations remain local.

The alternative folder build is `dist/SurveyDesignLab/SurveyDesignLab.exe`.
Keep its `_internal` directory next to the executable when copying it. The
single-file build extracts its runtime to a temporary directory at startup,
so the folder build usually opens faster.

## Rebuild from source (Windows x64)

Use CPython 3.10 x64 and a dedicated build environment outside this `code`
directory. Do not install these dependencies into an existing research
environment.

```powershell
py -3.10 -m venv ..\DesktopBuild\venv
..\DesktopBuild\venv\Scripts\python.exe -m pip install -r desktop\requirements-build.txt
..\DesktopBuild\venv\Scripts\python.exe desktop\build_windows.py --mode both --zip --work-root ..\DesktopBuild\pyinstaller_work
```

The source tree contains license/copyright texts and attribution metadata
from the exact official QtBase/QtWebEngine 6.8.3 source archives, including
Chromium. Provenance manifests preserve original paths and SHA-256 hashes.
The first build also collects versioned upstream license texts over HTTPS;
subsequent builds reuse them and can run offline with `--skip-notices`.

The build uses PyInstaller's PySide6 hooks for the required Qt plugins,
WebEngine helper process, resources, and translations, and explicitly collects
the PySCIPOpt wheel's dependent DLLs. It excludes Gurobi and other Qt bindings.
`dist/build-info.json` records versions and executable SHA-256 hashes.

## Automated packaged-app check

```powershell
..\DesktopBuild\venv\Scripts\python.exe desktop\verify_release.py dist\SurveyDesignLab\SurveyDesignLab.exe --report ..\onedir_selftest.json --screenshot ..\onedir.png
..\DesktopBuild\venv\Scripts\python.exe desktop\verify_release.py dist\SurveyDesignLab.exe --report ..\onefile_selftest.json --screenshot ..\onefile.png
```

This launches the frozen program from an empty temporary working directory,
removes Python/Conda/Qt environment variables, and leaves only Windows system
directories on PATH. It drives the real embedded interface through initial
solution, changed controls, JSON export, and a risk-frontier calculation.
Use the JSON report and process exit code to check success; the GUI build has
no console. This check does not replace testing on a separate Windows PC.

Third-party license texts are bundled under `third_party_notices` (inside
`_internal` for the folder build). To replace a Qt shared library, use the
folder build and replace its compatible DLL in `_internal/PySide6`; rebuilding
from the supplied source and spec also permits changing the linked libraries.
No license for the original research work is assigned by these build files.
