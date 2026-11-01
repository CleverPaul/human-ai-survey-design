"""Rebuild the portable Windows desktop application using this Python/venv."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop"
PACKAGES = (
    "numpy", "scipy", "pyscipopt", "PySide6", "PySide6_Addons",
    "PySide6_Essentials", "shiboken6", "pyinstaller", "pyinstaller-hooks-contrib",
)


def run(command, env=None):
    print(subprocess.list2cmdline([str(s) for s in command]), flush=True)
    subprocess.run([str(s) for s in command], cwd=ROOT, env=env, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("onedir", "onefile", "both"), default="both")
    parser.add_argument("--work-root", type=Path, default=ROOT.parent / "DesktopBuild_20261101" / "pyinstaller_work")
    parser.add_argument("--zip", action="store_true", help="Also zip the one-folder distribution.")
    parser.add_argument("--skip-notices", action="store_true", help="Reuse previously collected notices.")
    args = parser.parse_args()
    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
        parser.error("Build this Windows x64 application on Windows x64.")
    if not (ROOT / "desktop_app.py").is_file():
        parser.error("Missing desktop_app.py entry point.")
    if not args.skip_notices:
        run([sys.executable, DESKTOP / "collect_notices.py"])
    if not (DESKTOP / "third_party_notices" / "THIRD_PARTY_NOTICES.txt").is_file():
        parser.error("Collect notices before building.")
    dist = (ROOT / "dist").resolve()
    work = args.work_root.resolve()
    # The only overwritten distribution targets are these app-specific paths.
    if dist.parent != ROOT.resolve() or work == ROOT.resolve() or ROOT.resolve() in work.parents:
        parser.error("Build work must be outside the source directory; dist must be code/dist.")
    dist.mkdir(exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    modes = ("onedir", "onefile") if args.mode == "both" else (args.mode,)
    env = os.environ.copy()
    # Exclude inherited virtual-environment Qt paths during dependency analysis.
    for key in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "PYTHONPATH", "SCIPOPTDIR"):
        env.pop(key, None)
    for mode in modes:
        env["SURVEY_BUILD_MODE"] = mode
        run([
            sys.executable, "-m", "PyInstaller", "--noconfirm",
            # Analysis is identical in both modes; reuse its dependency cache.
            "--distpath", dist, "--workpath", work / "shared",
            DESKTOP / "SurveyDesignLab.spec",
        ], env)
    # Also expose readable notices beside the single executable.
    shutil.copytree(DESKTOP / "third_party_notices", dist / "third_party_notices", dirs_exist_ok=True)
    shutil.copy2(DESKTOP / "third_party_notices" / "THIRD_PARTY_NOTICES.txt", dist / "THIRD_PARTY_NOTICES.txt")
    shutil.copy2(DESKTOP / "PORTABLE_README.txt", dist / "README-Windows.txt")
    if (dist / "SurveyDesignLab" / "SurveyDesignLab.exe").is_file():
        shutil.copy2(DESKTOP / "PORTABLE_README.txt", dist / "SurveyDesignLab" / "README.txt")
        shutil.copy2(DESKTOP / "third_party_notices" / "THIRD_PARTY_NOTICES.txt", dist / "SurveyDesignLab" / "THIRD_PARTY_NOTICES.txt")
    if args.zip and (dist / "SurveyDesignLab" / "SurveyDesignLab.exe").is_file():
        with zipfile.ZipFile(dist / "SurveyDesignLab-portable.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in sorted((dist / "SurveyDesignLab").rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(dist))
    inventory = {
        "python": sys.version,
        "platform": platform.platform(),
        "packages": {name: metadata.version(name) for name in PACKAGES},
        "artifacts": {},
    }
    for path in (dist / "SurveyDesignLab.exe", dist / "SurveyDesignLab" / "SurveyDesignLab.exe", dist / "SurveyDesignLab-portable.zip"):
        if path.is_file():
            digest = hashlib.file_digest(path.open("rb"), "sha256").hexdigest() if hasattr(hashlib, "file_digest") else hashlib.sha256(path.read_bytes()).hexdigest()
            inventory["artifacts"][path.relative_to(dist).as_posix()] = {"bytes": path.stat().st_size, "sha256": digest}
    (dist / "build-info.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    print(json.dumps(inventory, indent=2), flush=True)


if __name__ == "__main__":
    main()
