#!/bin/bash
# Sign Gaffer.app (and every Mach-O file inside it) so that its designated requirement is the
# same on every build. macOS ties the Bluetooth permission to that requirement, so the
# permission survives a rebuild or an update instead of being asked for again.
#
#   scripts/sign_app.sh path/to/Gaffer.app    sign with the fixed identity; fails if there is none
#   scripts/sign_app.sh --ensure-identity     make the identity if it is missing, then stop
#
# The identity is a fixed self-signed code-signing certificate, "Gaffer Local Signing", kept in
# its own keychain file under ~/Library/Application Support/Gaffer-build/ (change the folder
# with GAFFER_BUILD_HOME). The script makes it on the first run. It is never added to the
# login or system keychain and no trust setting is changed: codesign signs with an untrusted
# self-signed identity when it is named with --keychain (checked on macOS 27.0.1).
# The designated requirement is codesign's own default for a certificate:
#   identifier "<bundle id>" and certificate leaf = H"<certificate sha1>"
# It pins the certificate, so another app with the same bundle id but another key does not
# satisfy it and can't inherit Gaffer's Bluetooth permission. There is no Developer ID, so
# the certificate is self-signed: macOS can't tell who made it, and whoever holds the keychain
# file can sign as Gaffer. Keep that file private.
#
# If the identity can't be made or used, this script FAILS. It never signs ad hoc by itself.
# GAFFER_SIGN=adhoc is a developer flag for a quick local build: the app is signed ad hoc with
# codesign's default requirement (the hash of that build's code), which changes on every build,
# so macOS asks for Bluetooth again each time. build_app.sh makes no release zip in that mode.
#
# Signing uses no hardened runtime: a self-signed or ad-hoc code has no team id, so library
# validation would refuse Python's own extension modules.
set -euo pipefail

BUNDLE_ID="work.awelahlayray.gaffer"
IDENTITY_NAME="Gaffer Local Signing"
BUILD_HOME="${GAFFER_BUILD_HOME:-$HOME/Library/Application Support/Gaffer-build}"
KEYCHAIN="$BUILD_HOME/signing.keychain-db"
PASSFILE="$BUILD_HOME/signing.keychain.pass"
NEW_KEYCHAIN="$KEYCHAIN.new.$$"
# Long enough that the identity never lapses under a person. A certificate's own expiry is
# not checked by the requirement above.
CERT_DAYS=36500

say() { printf '==> %s\n' "$*"; }

identity_hash() {  # prints the SHA-1 of the identity, or nothing
    [[ -f "$KEYCHAIN" ]] || return 0
    security find-identity -p codesigning "$KEYCHAIN" 2>/dev/null | awk -v n="\"$IDENTITY_NAME\"" '$0 ~ n {print $2; exit}'
}

to_trash() {  # move a path to the Trash with a unique name; nothing is deleted
    [[ -e "$1" ]] || return 0
    mkdir -p "$HOME/.Trash"
    mv "$1" "$HOME/.Trash/$(basename "$1")-$(date +%Y%m%d-%H%M%S)-$$"
}

make_identity() {
    # Built under a temporary name and moved into place whole, so a crash half-way (or a
    # second build starting at the same moment) never leaves a half-made keychain behind.
    # The private key is held in memory and never written to a file outside the keychain.
    local tmp="$NEW_KEYCHAIN" pass
    mkdir -p "$BUILD_HOME" && chmod 700 "$BUILD_HOME" || return 1
    pass="$(/usr/bin/openssl rand -hex 24)"
    security create-keychain -p "$pass" "$tmp" || return 1
    security set-keychain-settings "$tmp" || return 1   # no automatic lock
    security unlock-keychain -p "$pass" "$tmp" || return 1
    local pem
    pem="$(/usr/bin/openssl req -x509 -newkey rsa:2048 -nodes -days "$CERT_DAYS" \
        -keyout /dev/stdout -out /dev/stdout 2>/dev/null \
        -config <(printf '%s\n' '[req]' 'distinguished_name=dn' 'x509_extensions=ext' 'prompt=no' \
            '[dn]' "CN=$IDENTITY_NAME" '[ext]' 'basicConstraints=critical,CA:false' \
            'keyUsage=critical,digitalSignature' 'extendedKeyUsage=critical,codeSigning'))" || return 1
    # A here-string is the key's only copy outside the keychain, held in memory and never named.
    security import /dev/stdin -k "$tmp" -f pemseq -T /usr/bin/codesign >/dev/null <<< "$pem" || return 1
    security set-key-partition-list -S apple-tool:,apple: -s -k "$pass" "$tmp" >/dev/null || return 1
    if mv -n "$tmp" "$KEYCHAIN" && [[ ! -e "$tmp" ]]; then
        (umask 077; printf '%s' "$pass" > "$PASSFILE")
    else   # another build won the race: use its identity
        to_trash "$tmp"
    fi
}

use_identity() {  # sets SIGN_ARGS and MODE; returns 1 when there is no usable identity
    if [[ -f "$KEYCHAIN" && ( ! -f "$PASSFILE" || -z "$(identity_hash)" ) ]]; then
        # Its password is lost, or the identity is not in it: it can't be used, so make a new one.
        to_trash "$KEYCHAIN"
        to_trash "$PASSFILE"
    fi
    [[ -f "$KEYCHAIN" ]] || make_identity || { to_trash "$NEW_KEYCHAIN"; return 1; }
    local hash
    hash="$(identity_hash)"
    [[ -n "$hash" && -f "$PASSFILE" ]] || return 1
    security unlock-keychain -p "$(cat "$PASSFILE")" "$KEYCHAIN" || return 1
    SIGN_ARGS=(--sign "$hash" --keychain "$KEYCHAIN" --timestamp=none)
    MODE="identity $hash"
}

to_sign_args() {
    case "${GAFFER_SIGN:-}" in
        "") use_identity || { echo "sign_app: the Gaffer signing identity is not available, so nothing was signed. Fix it, or set GAFFER_SIGN=adhoc for a local build that is not for release." >&2; exit 1; } ;;
        adhoc) SIGN_ARGS=(--sign -); MODE="AD HOC (developer build, not for release)" ;;
        *) echo "sign_app: GAFFER_SIGN may only be empty or adhoc" >&2; exit 2 ;;
    esac
}

MODE=""
SIGN_ARGS=()
if [[ "${1:-}" == "--ensure-identity" ]]; then
    [[ "${GAFFER_SIGN:-}" == "adhoc" ]] && exit 0
    to_sign_args
    say "Signing identity ready: $MODE"
    exit 0
fi

APP="${1:?usage: sign_app.sh path/to/Gaffer.app}"
[[ -d "$APP/Contents" ]] || { echo "sign_app: $APP is not an app bundle" >&2; exit 1; }
to_sign_args

say "Signing inside out: $MODE"
# Every Mach-O file is signed first, then the app, whose seal covers them.
while IFS= read -r -d '' f; do
    if file -b "$f" | grep -q 'Mach-O'; then
        codesign --force "${SIGN_ARGS[@]}" "$f" 2>/dev/null
    fi
done < <(find "$APP/Contents/Resources" -type f \( -name '*.so' -o -name '*.dylib' -o -perm -u+x \) -print0)
codesign --force "${SIGN_ARGS[@]}" --identifier "$BUNDLE_ID" "$APP"
codesign --verify --deep --strict "$APP"
codesign -d -r- "$APP" 2>&1 | sed -n 's/^designated => /Designated requirement: /p'
