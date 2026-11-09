#!/usr/bin/env bash
set -euo pipefail

if [[ "$EUID" -ne 0 ]]; then
    printf '%s\n' 'Run the entire script using sudo bash.' >&2
    exit 1
fi

source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../caddy" && pwd)"
: "${DZMM_PUBLIC_HOST:?Set DZMM_PUBLIC_HOST to your public DNS hostname, without a scheme or port}"
admin_web_port="${DZMM_ADMIN_WEB_PORT:-18090}"
# Validate before downloading software, changing services, or touching the firewall.
python3 - "$DZMM_PUBLIC_HOST" "$admin_web_port" <<'PY'
import ipaddress, re, sys
host, port = sys.argv[1:]
labels = host.split('.')
if len(host) > 253 or len(labels) < 2 or any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label) for label in labels):
    raise SystemExit('DZMM_PUBLIC_HOST must be a DNS hostname')
try:
    ipaddress.ip_address(host)
except ValueError:
    pass
else:
    raise SystemExit('Use a stable DNS hostname instead of a server IP')
if not port.isascii() or not port.isdecimal() or not 1 <= int(port) <= 65535:
    raise SystemExit('DZMM_ADMIN_WEB_PORT must be between 1 and 65535')
PY
caddy_version=2.11.7
caddy_archive_sha256=727b91701a392de6ebc5027509f548bf39979e5216340d0faed8fa5e69c84f8b
backup_dir="/var/backups/dzmm-https/$(date -u +%Y%m%dT%H%M%SZ)"
download_dir="$(mktemp -d /tmp/dzmm-caddy.XXXXXXXX)"
trap 'rm -rf -- "$download_dir"' EXIT

if [[ "$(uname -m)" != x86_64 ]]; then
    printf '%s\n' 'This pinned release is for Linux x86_64 only.' >&2
    exit 1
fi

install -d -m 0700 "$backup_dir"
for existing in /etc/caddy/Caddyfile /etc/caddy/dzmm.env /etc/systemd/system/caddy.service /usr/local/bin/caddy; do
    if [[ -f "$existing" ]]; then
        cp -a --parents "$existing" "$backup_dir"
    fi
done
ufw status > "$backup_dir/ufw-before.txt"
for rules in /etc/ufw/user.rules /etc/ufw/user6.rules; do
    if [[ -f "$rules" ]]; then
        cp -a --parents "$rules" "$backup_dir"
    fi
done

curl -fL --connect-timeout 15 --max-time 180 --retry 2 \
    "https://github.com/caddyserver/caddy/releases/download/v${caddy_version}/caddy_${caddy_version}_linux_amd64.tar.gz" \
    -o "$download_dir/caddy.tar.gz"
printf '%s  %s\n' "$caddy_archive_sha256" "$download_dir/caddy.tar.gz" | sha256sum --check --status
tar -xzf "$download_dir/caddy.tar.gz" -C "$download_dir" caddy
install -m 0755 "$download_dir/caddy" /usr/local/bin/caddy

if ! getent group caddy > /dev/null; then
    groupadd --system caddy
fi
if ! id caddy > /dev/null 2>&1; then
    useradd --system --gid caddy --home-dir /var/lib/caddy --shell /usr/sbin/nologin caddy
fi
install -d -o root -g caddy -m 0750 /etc/caddy
install -d -o caddy -g caddy -m 0750 /var/lib/caddy
install -o root -g caddy -m 0640 "$source_dir/Caddyfile" /etc/caddy/Caddyfile
printf 'DZMM_PUBLIC_HOST=%s\nDZMM_ADMIN_WEB_PORT=%s\n' "$DZMM_PUBLIC_HOST" "$admin_web_port" > "$download_dir/dzmm.env"
install -o root -g caddy -m 0640 "$download_dir/dzmm.env" /etc/caddy/dzmm.env
install -o root -g root -m 0644 "$source_dir/caddy.service" /etc/systemd/system/caddy.service
/usr/local/bin/caddy fmt --overwrite /etc/caddy/Caddyfile
runuser -u caddy -- env XDG_DATA_HOME=/var/lib/caddy XDG_CONFIG_HOME=/var/lib/caddy \
    DZMM_PUBLIC_HOST="$DZMM_PUBLIC_HOST" DZMM_ADMIN_WEB_PORT="$admin_web_port" \
    /usr/local/bin/caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

ufw allow 80/tcp
ufw allow 443/tcp
systemctl daemon-reload
systemctl enable caddy
if systemctl is-active --quiet caddy; then
    systemctl reload caddy
else
    systemctl start caddy
fi
systemctl is-active caddy dzmm-core dzmm-admin-web dzmm-browser-worker dzmm-ai-worker dzmm-ai-memory-worker
printf 'Backup: %s\n' "$backup_dir"
printf '%s\n' 'Caddy started. Verify certificate issuance and external HTTPS before declaring deployment complete.'
