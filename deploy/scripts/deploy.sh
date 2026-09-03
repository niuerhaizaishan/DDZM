#!/usr/bin/env bash
set -euo pipefail
dzmm_release_dir=${1:-}
[ -n "$dzmm_release_dir" ] && [ -f "$dzmm_release_dir/pyproject.toml" ] || {
  echo 'usage: deploy.sh RELEASE_DIRECTORY' >&2
  exit 2
}
install -d -o dzmm -g dzmm /opt/dzmm/current
rsync -a --delete --delete-excluded \
  --exclude .git \
  --exclude .env \
  --exclude .venv \
  --exclude .worktrees \
  --exclude __pycache__ \
  --exclude '*.pyc' \
  --exclude .DS_Store \
  --exclude '._*' \
  "$dzmm_release_dir/" /opt/dzmm/current/
chown -R dzmm:dzmm /opt/dzmm/current
python3 -m venv /opt/dzmm/venv
/opt/dzmm/venv/bin/pip install --upgrade pip
/opt/dzmm/venv/bin/pip install /opt/dzmm/current
runuser -u dzmm -- /opt/dzmm/venv/bin/playwright install chromium
set -a
source /etc/dzmm/dzmm.env
set +a
cd /opt/dzmm/current
/opt/dzmm/venv/bin/alembic -c /opt/dzmm/current/alembic.ini upgrade head
install -m 644 /opt/dzmm/current/deploy/systemd/dzmm-*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable dzmm-ai-worker.service
systemctl enable dzmm-ai-memory-worker.service
systemctl stop dzmm-admin-web.service dzmm-browser-worker.service dzmm-ai-worker.service dzmm-ai-memory-worker.service
systemctl restart dzmm-core.service
dzmm_core_ready=false
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:18120/healthz >/dev/null; then
    dzmm_core_ready=true
    break
  fi
  sleep 1
done
if [ "$dzmm_core_ready" != true ]; then
  systemctl status dzmm-core.service --no-pager
  exit 1
fi
systemctl reset-failed dzmm-admin-web.service dzmm-browser-worker.service dzmm-ai-worker.service dzmm-ai-memory-worker.service || true
systemctl restart dzmm-admin-web.service dzmm-browser-worker.service dzmm-ai-worker.service dzmm-ai-memory-worker.service
