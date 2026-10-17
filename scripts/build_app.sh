#!/bin/bash
# Build Gaffer.app: the Swift shell plus a private Python 3.14 that runs the light service.
# Also writes the release zip for a GitHub Release.
#
#   scripts/build_app.sh                    build dist/Gaffer.app and its zip, install to ~/Applications/Gaffer.app
#   scripts/build_app.sh --no-install       build dist/ only
#   scripts/build_app.sh --dist DIR         write the results to DIR instead of dist/
#
# Output (in dist/):
#   Gaffer.app
#   Gaffer-<version>-macos-arm64.zip          what goes on the GitHub Release
#   Gaffer-<version>-macos-arm64.zip.sha256
#   Gaffer-<version>.manifest.txt             every file in the app before signing, with its sha256
#
# Needs: Xcode command line tools (swiftc, codesign, iconutil), uv, and node with npm (builds web/).
# The interpreter is python-build-standalone, installed and found by uv, so the app
# never uses a system or Homebrew Python.
#
# Reproducible: two builds of the same commit give the same app contents (same manifest) and the
# same designated requirement. What differs is only each signature's signing time (the CMS
# signature signs the clock), so the zip's bytes differ, but not what is in the app.
# Every file's date is the commit's date (SOURCE_DATE_EPOCH), so dates match too.
#
# The app is signed with the fixed identity (sign_app.sh). If that is missing or broken the
# build fails at the start. GAFFER_SIGN=adhoc is a developer flag for a quick local build; it
# makes no release zip.
#
# Old builds are moved to the Trash, never deleted.
set -euo pipefail

PY_VERSION="3.14.7"   # Captain, 17 Oct 2026: bundle Python 3.14 (lumen-studio needs it)
MIN_MACOS="14.0"      # matches LSMinimumSystemVersion in mac/Info.plist

INSTALL=1
DIST=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-install) INSTALL=0 ;;
        --dist) DIST="${2:?--dist needs a folder}"; shift ;;
        *) echo "build_app: unknown option $1" >&2; exit 2 ;;
    esac
    shift
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
DIST="${DIST:-$ROOT/dist}"
mkdir -p "$DIST"
DIST="$(cd "$DIST" && pwd -P)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/gaffer-build.XXXXXX")"
APP="$WORK/Gaffer.app"
C="$APP/Contents"
PYDIR="$C/Resources/python"
DISCARD="$WORK/discard"

say() { printf '==> %s\n' "$*"; }

to_trash() {  # move a path to the Trash with a unique name
    local path="$1"
    [[ -e "$path" ]] || return 0
    mkdir -p "$HOME/.Trash"
    mv "$path" "$HOME/.Trash/$(basename "$path")-$(date +%Y%m%d-%H%M%S)-$$"
}

command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/" >&2; exit 1; }
command -v npm >/dev/null || { echo "node and npm are needed to build web/: https://nodejs.org/" >&2; exit 1; }
command -v swiftc >/dev/null || { echo "swiftc is needed: xcode-select --install" >&2; exit 1; }
# Fail now, not after the build, if the signing identity can't be had.
"$ROOT/scripts/sign_app.sh" --ensure-identity

# One date for every file: the commit's. A build outside git needs SOURCE_DATE_EPOCH set.
if [[ -z "${SOURCE_DATE_EPOCH:-}" ]]; then
    SOURCE_DATE_EPOCH="$(git -C "$ROOT" log -1 --format=%ct 2>/dev/null)" || {
        echo "build_app: not a git checkout; set SOURCE_DATE_EPOCH" >&2; exit 1; }
fi
export SOURCE_DATE_EPOCH
if [[ -n "$(git -C "$ROOT" status --porcelain 2>/dev/null)" ]]; then
    echo "build_app: warning: the checkout has uncommitted changes, so this build is not reproducible from a commit" >&2
fi
STAMP="$(TZ=UTC date -r "$SOURCE_DATE_EPOCH" +%Y%m%d%H%M.%S)"

fix_dates_and_modes() {  # the same dates and permissions whatever the umask and the clock
    TZ=UTC find "$APP" -exec touch -h -t "$STAMP" {} +
    find "$APP" -type d -exec chmod 755 {} +
    find "$APP" -type f -perm -u+x -exec chmod 755 {} +
    find "$APP" -type f ! -perm -u+x -exec chmod 644 {} +
}

VERSION="$(plutil -extract CFBundleShortVersionString raw "$ROOT/mac/Info.plist")"
mkdir -p "$C/MacOS" "$C/Resources" "$DISCARD"

