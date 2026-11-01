# -*- mode: python ; coding: utf-8 -*-
"""Shared one-folder/one-file build; use build_windows.py to select the mode."""
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_delvewheel_libs_directory

project = Path(SPECPATH).parent.resolve()
desktop = project / "desktop"
mode = os.environ.get("SURVEY_BUILD_MODE", "onedir")
if mode not in {"onedir", "onefile"}:
    raise ValueError("SURVEY_BUILD_MODE must be onedir or onefile")

# Preserve the delvewheel wheel layout and its full dependent DLL chain.
scip_datas, scip_binaries = collect_delvewheel_libs_directory("pyscipopt")
datas = [
    (str(project / "web"), "web"),
    (str(desktop / "third_party_notices"), "third_party_notices"),
] + scip_datas

a = Analysis(
    [str(project / "desktop_app.py")],
    pathex=[str(project)],
    binaries=scip_binaries,
    datas=datas,
    hiddenimports=["pyscipopt", "pyscipopt.scip", "siliconsurvey.scip_backend"],
    hookspath=[str(desktop / "hooks")],
    runtime_hooks=[str(desktop / "runtime_environment.py")],
    excludes=[
        "gurobipy", "PyQt5", "PyQt6", "PySide2", "tkinter", "matplotlib",
        "pandas", "sklearn", "IPython", "jupyter", "notebook", "pytest",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
common = dict(
    name="SurveyDesignLab", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, disable_windowed_traceback=False,
    argv_emulation=False, target_arch=None, codesign_identity=None,
    entitlements_file=None,
)
if mode == "onefile":
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], **common)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **common)
    coll = COLLECT(
        exe, a.binaries, a.datas, strip=False, upx=False,
        name="SurveyDesignLab",
    )
