"""What a release-signed Gaffer.app must look like. Shared by test_build.py and test_app.py.

The app is signed with the fixed "Gaffer Local Signing" certificate (scripts/sign_app.sh), so its
designated requirement names that certificate's hash. macOS keeps the Bluetooth permission against
that requirement. An ad-hoc signature would have a requirement that changes on every build.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

BUNDLE_ID = "work.awelahlayray.gaffer"
LEAF_REQUIREMENT = re.compile(
    rf'designated => identifier "{re.escape(BUNDLE_ID)}" and certificate leaf = H"([0-9a-f]{{40}})"')


def requirement(app: Path) -> str:
    """The app's designated requirement line, as codesign prints it."""
    out = subprocess.run(["codesign", "-d", "-r-", str(app)], capture_output=True, text=True, check=True).stdout
    return next(line for line in out.splitlines() if line.startswith("designated =>"))


def assert_pinned_to_the_gaffer_certificate(app: Path) -> str:
    """Fail unless `app` is signed by the fixed certificate; returns the certificate hash it pins."""
    req = requirement(app)
    leaf = LEAF_REQUIREMENT.fullmatch(req)
    assert leaf, f"requirement does not pin the certificate: {req}"
    details = subprocess.run(["codesign", "-dvvv", str(app)], capture_output=True, text=True, check=True).stderr
    assert "Signature=adhoc" not in details, "the app is signed ad hoc"
    assert "Authority=Gaffer Local Signing" in details
    assert f"Identifier={BUNDLE_ID}" in details
    return leaf.group(1)
