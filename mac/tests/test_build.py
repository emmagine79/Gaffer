"""Acceptance tests for SPEC-017: the release build.

Run: uv run --project service --frozen pytest mac/tests/test_build.py

Needs the network (npm ci), Xcode command line tools, uv and node. It does not open Gaffer.app.
Each build is made from a fresh clone of the last COMMIT (not the working tree), in a folder with a
space in its path, so the test shows the build works from a clean checkout and does not depend on
where it ran. Both builds share one signing identity, kept in a throwaway build home.
"""

from __future__ import annotations

import hashlib
import os
import plistlib
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BUNDLE_ID = "work.awelahlayray.gaffer"
LEAF_REQUIREMENT = re.compile(
    rf'designated => identifier "{re.escape(BUNDLE_ID)}" and certificate leaf = H"([0-9a-f]{{40}})"')


def sh(*cmd, cwd=None, env=None, check=True):
    return subprocess.run([str(c) for c in cmd], cwd=cwd, env=env, check=check, capture_output=True, text=True)


def clone_head(base: Path, name: str) -> Path:
    dest = base / name / "gaffer checkout"
    dest.parent.mkdir(parents=True)
    sha = sh("git", "rev-parse", "HEAD", cwd=ROOT).stdout.strip()
    sh("git", "clone", "--quiet", str(ROOT), str(dest))
    sh("git", "checkout", "--quiet", "--detach", sha, cwd=dest)
    assert sh("git", "status", "--porcelain", cwd=dest).stdout == ""
    return dest


def build(checkout: Path, dist: Path, tmp: Path, home: Path, **extra_env):
    env = {**os.environ, "TMPDIR": str(tmp), "GAFFER_BUILD_HOME": str(home), **extra_env}
    tmp.mkdir(exist_ok=True)
    return sh(checkout / "scripts" / "build_app.sh", "--no-install", "--dist", dist, cwd=checkout, env=env, check=False)


def requirement(app: Path) -> str:
    out = sh("codesign", "-d", "-r-", app).stderr  # also prints the app's path, which differs
    return next(line for line in out.splitlines() if line.startswith("designated =>"))


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
    req = requirement(one / "Gaffer.app")
    assert req == requirement(two / "Gaffer.app")
    leaf = LEAF_REQUIREMENT.fullmatch(req)
    assert leaf, f"requirement does not pin the certificate: {req}"
    identities = sh("security", "find-identity", "-p", "codesigning", builds["home"] / "signing.keychain-db").stdout
    assert leaf.group(1).upper() in identities
    assert "Authority=Gaffer Local Signing" in sh("codesign", "-dvvv", one / "Gaffer.app").stderr


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


def test_ad_hoc_is_a_developer_flag_that_never_makes_a_release_zip(tmp_path):
    checkout = clone_head(tmp_path, "adhoc")
    dist = tmp_path / "adhoc" / "out"
    done = build(checkout, dist, tmp_path / "adhoc" / "tmp", tmp_path / "unused home", GAFFER_SIGN="adhoc")
    assert done.returncode == 0, done.stderr[-2000:]
    assert sorted(p.name for p in dist.iterdir()) == ["Gaffer-0.1.0.manifest.txt", "Gaffer.app"]  # no zip
    assert "Signature=adhoc" in sh("codesign", "-dvvv", dist / "Gaffer.app").stderr
    assert not (tmp_path / "unused home").exists()  # no identity was made either
