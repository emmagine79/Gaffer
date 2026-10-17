"""Acceptance tests for SPEC-017: the release build.

Run: uv run --project service --frozen pytest mac/tests/test_build.py

Needs the network (npm ci), Xcode command line tools, uv and node. It does not open Gaffer.app.
Every script here runs with a throwaway HOME, so nothing lands in the real ~/Applications, Trash or
signing identity.
Each build is made from a fresh clone of the last COMMIT (plus any uncommitted changes to tracked files),
in a folder with a space in its path, so the test shows the build works from a clean checkout and does not depend on
where it ran. Both builds share one signing identity, kept in a throwaway build home.
"""

from __future__ import annotations

import functools
import hashlib
import os
import plistlib
import re
import struct
import subprocess
import sys
from pathlib import Path

import pytest
from signing_check import BUNDLE_ID, assert_pinned_to_the_gaffer_certificate, requirement

ROOT = Path(__file__).resolve().parents[2]


def sh(*cmd, cwd=None, env=None, check=True):
    return subprocess.run([str(c) for c in cmd], cwd=cwd, env=env, check=check, capture_output=True, text=True)


def clone_head(base: Path, name: str) -> Path:
    # Known limit: `git diff HEAD` does not carry untracked files, so a brand-new file that has not
    # been `git add`ed is missing from the clone. A normal run on a clean checkout has none.
    dest = base / name / "gaffer checkout"
    dest.parent.mkdir(parents=True)
    sha = sh("git", "rev-parse", "HEAD", cwd=ROOT).stdout.strip()
    sh("git", "clone", "--quiet", str(ROOT), str(dest))
    sh("git", "checkout", "--quiet", "--detach", sha, cwd=dest)
    # A committed tree builds exactly as committed. Uncommitted changes to tracked files (a fix being
    # tried, or the revert check putting the old scripts back) are carried over so the build sees them.
    pending = sh("git", "diff", "HEAD", "--binary", cwd=ROOT).stdout
    if pending:
        subprocess.run(["git", "apply", "--whitespace=nowarn"], input=pending, text=True, cwd=dest, check=True)
    else:
        assert sh("git", "status", "--porcelain", cwd=dest).stdout == ""
    return dest


@functools.cache
def real_tool_dirs() -> dict[str, str]:
    """Where uv and npm keep their downloads, so a build under a throwaway HOME does not fetch them again."""
    return {
        "UV_CACHE_DIR": sh("uv", "cache", "dir").stdout.strip(),
        "UV_PYTHON_INSTALL_DIR": sh("uv", "python", "dir").stdout.strip(),
        "npm_config_cache": sh("npm", "config", "get", "cache").stdout.strip(),
    }


def build(checkout: Path, dist: Path, tmp: Path, build_home: Path, home: Path | None = None,
          args: tuple[str, ...] = ("--no-install",), **extra_env):
    """Run scripts/build_app.sh with a throwaway HOME (a sibling of `tmp`) unless `home` is given."""
    home = home or tmp.parent / "home"
    home.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, **real_tool_dirs(), "HOME": str(home), "TMPDIR": str(tmp),
           "GAFFER_BUILD_HOME": str(build_home), **extra_env}
    tmp.mkdir(exist_ok=True)
    return sh(checkout / "scripts" / "build_app.sh", *args, "--dist", dist, cwd=checkout, env=env, check=False)


def python_cdhash(app: Path) -> str:
    out = sh("codesign", "-dvvv", app / "Contents" / "Resources" / "python" / "bin" / "python3.14").stderr
    return re.search(r"^CDHash=(\w+)", out, re.M).group(1)


def tree(app: Path) -> list[str]:
    return sorted(str(p.relative_to(app)) for p in app.rglob("*"))


@pytest.fixture(scope="module")
def builds(tmp_path_factory):
    base = tmp_path_factory.mktemp("build")
    home = base / "build home"  # one identity for both builds, as on a real Mac
    results = []
    for name in ("one", "two"):
        checkout = clone_head(base, name)
        dist = base / name / "out"
        done = build(checkout, dist, base / name / "tmp", home)
        assert done.returncode == 0, done.stderr[-2000:]
        results.append(dist)
    return {"one": results[0], "two": results[1], "home": home, "base": base}


