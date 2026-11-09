#!/usr/bin/env bash
set -euo pipefail
[ "${1:-}" = "--apply" ] || { echo 'use --apply'; exit 2; }
id dzmm >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin dzmm
install -d -o dzmm -g dzmm /opt/dzmm /var/lib/dzmm-browser /var/log/dzmm
install -d -m 700 -o root -g root /etc/dzmm
apt-get update
apt-get install -y python3-venv xvfb fluxbox x11vnc novnc websockify fonts-noto-cjk
