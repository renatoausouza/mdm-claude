#!/usr/bin/env bash
# Deployment skeleton install script (ticket #1).
#
# Idempotent-ish setup of: a dedicated non-root service user, the systemd
# unit, and an nginx reverse proxy terminating TLS in front of the fixed
# application port. Run with sudo from the repo root.
#
# NOTE: the TLS cert generated here is self-signed, for smoke-testing only.
# Production deployment should use a CA-issued certificate (e.g. certbot)
# once a real domain is available for the OCI VM.
#
# To reverse these changes, see deploy/uninstall.sh.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER="mdm-svc"
MDM_PORT="${MDM_PORT:-8000}"
# OCI Generative AI compartment/region — required for extraction/chat to
# actually work, but left unset-able here so install.sh doesn't hard-fail
# on a fresh checkout; the app itself raises a clear error on first use if
# still unset once the service is up.
OCI_GENAI_COMPARTMENT_ID="${OCI_GENAI_COMPARTMENT_ID:-}"
OCI_GENAI_REGION="${OCI_GENAI_REGION:-}"

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi

# Grant traverse (x) ACL on every ancestor directory up to (but not
# including) "/" — not just the immediate parent. A restrictive permission
# on ANY ancestor blocks traversal regardless of what's granted below it,
# and REPO_DIR's immediate parent isn't the only one that can be
# restrictive: a user's home directory (commonly mode 750, as ubuntu's is
# here) sits two levels up from a repo cloned to ~/projects/<name>, and
# granting only dirname($REPO_DIR) silently leaves that level unfixed.
grant_traverse_acl() {
  local user="$1" dir="$2"
  while [ "$dir" != "/" ] && [ -n "$dir" ]; do
    setfacl -m "u:${user}:x" "$dir"
    dir="$(dirname "$dir")"
  done
}

# Grant the service user read/traverse access to the repo without adding it
# to the owning user's group (surgical ACL, not a broad group grant) and
# without a recursive chgrp/chmod, which would overwrite existing ownership.
# The default ACL (-d) covers files added later (e.g. by `git pull`).
grant_traverse_acl "$SERVICE_USER" "$(dirname "$REPO_DIR")"
setfacl -R -m "u:${SERVICE_USER}:rX" "$REPO_DIR"
setfacl -R -d -m "u:${SERVICE_USER}:rX" "$REPO_DIR"

# data/ (documents, the SQLite DB, the encryption key) needs write access,
# unlike the rest of the repo — granted narrowly, not via the read-only
# grant above. The systemd unit's ReadWritePaths= lifts the ProtectSystem=
# strict mount restriction for this same path; this ACL is what actually
# grants the POSIX permission underneath it.
mkdir -p "$REPO_DIR/data/documents" "$REPO_DIR/data/oci"
setfacl -R -m "u:${SERVICE_USER}:rwX" "$REPO_DIR/data"
setfacl -R -d -m "u:${SERVICE_USER}:rwX" "$REPO_DIR/data"

python3 -m venv "$REPO_DIR/.venv"
"$REPO_DIR/.venv/bin/pip" install --upgrade pip -q
"$REPO_DIR/.venv/bin/pip" install -e "$REPO_DIR" -q

command -v npm >/dev/null || {
  echo "npm is required to build the frontend but was not found on PATH." >&2
  exit 1
}
# npm ci (not install) so the build is reproducible from package-lock.json;
# nginx serves the static output directly (deploy/nginx-mdm.conf), it never
# goes through the Node process at runtime.
( cd "$REPO_DIR/frontend" && npm ci -q && npm run build )

# nginx (runs as www-data) reads the built SPA straight off disk, unlike
# the backend which only mdm-svc needs to reach — same surgical-ACL
# approach as the mdm-svc grants above, scoped to just the build output
# rather than the whole repo (frontend/dist has no secrets, but there's no
# reason to widen access further than necessary).
grant_traverse_acl "www-data" "$(dirname "$REPO_DIR")"
setfacl -m "u:www-data:x" "$REPO_DIR"
setfacl -m "u:www-data:x" "$REPO_DIR/frontend"
setfacl -R -m "u:www-data:rX" "$REPO_DIR/frontend/dist"
setfacl -R -d -m "u:www-data:rX" "$REPO_DIR/frontend/dist"

# Template the repo path and port into the unit file rather than installing
# it verbatim — mdm.service in source control has no hardcoded environment
# assumptions, so it works regardless of where the repo is cloned or which
# port is configured.
sed -e "s#__REPO_DIR__#${REPO_DIR}#g" -e "s#__MDM_PORT__#${MDM_PORT}#g" \
  -e "s#__OCI_GENAI_COMPARTMENT_ID__#${OCI_GENAI_COMPARTMENT_ID}#g" \
  -e "s#__OCI_GENAI_REGION__#${OCI_GENAI_REGION}#g" \
  "$REPO_DIR/deploy/mdm.service" > /etc/systemd/system/mdm.service
chmod 644 /etc/systemd/system/mdm.service
sed -e "s#__REPO_DIR__#${REPO_DIR}#g" \
  "$REPO_DIR/deploy/mdm-purge.service" > /etc/systemd/system/mdm-purge.service
chmod 644 /etc/systemd/system/mdm-purge.service
cp "$REPO_DIR/deploy/mdm-purge.timer" /etc/systemd/system/mdm-purge.timer
chmod 644 /etc/systemd/system/mdm-purge.timer

systemctl daemon-reload
systemctl enable mdm.service
systemctl restart mdm.service
systemctl enable --now mdm-purge.timer

mkdir -p /etc/nginx/ssl
if [ ! -f /etc/nginx/ssl/mdm-selfsigned.crt ]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
    -keyout /etc/nginx/ssl/mdm-selfsigned.key \
    -out /etc/nginx/ssl/mdm-selfsigned.crt \
    -subj "/CN=mdm.local"
  chmod 600 /etc/nginx/ssl/mdm-selfsigned.key
fi

sed -e "s#__MDM_PORT__#${MDM_PORT}#g" -e "s#__REPO_DIR__#${REPO_DIR}#g" \
  "$REPO_DIR/deploy/nginx-mdm.conf" > /etc/nginx/sites-available/mdm.conf
chmod 644 /etc/nginx/sites-available/mdm.conf
ln -sf /etc/nginx/sites-available/mdm.conf /etc/nginx/sites-enabled/mdm.conf
# Deliberately not touching sites-enabled/default: our server block is
# scoped to server_name mdm.local, so it doesn't need the default site
# removed, and this host may be serving other vhosts through it.
nginx -t
systemctl reload nginx || systemctl restart nginx

echo "Done. Verify with: systemctl status mdm.service mdm-purge.timer nginx"
if [ ! -s "$REPO_DIR/data/oci/config" ]; then
  echo "NOTE: $REPO_DIR/data/oci/config is missing/empty — extraction and" \
       "the chat feature will fail until a real OCI API-key config (and its" \
       "private key file) are placed there. See README.md."
fi
if [ -z "$OCI_GENAI_COMPARTMENT_ID" ] || [ -z "$OCI_GENAI_REGION" ]; then
  echo "NOTE: OCI_GENAI_COMPARTMENT_ID and/or OCI_GENAI_REGION were not set" \
       "when install.sh ran — edit /etc/systemd/system/mdm.service and" \
       "run 'systemctl daemon-reload && systemctl restart mdm.service'."
fi
