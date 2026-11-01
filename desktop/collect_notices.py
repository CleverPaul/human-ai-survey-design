"""Copy installed licenses and cache versioned upstream notices for the bundle."""
from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import shutil
import ssl
import sys
import urllib.request

HERE = Path(__file__).resolve().parent
OUT = HERE / "third_party_notices"
PACKAGES = (
    "PySide6", "PySide6_Addons", "PySide6_Essentials", "shiboken6",
    "numpy", "scipy", "pyscipopt", "pyinstaller",
)
# Files are cached in the source tree: subsequent builds can run offline.
UPSTREAM = {
    "Qt/LGPL-3.0-only.txt": "https://raw.githubusercontent.com/qt/qtbase/v6.8.3/LICENSES/LGPL-3.0-only.txt",
    "Qt/GPL-3.0-only.txt": "https://raw.githubusercontent.com/qt/qtbase/v6.8.3/LICENSES/GPL-3.0-only.txt",
    "Qt/LGPL-2.1-only.txt": "https://raw.githubusercontent.com/spdx/license-list-data/v3.27.0/text/LGPL-2.1-only.txt",
    "Qt/Qt-GPL-exception-1.0.txt": "https://raw.githubusercontent.com/qt/qtbase/v6.8.3/LICENSES/Qt-GPL-exception-1.0.txt",
    "SCIP/LICENSE.txt": "https://raw.githubusercontent.com/scipopt/scip/v10.0.2/LICENSE",
    "SoPlex/LICENSE.txt": "https://raw.githubusercontent.com/scipopt/soplex/v8.0.2/LICENSE",
    "Ipopt/LICENSE.txt": "https://raw.githubusercontent.com/coin-or/Ipopt/releases/3.14.19/LICENSE",
    "COIN-MUMPS/LICENSE.txt": "https://raw.githubusercontent.com/coin-or-tools/ThirdParty-Mumps/releases/3.0.8/LICENSE",
    "MUMPS-5.8.0/CECILL-C.txt": "https://raw.githubusercontent.com/spdx/license-list-data/v3.27.0/text/CECILL-C.txt",
    "SCIP/build-provenance.txt": "https://raw.githubusercontent.com/scipopt/scipoptsuite-deploy/v0.12.0/.github/workflows/scripts/windows.bash",
}


def ssl_context():
    # Some Windows/Conda installs have a broken machine certificate-store entry.
    # A configured CA bundle still verifies HTTPS; never disable verification.
    for base in (Path(sys.base_prefix), Path(sys.prefix)):
        pem = base / "Library" / "ssl" / "cacert.pem"
        if pem.is_file():
            return ssl.create_default_context(cafile=str(pem))
    return ssl.create_default_context()


def main():
    OUT.mkdir(exist_ok=True)
    inventory = {"packages": {}, "upstream": {}, "qt_source_notices": {}}
    for module in ("QtBase", "QtWebEngine"):
        directory = OUT / "Qt" / f"{module}-6.8.3-licenses"
        provenance_path = directory / "provenance.json"
        if not provenance_path.is_file():
            raise SystemExit(f"Missing exact Qt 6.8.3 source notices: {provenance_path}")
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        for file in provenance["files"]:
            path = directory / file["stored_path"]
            if hashlib.sha256(path.read_bytes()).hexdigest() != file["sha256"]:
                raise SystemExit(f"License-file hash mismatch: {path}")
        inventory["qt_source_notices"][module] = {
            "source_url": provenance["source_url"],
            "source_sha256": provenance["source_sha256"],
            "license_file_count": len(provenance["files"]),
        }
    for name in PACKAGES:
        dist = metadata.distribution(name)
        inventory["packages"][name] = dist.version
        for file in dist.files or []:
            if any(term in str(file).lower() for term in ("license", "copying", "notice", "copyright")):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    destination = OUT / "installed" / name / Path(file)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
    python_license = next((p for p in (Path(sys.base_prefix) / "LICENSE_PYTHON.txt", Path(sys.base_prefix) / "LICENSE.txt") if p.is_file()), None)
    if python_license:
        shutil.copy2(python_license, OUT / "PYTHON-LICENSE.txt")
    context = ssl_context()
    for relative, url in UPSTREAM.items():
        destination = OUT / relative
        if not destination.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            print("Collecting", relative, flush=True)
            request = urllib.request.Request(url, headers={"User-Agent": "SurveyDesignLab-build/1.0"})
            destination.write_bytes(urllib.request.urlopen(request, context=context, timeout=30).read())
        inventory["upstream"][relative] = {"url": url, "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}
    (OUT / "inventory.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    (OUT / "THIRD_PARTY_NOTICES.txt").write_text(
        "Survey Design Lab - bundled third-party software\n"
        "================================================\n\n"
        "This application uses Python, NumPy, SciPy, PySide6/Shiboken6 and Qt, "
        "and PySCIPOpt/SCIP. It is frozen with PyInstaller. Their license texts "
        "are included in installed/ and the named component folders. Exact "
        "package versions and upstream file hashes are in inventory.json.\n\n"
        "Qt and PySide6 are distributed under their applicable open-source "
        "licenses, including GNU LGPL v3. QtWebEngine incorporates Chromium. "
        "License/copyright texts and attribution metadata from the exact "
        "official QtBase and QtWebEngine 6.8.3 source archives are saved in "
        "Qt/QtBase-6.8.3-licenses and Qt/QtWebEngine-6.8.3-licenses. Their "
        "provenance files record original source paths and SHA-256 hashes. "
        "This inclusive source collection also contains build, test, example, "
        "and platform-specific components; it does not claim every listed "
        "component is linked into this Windows app. GNU GPL and LGPL texts "
        "are included in Qt/. The dynamic Qt libraries can be replaced in the "
        "one-folder distribution; desktop/ contains instructions to rebuild "
        "either distribution from application source. No restriction is "
        "imposed here on debugging modifications to these libraries.\n\n"
        "Corresponding upstream source: https://code.qt.io/cgit/pyside/pyside-setup.git/tag/?h=v6.8.3\n"
        "Qt source: https://download.qt.io/archive/qt/6.8/6.8.3/submodules/\n"
        "SCIP: https://github.com/scipopt/scip/tree/v10.0.2\n"
        "SoPlex: https://github.com/scipopt/soplex/tree/v8.0.2\n"
        "PySCIPOpt: https://github.com/scipopt/PySCIPOpt/tree/v6.3.0\n\n"
        "The Windows PySCIPOpt wheel also bundles Ipopt, COIN-MUMPS and Intel "
        "compiler runtime DLLs. Their license texts are in Ipopt/, "
        "COIN-MUMPS/, MUMPS-5.8.0/, and Intel-runtime-2024.1/. The SCIP build "
        "provenance is included in SCIP/. MUMPS 5.8.0 source is available from "
        "https://mumps-solver.org/MUMPS_5.8.0.tar.gz . "
        "The wheel's dependent DLLs are included unchanged. NumPy and SciPy "
        "license files include their bundled numerical-library notices.\n\n"
        "These notices describe third-party components only. They do not "
        "assign an open-source license to the research manuscript or the "
        "application's original research code. No Gurobi package, license, "
        "credentials, or personal datasets are included in this distribution.\n",
        encoding="utf-8",
    )
    print("Notices ready:", OUT, flush=True)


if __name__ == "__main__":
    main()