say "Python $PY_VERSION (python-build-standalone via uv)"
PY_SRC_BIN="$(uv python find --managed-python "$PY_VERSION" 2>/dev/null)" || {
    uv python install "$PY_VERSION"
    PY_SRC_BIN="$(uv python find --managed-python "$PY_VERSION")"
}
PY_SRC="$(cd "$(dirname "$PY_SRC_BIN")/.." && pwd -P)"
ditto --noextattr --noqtn "$PY_SRC" "$PYDIR"
BUNDLED_PY="$PYDIR/bin/python3.14"

say "Web page (web/ -> web/dist)"
(cd "$ROOT/web" && npm ci --no-audit --no-fund --silent && npm run build --silent)

say "Light service and its locked dependencies"
REQS="$WORK/requirements.txt"
# Workspace members (godox-mesh-bt) are left out of the export and installed from source below.
uv export --project "$ROOT/service" --frozen --no-dev --no-emit-project --no-emit-workspace --quiet -o "$REQS"
# --break-system-packages: the bundled copy carries python-build-standalone's
# EXTERNALLY-MANAGED marker; this installs into that private copy only.
uv pip install --quiet --python "$BUNDLED_PY" --break-system-packages --require-hashes -r "$REQS"
uv pip install --quiet --python "$BUNDLED_PY" --break-system-packages --no-deps \
    "$ROOT/service/packages/godox-mesh-bt" "$ROOT/service"
# The built web page goes inside the service package, where gaffer/app.py looks first.
SITE="$("$BUNDLED_PY" -I -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
ditto --noextattr --noqtn "$ROOT/web/dist" "$SITE/gaffer/web"
# Take out what differs on every build (this Mac's paths, install times, old .pyc files).
"$BUNDLED_PY" -I "$ROOT/scripts/bundle_tool.py" prune "$PYDIR" "$DISCARD"

say "Licences"
# MIT requires the licence to travel with the code: lumen-studio's NOTICE and the others'
# LICENSE files, then Python's and each Python package's, all listed in NOTICE.
cp "$ROOT/NOTICE" "$C/Resources/NOTICE"
ditto --noextattr --noqtn "$ROOT/THIRD-PARTY" "$C/Resources/THIRD-PARTY"
cp "$ROOT/LICENSE" "$C/Resources/LICENSE"
"$BUNDLED_PY" -I "$ROOT/scripts/bundle_tool.py" licences "$C/Resources" "$PYDIR" "$ROOT"

# Compile once now; the app runs Python with -B so it never writes into the signed bundle.
# checked-hash .pyc files carry no date, and -s/-p give every file the same recorded path,
# so the result does not depend on where the build ran.
"$BUNDLED_PY" -I -m compileall -q -j 0 --invalidation-mode checked-hash \
    -s "$PYDIR" -p "/Gaffer.app/Contents/Resources/python" "$PYDIR/lib/python3.14" >/dev/null

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

say "Manifest (the app before signing)"
xattr -cr "$APP"
fix_dates_and_modes
MANIFEST="$DIST/Gaffer-$VERSION.manifest.txt"
"$BUNDLED_PY" -I "$ROOT/scripts/bundle_tool.py" manifest "$APP" > "$WORK/manifest.txt"
to_trash "$MANIFEST"
mv "$WORK/manifest.txt" "$MANIFEST"

"$ROOT/scripts/sign_app.sh" "$APP"
fix_dates_and_modes   # signing touched files and added _CodeSignature

ZIP="$DIST/Gaffer-$VERSION-macos-arm64.zip"
if [[ "${GAFFER_SIGN:-}" == "adhoc" ]]; then
    say "No release zip: this is an ad-hoc developer build"
else
    say "Release zip"
    to_trash "$ZIP"
    to_trash "$ZIP.sha256"
    # Sorted entries, no extra attributes (-X), links kept as links (-y), UTC dates.
    (cd "$WORK" && find Gaffer.app | LC_ALL=C sort | TZ=UTC zip -X -y -q "$WORK/Gaffer.zip" -@)
    mv "$WORK/Gaffer.zip" "$ZIP"
    (cd "$DIST" && shasum -a 256 "$(basename "$ZIP")" > "$(basename "$ZIP").sha256")
fi

say "$DIST/Gaffer.app"
to_trash "$DIST/Gaffer.app"
mv "$APP" "$DIST/Gaffer.app"

if [[ "$INSTALL" == 1 ]]; then
    say "~/Applications/Gaffer.app"
    mkdir -p "$HOME/Applications"
    to_trash "$HOME/Applications/Gaffer.app"
    ditto "$DIST/Gaffer.app" "$HOME/Applications/Gaffer.app"
    codesign --verify --deep --strict "$HOME/Applications/Gaffer.app"
fi
say "Done."
