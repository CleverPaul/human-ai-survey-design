"""Run a frozen release from a clean working directory and reduced environment."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    executable, report = args.executable.resolve(), args.report.resolve()
    if not executable.is_file():
        parser.error("Executable does not exist.")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.unlink(missing_ok=True)
    env = os.environ.copy()
    for key in list(env):
        if key.upper().startswith(("PYTHON", "CONDA", "GUROBI", "SURVEY_", "QT_", "QML_", "QTWEBENGINE")):
            env.pop(key)
    windows = Path(env.get("SystemRoot", r"C:\Windows"))
    env["PATH"] = os.pathsep.join(map(str, [windows / "System32", windows]))
    command = [str(executable), "--self-test", str(report)]
    if args.screenshot:
        command += ["--screenshot", str(args.screenshot.resolve())]
    with tempfile.TemporaryDirectory(prefix="SurveyDesignVerification_") as directory:
        completed = subprocess.run(command, cwd=directory, env=env, timeout=160)
    if not report.exists():
        raise SystemExit(f"No self-test report; process exited {completed.returncode}.")
    result = json.loads(report.read_text(encoding="utf-8"))
    if completed.returncode or not result.get("ok") or not result.get("frozen"):
        raise SystemExit(f"Frozen release failed: {result.get('error')} (exit {completed.returncode}).")
    result["launch_check"] = {
        "clean_temporary_working_directory": True,
        "path_contains_only_windows_system_directories": True,
        "python_conda_gurobi_qt_environment_removed": True,
        "separate_clean_windows_machine_tested": False,
        "process_exit_code": completed.returncode,
    }
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    initial = result["initial"]["result"]
    print(json.dumps({"ok": True, "solver": initial["solver"],
                      "objective": initial["objective"], "gap": initial["gap"],
                      "report": str(report)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
