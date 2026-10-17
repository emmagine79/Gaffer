#!/bin/bash
# Build Gaffer.app: the Swift shell plus a private Python 3.14 that runs the light service.
#
#   scripts/build_app.sh            build dist/Gaffer.app and install it to ~/Applications/Gaffer.app
#   scripts/build_app.sh --no-install   build dist/Gaffer.app only
#
# Needs: Xcode command line tools (swiftc, codesign, iconutil) and uv.
# The interpreter is python-build-standalone, installed and found by uv, so the app
# never uses a system or Homebrew Python.
#
# Old builds are moved to the Trash, never deleted.
set -euo pipefail

PY_VERSION="3.14.7"   # Captain, 17 Oct 2026: bundle Python 3.14 (lumen-studio needs it)
BUNDLE_ID="work.awelahlayray.gaffer"
MIN_MACOS="14.0"      # matches LSMinimumSystemVersion in mac/Info.plist

INSTALL=1
[[ "${1:-}" == "--no-install" ]] && INSTALL=0

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
DIST="$ROOT/dist"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/gaffer-build.XXXXXX")"
APP="$WORK/Gaffer.app"
C="$APP/Contents"
PYDIR="$C/Resources/python"

say() { printf '==> %s\n' "$*"; }

to_trash() {  # move a path to the Trash with a unique name
    local path="$1"
    [[ -e "$path" ]] || return 0
    mkdir -p "$HOME/.Trash"
    mv "$path" "$HOME/.Trash/$(basename "$path" .app)-$(date +%Y%m%d-%H%M%S)-$$.app"
}

command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/" >&2; exit 1; }
command -v swiftc >/dev/null || { echo "swiftc is needed: xcode-select --install" >&2; exit 1; }

mkdir -p "$C/MacOS" "$C/Resources"

say "Python $PY_VERSION (python-build-standalone via uv)"
PY_SRC_BIN="$(uv python find --managed-python "$PY_VERSION" 2>/dev/null)" || {
    uv python install "$PY_VERSION"
    PY_SRC_BIN="$(uv python find --managed-python "$PY_VERSION")"
}
PY_SRC="$(cd "$(dirname "$PY_SRC_BIN")/.." && pwd -P)"
ditto "$PY_SRC" "$PYDIR"
BUNDLED_PY="$PYDIR/bin/python3.14"

say "Light service and its locked dependencies"
REQS="$WORK/requirements.txt"
uv export --project "$ROOT/service" --frozen --no-dev --no-emit-project --quiet -o "$REQS"
# --break-system-packages: the bundled copy carries python-build-standalone's
# EXTERNALLY-MANAGED marker; this installs into that private copy only.
uv pip install --quiet --python "$BUNDLED_PY" --break-system-packages --require-hashes -r "$REQS"
uv pip install --quiet --python "$BUNDLED_PY" --break-system-packages --no-deps "$ROOT/service"
# Compile once now; the app runs Python with -B so it never writes into the signed bundle.
"$BUNDLED_PY" -I -m compileall -q -j 0 "$PYDIR/lib/python3.14/site-packages" >/dev/null

say "Swift shell"
swiftc -O -swift-version 5 -target "arm64-apple-macos$MIN_MACOS" \
    -framework AppKit -framework WebKit \
    "$ROOT"/mac/Sources/*.swift -o "$C/MacOS/Gaffer"
cp "$ROOT/mac/Info.plist" "$C/Info.plist"
plutil -lint -s "$C/Info.plist"

say "Icon"
swiftc -O -target "arm64-apple-macos$MIN_MACOS" "$ROOT/mac/Icon/make_icon.swift" -o "$WORK/make_icon"
"$WORK/make_icon" "$WORK/icon-1024.png"
ICONSET="$WORK/Gaffer.iconset"
mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
    sips -z "$s" "$s" "$WORK/icon-1024.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
    d=$((s * 2))
    sips -z "$d" "$d" "$WORK/icon-1024.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$C/Resources/Gaffer.icns"

say "Ad-hoc code signing, inside out"
# Every Mach-O file in the bundled Python is signed first, then the app itself.
# No hardened runtime: an ad-hoc signature has no team id, so library validation
# would refuse Python's own extension modules.
while IFS= read -r -d '' f; do
    if file -b "$f" | grep -q 'Mach-O'; then
        codesign --force --sign - "$f" 2>/dev/null
    fi
done < <(find "$PYDIR" -type f \( -name '*.so' -o -name '*.dylib' -o -perm -u+x \) -print0)
codesign --force --sign - --identifier "$BUNDLE_ID" "$APP"
codesign --verify --deep --strict "$APP"

say "dist/Gaffer.app"
mkdir -p "$DIST"
to_trash "$DIST/Gaffer.app"
mv "$APP" "$DIST/Gaffer.app"

if [[ "$INSTALL" == 1 ]]; then
    say "~/Applications/Gaffer.app"
    mkdir -p "$HOME/Applications"
    to_trash "$HOME/Applications/Gaffer.app"
    ditto "$DIST/Gaffer.app" "$HOME/Applications/Gaffer.app"
    codesign --verify --deep --strict "$HOME/Applications/Gaffer.app"
fi
say "Done. Double-click Gaffer.app to open it."
