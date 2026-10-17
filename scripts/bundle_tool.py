"""Helpers for scripts/build_app.sh. Run with the bundled Python: python3.14 -I bundle_tool.py <command> ...

  prune     <python-dir> <discard-dir>              make the installed packages identical on every build
  licences  <resources-dir> <python-dir> <repo-dir> ship every bundled package's licence and list them in NOTICE
  manifest  <app-dir>                               print one line per file: type, mode, sha256, path

Standard library only. Nothing is deleted: files taken out go to <discard-dir>.
"""

from __future__ import annotations

import csv
import hashlib
import os
import platform
import shutil
import sys
from email.parser import Parser
from pathlib import Path

#: Files uv writes into a package it installs from a folder: the folder's path on this Mac and
#: the install time. They differ on every build and nothing reads them.
BUILD_ONLY_FILES = ("direct_url.json", "uv_cache.json", "uv_build.json")

#: A file with one of these name starts is a licence text.
LICENCE_TEXT_NAMES = ("licen", "copying")
#: These travel with the licence text when a package has one, but are never a licence on their
#: own: an AUTHORS file says who wrote the code, not what you may do with it.
LICENCE_EXTRA_NAMES = ("notice", "authors")

#: Packages whose wheels carry no licence file, and where the licence text is instead.
#: pyobjc-core and pyobjc-framework-libdispatch are built from the same project (pyobjc) as
#: pyobjc-framework-Cocoa, whose wheel carries that project's licence.
#: godox-mesh-bt and gaffer-service are in this repo. A package not named here with no
#: licence file stops the build: a person has to decide where its licence text comes from.
BORROWED = {
    "pyobjc_core": "pyobjc_framework_cocoa",
    "pyobjc_framework_libdispatch": "pyobjc_framework_cocoa",
}
IN_REPO = {
    "godox_mesh_bt": "service/packages/godox-mesh-bt/LICENSE",
    "gaffer_service": "LICENSE",
}


def site_packages(python_dir: Path) -> Path:
    found = sorted((python_dir / "lib").glob("python3.*/site-packages"))
    if len(found) != 1:
        sys.exit(f"bundle_tool: expected one site-packages folder in {python_dir}, found {len(found)}")
    return found[0]


def move_away(path: Path, discard: Path) -> None:
    discard.mkdir(parents=True, exist_ok=True)
    target = discard / f"{len(list(discard.iterdir()))}-{path.name}"
    shutil.move(str(path), str(target))


def prune(python_dir: Path, discard: Path) -> None:
    site = site_packages(python_dir)
    for info in sorted(site.glob("*.dist-info")):
        record = info / "RECORD"
        gone: set[str] = set()
        # Console scripts (bin/uvicorn and so on) start with the absolute path of the build
        # folder and are never used by the app, which runs `python -m gaffer`.
        if record.exists():
            for row in csv.reader(record.read_text().splitlines()):
                if row and row[0].startswith("../../../bin/"):
                    script = (site / row[0]).resolve()
                    if script.is_file() and not script.is_symlink():
                        move_away(script, discard)
                        gone.add(row[0])
        for name in BUILD_ONLY_FILES:
            if (info / name).exists():
                move_away(info / name, discard)
                gone.add(f"{info.name}/{name}")
        if gone and record.exists():
            kept = [r for r in csv.reader(record.read_text().splitlines()) if r and r[0] not in gone]
            with record.open("w", newline="") as out:
                csv.writer(out, lineterminator="\n").writerows(kept)
    # The standalone Python ships .pyc files compiled when it was built; the build recompiles
    # everything the same way, so start from none.
    for cache in sorted(python_dir.rglob("__pycache__")):
        if cache.is_dir():
            move_away(cache, discard)


def declared_licence_files(info: Path) -> set[str]:
    """File names the package's METADATA lists as its licence texts (License-File fields)."""
    meta = Parser().parsestr((info / "METADATA").read_text(errors="replace"))
    return {Path(value.strip()).name for value in meta.get_all("License-File") or []}


def licence_files(folder: Path, declared: set[str] = frozenset(), skip: str = "") -> list[Path]:
    """The files to ship for a package or for Python: its licence texts and their NOTICE or AUTHORS.

    Returns nothing unless at least one file is a licence text (named LICENSE, LICENCE or COPYING,
    or listed in the package's License-File metadata). NOTICE and AUTHORS files alone don't count.
    A path part named `skip` leaves the file out.
    """
    everything = sorted(p for p in folder.rglob("*") if p.is_file() and skip not in p.parts)
    texts = [p for p in everything if p.name.lower().startswith(LICENCE_TEXT_NAMES) or p.name in declared]
    if not texts:
        return []
    extras = [p for p in everything if p.name.lower().startswith(LICENCE_EXTRA_NAMES)]
    return sorted(set(texts) | set(extras))


