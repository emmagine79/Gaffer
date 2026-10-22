#!/usr/bin/env bash
# Publish site/ to https://gaffer.awelahlayray.work on the DigitalOcean VPS (SPEC-018).
#
# Safe to re-run. Each run:
#   1. checks the gaffer DNS name points at the VPS,
#   2. rsyncs site/ (and only site/) to its own folder on the VPS,
#   3. adds the Caddy server block if it is missing (backup, validate, reload),
#   4. waits for Caddy to hold a valid certificate,
#   5. proves the live page: HTTP 200, issuer and expiry, and the same hash as site/index.html.
#
# It touches only: /var/www/gaffer.awelahlayray.work and one server block in /etc/caddy/Caddyfile.
# It never edits DNS. The A record is added once by hand (see SPEC-018).
#
# Usage:  scripts/deploy_site.sh            deploy and verify
#         DRY_RUN=1 scripts/deploy_site.sh  show the rsync plan and validate the new Caddy block; change nothing
set -euo pipefail

SITE_HOST="${SITE_HOST:-gaffer.awelahlayray.work}"
VPS_ALIAS="${VPS_ALIAS:-awesome-vps}"   # ssh alias from the digitalocean-vps-deploy skill
VPS_IP="${VPS_IP:-159.89.203.137}"      # A record of awelahlayray.work
REMOTE_ROOT="/var/www/${SITE_HOST}"
CADDYFILE="/etc/caddy/Caddyfile"
# Certificate wait: Let's Encrypt normally answers in under a minute. 24 x 5 s = 2 minutes is
# a stop condition for this script only, not a platform limit.
CERT_TRIES=24
CERT_PAUSE=5
DRY_RUN="${DRY_RUN:-0}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE_DIR="${ROOT}/site"

say() { printf '==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$1" >&2; exit "${2:-1}"; }

[ -f "${SITE_DIR}/index.html" ] || die "site/index.html is missing"
for tool in rsync ssh curl openssl dig shasum; do
  command -v "$tool" >/dev/null || die "$tool is not installed"
done

# Only site/ is published. Refuse if a research or binary file sits inside it.
if find "${SITE_DIR}" -type f \( -name '*.apk' -o -name '*.dex' -o -name '*.so' -o -name '*.xapk' -o -name '*.jar' \) | grep -q .; then
  die "site/ holds a binary file that must never be published"
fi

say "1/5 DNS: ${SITE_HOST} must point at ${VPS_IP}"
dns_ip="$(dig +short A "${SITE_HOST}" @1.1.1.1 | tail -n1)"
if [ "${dns_ip}" != "${VPS_IP}" ]; then
  die "${SITE_HOST} resolves to '${dns_ip:-nothing}', not ${VPS_IP}. Add the A record 'gaffer' -> ${VPS_IP} at Porkbun, then re-run." 2
fi

say "2/5 VPS access"
ssh -o BatchMode=yes -o ConnectTimeout=10 "${VPS_ALIAS}" 'caddy version >/dev/null && test -f '"${CADDYFILE}" \
  || die "cannot reach the VPS or Caddy through ssh alias ${VPS_ALIAS}" 3

say "3/5 Upload site/ to ${REMOTE_ROOT} (rsync --delete on this one folder only)"
rsync_flags=(-az --delete --exclude '.DS_Store')
if [ "${DRY_RUN}" = "1" ]; then rsync_flags+=(--dry-run -v); else
  ssh "${VPS_ALIAS}" "mkdir -p '${REMOTE_ROOT}'"
fi
rsync "${rsync_flags[@]}" "${SITE_DIR}/" "${VPS_ALIAS}:${REMOTE_ROOT}/"

say "4/5 Caddy server block for ${SITE_HOST}"
# Runs on the VPS. Adds the block only if it is missing, validates before reloading,
# restores the backup if validation fails, and reloads (never restarts) Caddy.
ssh "${VPS_ALIAS}" bash -s -- "${SITE_HOST}" "${REMOTE_ROOT}" "${CADDYFILE}" "${DRY_RUN}" <<'REMOTE'
set -euo pipefail
host="$1"; root="$2"; caddyfile="$3"; dry="$4"
block="${host} {
	root * ${root}
	encode gzip
	file_server
}"
if grep -qxF "${host} {" "${caddyfile}"; then
  echo "block already present"
  caddy validate --config "${caddyfile}" >/dev/null 2>&1
  exit 0
fi
candidate="$(mktemp)"
trap 'rm -f "${candidate}"' EXIT
{ cat "${caddyfile}"; printf '\n%s\n' "${block}"; } > "${candidate}"
if [ "${dry}" = "1" ]; then
  caddy validate --config "${candidate}" --adapter caddyfile >/dev/null 2>&1 && echo "dry run: new block validates, nothing changed"
  exit 0
fi
backup="${caddyfile}.bak-$(date +%Y%m%d-%H%M%S)"
cp -p "${caddyfile}" "${backup}"
cat "${candidate}" > "${caddyfile}"
if ! caddy validate --config "${caddyfile}" >/dev/null 2>&1; then
  cp -p "${backup}" "${caddyfile}"
  echo "Caddy rejected the new block; the old Caddyfile is restored" >&2
  exit 1
fi
systemctl reload caddy
echo "block added and Caddy reloaded (backup: ${backup})"
REMOTE

if [ "${DRY_RUN}" = "1" ]; then say "dry run finished; nothing was changed"; exit 0; fi

say "5/5 Certificate and live page"
url="https://${SITE_HOST}"
for i in $(seq 1 "${CERT_TRIES}"); do
  if curl -sS -o /dev/null --max-time 15 "${url}" 2>/dev/null; then break; fi
  [ "${i}" = "${CERT_TRIES}" ] && die "no valid certificate after $((CERT_TRIES * CERT_PAUSE)) seconds; check 'journalctl -u caddy' on the VPS" 4
  sleep "${CERT_PAUSE}"
done

status_line="$(curl -sSI --max-time 15 "${url}" | head -n1 | tr -d '\r')"
case "${status_line}" in *" 200"*) ;; *) die "expected HTTP 200, got: ${status_line}" 5 ;; esac

cert="$(printf '' | openssl s_client -connect "${SITE_HOST}:443" -servername "${SITE_HOST}" 2>/dev/null | openssl x509 -noout -issuer -enddate)"
printf '%s\n' "${status_line}" "${cert}"

local_hash="$(shasum -a 256 "${SITE_DIR}/index.html" | cut -d' ' -f1)"
live_hash="$(curl -sS --max-time 15 "${url}/index.html" | shasum -a 256 | cut -d' ' -f1)"
printf 'site/index.html  %s\nserved           %s\n' "${local_hash}" "${live_hash}"
[ "${local_hash}" = "${live_hash}" ] || die "served index.html differs from site/index.html" 6

say "OK: ${url} serves site/index.html with a valid certificate"