def test_two_builds_of_one_commit_have_the_same_contents_and_the_same_pinned_requirement(builds):
    one, two = builds["one"], builds["two"]
    # Every file in the app before signing: same list, same hashes, same permissions.
    assert (one / "Gaffer-0.1.0.manifest.txt").read_bytes() == (two / "Gaffer-0.1.0.manifest.txt").read_bytes()
    # After signing: the same files in the same places.
    assert tree(one / "Gaffer.app") == tree(two / "Gaffer.app")
    # A signed file inside: its code hash does not include the signing time. (The app's own hash does,
    # because it seals the signatures of everything inside it, so it is not compared.)
    assert python_cdhash(one / "Gaffer.app") == python_cdhash(two / "Gaffer.app")
    # The requirement pins the certificate, and is the same on both builds.
    assert requirement(one / "Gaffer.app") == requirement(two / "Gaffer.app")
    leaf = assert_pinned_to_the_gaffer_certificate(one / "Gaffer.app")
    identities = sh("security", "find-identity", "-p", "codesigning", builds["home"] / "signing.keychain-db").stdout
    assert leaf.upper() in identities


def test_release_zip_unpacks_to_a_valid_app_that_runs_and_ships_its_licences(builds, tmp_path):
    out = builds["one"]
    zip_path = out / "Gaffer-0.1.0-macos-arm64.zip"
    recorded = (out / "Gaffer-0.1.0-macos-arm64.zip.sha256").read_text().split()
    assert recorded == [hashlib.sha256(zip_path.read_bytes()).hexdigest(), zip_path.name]
    sh("ditto", "-x", "-k", zip_path, tmp_path)
    app = tmp_path / "Gaffer.app"
    sh("codesign", "--verify", "--deep", "--strict", app)  # the zip kept links, modes and the seal
    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert info["CFBundleIdentifier"] == BUNDLE_ID
    assert (app / "Contents" / "Resources" / f"{info['CFBundleIconFile']}.icns").stat().st_size > 0
    # The bundled Python runs the service from the locked dependencies (demo mode, no Bluetooth).
    python = app / "Contents" / "Resources" / "python" / "bin" / "python3.14"
    check = sh(python, "-I", "-B", "-m", "gaffer", "--self-test", env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"})
    assert "All good." in check.stdout

    # Python's licence, each package's licence, and NOTICE lists them all.
    resources = app / "Contents" / "Resources"
    notice = (resources / "NOTICE").read_text()
    assert any((resources / "LICENSES" / "Python").rglob("LICENSE.txt"))
    assert "Python 3.14" in notice
    site = next((resources / "python" / "lib").glob("python3.*/site-packages"))
    packages = sorted(site.glob("*.dist-info"))
    assert len(packages) > 20
    for info_dir in packages:
        meta = (info_dir / "METADATA").read_text()
        name = re.search(r"^Name: (.+)$", meta, re.M).group(1)
        version = re.search(r"^Version: (.+)$", meta, re.M).group(1)
        folder = resources / "LICENSES" / f"{name}-{version}"
        assert any(p.is_file() for p in folder.rglob("*")), f"no licence text shipped for {name} {version}"
        assert f"* {name} {version}:" in notice
    assert "segno" in notice  # a dependency added by a later card is picked up from uv.lock


def test_the_release_build_will_not_sign_ad_hoc(tmp_path):
    """No identity, no release: the build stops at the start and writes nothing, rather than signing ad hoc."""
    blocker = tmp_path / "a file, not a folder"
    blocker.write_text("")
    dist = tmp_path / "out"
    done = build(ROOT, dist, tmp_path / "tmp", blocker / "build home")  # the identity can't be made here
    assert done.returncode != 0
    assert "signing identity is not available" in done.stderr
    assert list(dist.iterdir()) == []  # no app, no zip
    assert list((tmp_path / "tmp").iterdir()) == []  # the work folder was cleared away, not left in TMPDIR


def test_ad_hoc_is_a_developer_flag_that_never_makes_a_release_zip_and_never_installs(tmp_path):
    checkout = clone_head(tmp_path, "adhoc")
    dist = tmp_path / "adhoc" / "out"
    home = tmp_path / "adhoc" / "home"
    # No --no-install: the flag alone must keep the ad-hoc app out of ~/Applications, where it would
    # replace the properly signed Gaffer and lose its Bluetooth permission.
    done = build(checkout, dist, tmp_path / "adhoc" / "tmp", tmp_path / "unused home", home=home,
                 args=(), GAFFER_SIGN="adhoc")
    assert done.returncode == 0, done.stderr[-2000:]
    assert not (home / "Applications" / "Gaffer.app").exists()
    assert sorted(p.name for p in dist.iterdir()) == ["Gaffer-0.1.0.manifest.txt", "Gaffer.app"]  # no zip
    assert "Signature=adhoc" in sh("codesign", "-dvvv", dist / "Gaffer.app").stderr
    assert not (tmp_path / "unused home").exists()  # no identity was made either


# --- scripts/sign_app.sh and scripts/bundle_tool.py on their own: quick, no full build ---

def sign_app(tmp_path: Path, *args, **extra_env):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {**os.environ, "HOME": str(home), "GAFFER_BUILD_HOME": str(tmp_path / "build home"), **extra_env}
    return sh(ROOT / "scripts" / "sign_app.sh", *args, env=env, check=False)


def test_a_signing_identity_that_is_half_made_is_never_trashed_or_replaced(tmp_path):
    """A keychain with no password file, or a password file with no keychain, is another build's work in
    progress (or a crash): the build stops and says so. It must not trash the keychain and make a new
    identity, which would change the certificate and bring the Bluetooth prompt back."""
    first = sign_app(tmp_path, "--ensure-identity")
    assert first.returncode == 0, first.stderr
    build_home = tmp_path / "build home"
    keychain, passfile = build_home / "signing.keychain-db", build_home / "signing.keychain.pass"
    keychain_bytes, password = keychain.read_bytes(), passfile.read_text()

    # Another build is part-way through: the password file is there, the keychain is not yet.
    parked = tmp_path / "parked"
    parked.mkdir()
    keychain.rename(parked / keychain.name)
    mid_setup = sign_app(tmp_path, "--ensure-identity")
    assert mid_setup.returncode != 0 and "Nothing was trashed" in mid_setup.stderr
    assert not keychain.exists() and passfile.read_text() == password
    (parked / keychain.name).rename(keychain)

    # The password file has gone: the identity is kept as it is.
    passfile.rename(parked / passfile.name)
    lost = sign_app(tmp_path, "--ensure-identity")
    assert lost.returncode != 0 and "Nothing was changed" in lost.stderr
    assert keychain.read_bytes() == keychain_bytes
    assert not (tmp_path / "home" / ".Trash").exists()  # nothing was moved to the Trash

    # Put the password file back and the same identity signs again.
    (parked / passfile.name).rename(passfile)
    again = sign_app(tmp_path, "--ensure-identity")
    assert again.returncode == 0, again.stderr
    assert keychain.read_bytes() == keychain_bytes


def test_an_existing_keychain_without_the_identity_is_never_trashed_or_replaced(tmp_path):
    """A keychain that can't give up the identity (for instance it came back locked, or lost the key) must
    stop the build, not be replaced: a new certificate brings the Bluetooth prompt back."""
    assert sign_app(tmp_path, "--ensure-identity").returncode == 0
    build_home = tmp_path / "build home"
    keychain, passfile = build_home / "signing.keychain-db", build_home / "signing.keychain.pass"
    parked = tmp_path / "parked"
    parked.mkdir()
    keychain.rename(parked / "real.keychain-db")
    sh("security", "create-keychain", "-p", passfile.read_text(), keychain)  # unlocks with the password, holds no identity
    empty_bytes = keychain.read_bytes()

    done = sign_app(tmp_path, "--ensure-identity")
    assert done.returncode != 0 and "Nothing was changed" in done.stderr
    assert keychain.read_bytes() == empty_bytes
    assert passfile.exists()
    assert not (tmp_path / "home" / ".Trash").exists()


def test_a_build_that_fails_after_claiming_the_password_file_gives_it_back(tmp_path):
    """The password file is written before the keychain is put in place. If the keychain can't be put in
    place (here something that is not a file is in the way), the claim is undone, so the next build is not stuck."""
    build_home = tmp_path / "build home"
    build_home.mkdir()
    os.mkfifo(build_home / "signing.keychain-db")  # exists, but is not a keychain file, and mv -n will not replace it
    done = sign_app(tmp_path, "--ensure-identity")
    assert done.returncode != 0
    assert not (build_home / "signing.keychain.pass").exists()

    (build_home / "signing.keychain-db").rename(tmp_path / "removed")
    assert sign_app(tmp_path, "--ensure-identity").returncode == 0  # nothing was left in the way


def test_a_file_that_will_not_sign_is_named_in_the_error(tmp_path):
    """A Mach-O file whose load commands are broken makes codesign fail; the build stops and names the file."""
    app = tmp_path / "Gaffer.app"
    resources = app / "Contents" / "Resources"
    resources.mkdir(parents=True)
    # mach_header_64 for an arm64 dylib with one load command whose size is 0.
    header = struct.pack("<IiiIIIII", 0xFEEDFACF, 0x0100000C, 0, 6, 1, 8, 0, 0)
    (resources / "broken.dylib").write_bytes(header + struct.pack("<II", 0x19, 0) + b"\0" * 64)
    done = sign_app(tmp_path, app, GAFFER_SIGN="adhoc")
    assert done.returncode != 0
    assert "broken.dylib" in done.stderr  # codesign's own wording is not checked: it changes with macOS


def licences_run(tmp_path: Path, package_files: dict[str, str], metadata_extra: str = ""):
    """Run `bundle_tool.py licences` on a fake Python tree holding one package, with the given files in its dist-info."""
    python_dir = tmp_path / "python"
    lib = python_dir / "lib" / "python3.14"
    (lib / "site-packages" / "toy-1.0.dist-info").mkdir(parents=True)
    (lib / "LICENSE.txt").write_text("Python licence text\n")
    info = lib / "site-packages" / "toy-1.0.dist-info"
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: toy\nVersion: 1.0\n{metadata_extra}")
    for name, text in package_files.items():
        (info / name).write_text(text)
    resources = tmp_path / "resources"
    resources.mkdir()
    (resources / "NOTICE").write_text("Gaffer notice\n")
    done = sh(sys.executable, "-I", ROOT / "scripts" / "bundle_tool.py", "licences", resources, python_dir, tmp_path / "repo",
              check=False)
    return done, resources


def test_an_authors_or_notice_file_is_not_a_licence(tmp_path):
    done, resources = licences_run(tmp_path, {"AUTHORS.md": "Somebody\n", "NOTICE": "Credits\n"})
    assert done.returncode != 0 and "toy 1.0 has no licence file" in done.stderr


def test_a_licence_text_ships_with_its_notice_and_authors_files(tmp_path):
    done, resources = licences_run(tmp_path, {"LICENSE": "MIT text\n", "AUTHORS.md": "Somebody\n"})
    assert done.returncode == 0, done.stderr
    shipped = sorted(p.name for p in (resources / "LICENSES" / "toy-1.0").iterdir())
    assert shipped == ["AUTHORS.md", "LICENSE"]
    assert "* toy 1.0:" in (resources / "NOTICE").read_text()


def test_a_licence_file_named_in_the_metadata_counts(tmp_path):
    done, resources = licences_run(tmp_path, {"COPYRIGHT.txt": "Terms\n"}, metadata_extra="License-File: COPYRIGHT.txt\n")
    assert done.returncode == 0, done.stderr
    assert (resources / "LICENSES" / "toy-1.0" / "COPYRIGHT.txt").is_file()