def declared_licence(info: Path) -> str:
    meta = Parser().parsestr((info / "METADATA").read_text(errors="replace"))
    for field in ("License-Expression", "License"):
        value = (meta.get(field) or "").strip()
        if value:
            return value.splitlines()[0]
    for classifier in meta.get_all("Classifier") or []:
        if classifier.startswith("License ::"):
            return classifier.split("::")[-1].strip()
    return "not declared"


def licences(resources: Path, python_dir: Path, repo: Path) -> None:
    site = site_packages(python_dir)
    out = resources / "LICENSES"
    out.mkdir(exist_ok=True)
    lines = [
        "",
        "PYTHON AND THE PYTHON PACKAGES INSIDE THIS APP",
        "----------------------------------------------",
        "",
        "Gaffer.app carries its own Python and these packages. Each licence text is in",
        "Contents/Resources/LICENSES/<name>/, in the folder named below.",
        "",
    ]
    version = platform.python_version()  # this script runs under the bundled interpreter
    py_files = licence_files(python_dir / "lib", skip="site-packages")
    if not py_files:
        sys.exit("bundle_tool: Python's licence file is missing")
    for f in py_files:
        # Python's own LICENSE.txt, and any licence that comes with Tcl/Tk.
        rel = f.relative_to(python_dir / "lib")
        target = out / "Python" / rel.parent.as_posix().replace("/", "_") / f.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
    lines += [
        f"* Python {version} (python-build-standalone, found by uv): Python Software Foundation Licence",
        "  https://www.python.org/  https://github.com/astral-sh/python-build-standalone",
        "  LICENSES/Python/",
        "  This Python build links native libraries (for example OpenSSL, SQLite, libffi and zlib)",
        "  whose licence texts the uv copy of Python does not include.",
        "",
    ]
    for info in sorted(site.glob("*.dist-info")):
        meta = Parser().parsestr((info / "METADATA").read_text(errors="replace"))
        name, ver = meta["Name"], meta["Version"]
        key = name.lower().replace("-", "_").replace(".", "_")
        files = licence_files(info, declared_licence_files(info))
        source = f"{info.name}"
        if not files and key in BORROWED:
            donor = next(site.glob(f"{BORROWED[key]}-*.dist-info"))
            files, source = licence_files(donor, declared_licence_files(donor)), f"{donor.name} (same project)"
        if not files and key in IN_REPO:
            files, source = [repo / IN_REPO[key]], "this repository"
        if not files:
            sys.exit(f"bundle_tool: {name} {ver} has no licence file and no rule says where its licence is")
        folder = out / f"{name}-{ver}"
        folder.mkdir(exist_ok=True)
        for f in files:
            rel = f.relative_to(info) if info in f.parents else Path(f.name)
            target = folder / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
        lines.append(f"* {name} {ver}: {declared_licence(info)}")
        lines.append(f"  LICENSES/{name}-{ver}/  (text from {source})")
    notice = resources / "NOTICE"
    notice.write_text(notice.read_text().rstrip("\n") + "\n" + "\n".join(lines) + "\n")


def manifest(app: Path) -> None:
    """One sorted line per entry: kind, mode (executable or not), sha256 or link target, path."""
    for dirpath, dirnames, filenames in os.walk(app):
        dirnames.sort()
        base = Path(dirpath)
        for name in sorted(dirnames + filenames):
            path = base / name
            rel = path.relative_to(app).as_posix()
            if path.is_symlink():
                print(f"link\t-\t{os.readlink(path)}\t{rel}")
            elif path.is_dir():
                print(f"dir\t-\t-\t{rel}")
            else:
                mode = "x" if path.stat().st_mode & 0o100 else "-"
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                print(f"file\t{mode}\t{digest}\t{rel}")


def main() -> None:
    cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    if cmd == "prune" and len(args) == 2:
        prune(Path(args[0]), Path(args[1]))
    elif cmd == "licences" and len(args) == 3:
        licences(Path(args[0]), Path(args[1]), Path(args[2]))
    elif cmd == "manifest" and len(args) == 1:
        manifest(Path(args[0]))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
