"""Create a source archive and checksums without runtimes or local credentials."""

import argparse
import hashlib
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {"dist", "build", "__pycache__", ".venv", "node_modules", ".git",
            ".pytest_cache", ".devtools"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    output = parser.parse_args().output.resolve()
    if ROOT == output or ROOT in output.parents or output.suffix.lower() != ".zip":
        parser.error("Write the ZIP outside code/.")
    files = []
    for file in sorted(ROOT.rglob("*")):
        rel = file.relative_to(ROOT)
        if (not file.is_file() or any(part in EXCLUDED for part in rel.parts)
                or file.suffix.lower() in {".pyc", ".pyo", ".lic", ".zip"}
                or file.name in {".env", "MANIFEST.sha256"}
                or rel.as_posix().startswith("results/local_")):
            continue
        files.append(file)
    manifest = ROOT / "MANIFEST.sha256"
    manifest.write_text("".join(
        hashlib.sha256(file.read_bytes()).hexdigest() + "  " + file.relative_to(ROOT).as_posix() + "\n"
        for file in files), encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in files + [manifest]:
            archive.write(file, Path("code") / file.relative_to(ROOT))
    print(f"{output}: {len(files) + 1} files; {output.stat().st_size} bytes")


if __name__ == "__main__":
    main()
