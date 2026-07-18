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

setfacl -x "u:${SERVICE_USER}" "$(dirname "$REPO_DIR")" 2>/dev/null || true
setfacl -R -x "u:${SERVICE_USER}" "$REPO_DIR" 2>/dev/null || true
setfacl -R -d -x "u:${SERVICE_USER}" "$REPO_DIR" 2>/dev/null || true

if id "$SERVICE_USER" >/dev/null 2>&1; then
  userdel "$SERVICE_USER"
fi

echo "Done. Not removed: $REPO_DIR/.venv, /etc/nginx/ssl/mdm-selfsigned.{crt,key} (delete manually if desired)."
