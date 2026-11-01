"""Collect license texts from the exact, SHA-256-verified Qt source releases.

Download the two source archives from their official download.qt.io URLs,
then run: python desktop/collect_qt_notices.py --source-dir PATH_TO_ARCHIVES
Source archives remain outside the repository and release artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path, PurePosixPath
import posixpath
import tarfile

CODE = Path(__file__).resolve().parent.parent
CACHE = CODE.parent / "DesktopBuild_20261101"
OUTPUT = CODE / "desktop" / "third_party_notices" / "Qt"
SOURCES = {
    "qtwebengine": "df4e19ba2b3a540551b6f998d62597377ffa688c1cff564589b7da2e2bf87337",
    "qtbase": "56001b905601bb9023d399f3ba780d7fa940f3e4861e496a7c490331f49e0b80",
}
METADATA = {"readme.chromium", "readme.crashpad", "readme.v8", "readme.pdfium", "readme.angle", "qt_attribution.json", "additional_readme_paths.json"}


def write_index(destination: Path, metadata: dict) -> None:
    rows = "\n".join(
        f'<li><a href="{html.escape(item["stored_path"], quote=True)}">{html.escape(item["path"])}</a></li>'
        for item in metadata["files"]
    )
    title = f'Qt {metadata["module"]} 6.8.3 license and attribution texts'
    markup = (
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        f'<title>{html.escape(title)}</title>'
        '<style>body{max-width:1100px;margin:40px auto;padding:0 20px;font:15px/1.5 system-ui,sans-serif;color:#192c3c}li{margin:5px 0;overflow-wrap:anywhere}a{color:#277d91}code{overflow-wrap:anywhere}</style>'
        f'<h1>{html.escape(title)}</h1>'
        f'<p>{html.escape(metadata["description"])}</p>'
        f'<p>Source archive: <a href="{html.escape(metadata["source_url"], quote=True)}">{html.escape(metadata["source_url"])}</a><br>'
        f'Verified SHA-256: <code>{metadata["source_sha256"]}</code></p>'
        '<p><a href="provenance.json">Provenance and file checksums</a></p>'
        f'<p>{len(metadata["files"])} files, listed by original source path.</p><ul>{rows}</ul></html>'
    )
    (destination / "index.html").write_text(markup, encoding="utf-8")


def collect(module: str) -> None:
    filename = f"{module}-everywhere-src-6.8.3.tar.xz"
    archive = CACHE / filename
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    actual = digest.hexdigest()
    if actual != SOURCES[module]:
        raise RuntimeError(f"SHA-256 mismatch for {filename}: {actual}")
    print(f"Verified {filename}", flush=True)
    destination = OUTPUT / ("QtWebEngine-6.8.3-licenses" if module == "qtwebengine" else "QtBase-6.8.3-licenses")
    destination.mkdir(parents=True, exist_ok=True)
    references: set[str] = set()
    extracted: dict[str, dict] = {}

    def save(name: str, data: bytes) -> None:
        if name in extracted:
            return
        parts = PurePosixPath(name).parts
        if not parts or ".." in parts or PurePosixPath(name).is_absolute():
            raise RuntimeError(f"Unsafe archive path: {name}")
        suffix = PurePosixPath(name).suffix.lower()
        if suffix not in {".json", ".txt", ".html", ".md", ".rst"}:
            suffix = ".txt"
        stored_path = f"files/{len(extracted) + 1:05d}{suffix}"
        target = destination / stored_path
        if not target.resolve().is_relative_to(destination.resolve()):
            raise RuntimeError(f"Unsafe output path: {name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        extracted[name] = {"path": name, "stored_path": stored_path, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    def add_reference(parent: str, name: str) -> None:
        # // means relative to the Chromium source root in README metadata.
        if name.startswith("//"):
            marker = "/src/3rdparty/chromium/"
            if marker not in parent:
                return
            normalized = parent.split(marker)[0] + marker + name[2:]
        else:
            normalized = posixpath.normpath(posixpath.join(parent, name))
        if ".." not in PurePosixPath(normalized).parts:
            references.add(normalized)

    with tarfile.open(archive, "r|xz") as bundle:
        for member in bundle:
            if not member.isfile():
                continue
            name = PurePosixPath(member.name).name
            lowered = name.lower()
            is_legal = (
                any(term in lowered for term in ("license", "licence", "copying", "copyright", "notice", "patents"))
                or any(part.lower() in {"licenses", "licences"} for part in PurePosixPath(member.name).parts)
                or lowered in {"ftl.txt", "bdflicense.txt"}
            )
            if not (is_legal or lowered in METADATA):
                continue
            source = bundle.extractfile(member)
            if source is None:
                continue
            data = source.read()
            save(member.name, data)
            parent = posixpath.dirname(member.name)
            if lowered == "qt_attribution.json":
                try:
                    records = json.loads(data)
                    if isinstance(records, dict):
                        records = [records]
                    for record in records:
                        for key in ("LicenseFile", "CopyrightFile"):
                            value = record.get(key, [])
                            for reference in ([value] if isinstance(value, str) else value):
                                add_reference(parent, reference)
                except (ValueError, AttributeError, TypeError):
                    pass
            elif lowered in METADATA:
                for line in data.decode("utf-8", errors="replace").splitlines():
                    if line.startswith("License File:"):
                        for reference in line.partition(":")[2].strip().split(","):
                            reference = reference.strip()
                            if reference and reference != "NOT_SHIPPED":
                                add_reference(parent, reference)

    missing = references - extracted.keys()
    if missing:
        print(f"Checking {len(missing)} metadata-referenced license paths", flush=True)
        with tarfile.open(archive, "r|xz") as bundle:
            for member in bundle:
                if member.isfile() and member.name in missing:
                    source = bundle.extractfile(member)
                    if source is not None:
                        save(member.name, source.read())

    metadata = {
        "module": module,
        "version": "6.8.3",
        "source_url": "https://download.qt.io/archive/qt/6.8/6.8.3/submodules/" + filename,
        "sha256_reference_url": "https://download.qt.io/archive/qt/6.8/6.8.3/submodules/" + filename + ".mirrorlist",
        "source_sha256": actual,
        "license_and_metadata_file_count": len(extracted),
        "total_bytes": sum(item["bytes"] for item in extracted.values()),
        "description": "License and copyright texts plus attribution metadata collected from the exact Qt 6.8.3 source archive. This inclusive source collection also contains build, test, example, and platform-specific components; it is not a claim that every listed component is linked into the Windows application.",
        "files": sorted(extracted.values(), key=lambda item: item["path"]),
        "metadata_references_not_found_in_source_archive": sorted(references - extracted.keys()),
    }
    (destination / "provenance.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (destination / "README.txt").write_text(
        f'Official {module} 6.8.3 source license collection\n\n'
        'License and attribution text files are in files/. They have short numbered names for Windows portability.\n'
        'provenance.json maps each file to its original source-archive path and records all file SHA-256 hashes.\n'
        f'Source: {metadata["source_url"]}\n'
        f'Source SHA-256 (verified): {actual}\n\n'
        + metadata['description'] + '\n', encoding="utf-8")
    write_index(destination, metadata)
    print(json.dumps({"module": module, "files": len(extracted), "bytes": sum(item["bytes"] for item in extracted.values()), "unresolved_references": len(metadata["metadata_references_not_found_in_source_archive"]), "output": str(destination)}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("modules", nargs="*", metavar="MODULE", help="qtwebengine and/or qtbase (default: both)")
    parser.add_argument("--source-dir", type=Path, default=CACHE, help="Directory containing the exact Qt 6.8.3 source archives")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT, help="Destination for collected license texts")
    args = parser.parse_args()
    for requested in args.modules:
        if requested not in SOURCES:
            parser.error(f"Unknown module: {requested}")
    CACHE = args.source_dir.resolve()
    OUTPUT = args.output_dir.resolve()
    for requested in args.modules or SOURCES:
        collect(requested)
