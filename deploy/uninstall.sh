#!/usr/bin/env bash
# Reverses deploy/install.sh. Run with sudo from the repo root.
#
# Does NOT remove: the .venv (harmless leftover directory, just delete it
# manually if desired), or nginx/openssl/acl packages themselves (installed
# via apt, shared with other potential uses of this host).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_USER="mdm-svc"

systemctl stop mdm.service 2>/dev/null || true
systemctl disable mdm.service 2>/dev/null || true
rm -f /etc/systemd/system/mdm.service

systemctl stop mdm-purge.timer 2>/dev/null || true
systemctl disable mdm-purge.timer 2>/dev/null || true
rm -f /etc/systemd/system/mdm-purge.timer /etc/systemd/system/mdm-purge.service
systemctl daemon-reload

rm -f /etc/nginx/sites-enabled/mdm.conf
rm -f /etc/nginx/sites-available/mdm.conf
systemctl reload nginx 2>/dev/null || true

# Mirrors install.sh's grant_traverse_acl: it walks every ancestor of
# REPO_DIR up to "/" (not just the immediate parent), so removal has to
# walk the same chain or it leaves a stray traverse grant behind (e.g. on
# the owning user's home directory, two levels up from a repo cloned to
# ~/projects/<name>).
revoke_traverse_acl() {
  local user="$1" dir="$2"
  while [ "$dir" != "/" ] && [ -n "$dir" ]; do
    setfacl -x "u:${user}" "$dir" 2>/dev/null || true
    dir="$(dirname "$dir")"
  done
}

revoke_traverse_acl "$SERVICE_USER" "$(dirname "$REPO_DIR")"
setfacl -R -x "u:${SERVICE_USER}" "$REPO_DIR" 2>/dev/null || true
setfacl -R -d -x "u:${SERVICE_USER}" "$REPO_DIR" 2>/dev/null || true

revoke_traverse_acl "www-data" "$(dirname "$REPO_DIR")"
setfacl -x "u:www-data" "$REPO_DIR" 2>/dev/null || true
setfacl -x "u:www-data" "$REPO_DIR/frontend" 2>/dev/null || true
setfacl -R -x "u:www-data" "$REPO_DIR/frontend/dist" 2>/dev/null || true
setfacl -R -d -x "u:www-data" "$REPO_DIR/frontend/dist" 2>/dev/null || true

if id "$SERVICE_USER" >/dev/null 2>&1; then
  userdel "$SERVICE_USER"
fi

echo "Done. Not removed: $REPO_DIR/.venv, $REPO_DIR/frontend/{node_modules,dist}, /etc/nginx/ssl/mdm-selfsigned.{crt,key} (delete manually if desired)."
