#!/bin/bash
# 部署：大话骰子三超时（报名 / 等待继续 / 发牌）+ 万能点文案统一 + 两道互斥闸门各自补全（迁移 102/103）
# 另：成对对齐服务器长期陈旧的 admin 前端。历史部署脚本的 scp 清单不含 admin.js，
#     导致服务器 static/admin.js 停在旧版；而新版 admin.js 中 `#random-event-vote-enabled`
#     等引用没有空值守卫，只换 JS 会让「随机事件 → 事件规则」页报错，
#     且投票接口方法在陈旧的 core_client.py 里缺失 → 三件必须一起换（均为纯新增）。
#
# scp 清单与 cp 一一对应（勿删改，核对用）：
#   core_schema.py core_repository.py core_commands.py core_liar_dice.py core_api_models.py
#   core_app.py admin_app.py admin_admin.js admin_index.html admin_core_client.py
#   mig_102.py mig_103.py
#
# 用法：
#   scp <上述 12 个文件> ubuntu@43.153.194.94:/tmp/
#   scp scripts/deploy_liar_dice_timeouts.sh ubuntu@43.153.194.94:/tmp/
#   ssh ubuntu@43.153.194.94 'sudo bash /tmp/deploy_liar_dice_timeouts.sh'
#
# 设计要点（都是踩过坑后的写法）：
#   0) 先逐文件校验 sha256：/tmp 里常有上次部署的同名残留，scp 通配漏一个就会把旧文件拷进生产
#   1) 先迁移、后换码：本次迁移仅 ADD COLUMN，旧代码不引用 → 可不停 core 先迁移；
#      迁移失败时 core 仍在跑旧代码、库停在原版本，零影响
#   2) 等 core 真正就绪（轮询 healthz，实测 uvicorn 约 10–12 秒）再启 worker：
#      否则 worker 会 httpx.ConnectError 抢跑，连续重启触发 "Start request repeated too quickly" 变 failed
#   3) 备份 + 失败自动回滚（文件级；数据库需手动 alembic downgrade -1）
set -uo pipefail
VENV=/opt/dzmm/venv/lib/python3.12/site-packages/dzmm_bot
CUR=/opt/dzmm/current
SRC="$CUR/src/dzmm_bot"
AL="/opt/dzmm/venv/bin/alembic -c $CUR/alembic.ini"
BK=/tmp/dzmm_backup_$(date +%Y%m%d_%H%M%S)

PYFILES="core/schema.py core/repository.py core/commands.py core/liar_dice.py core/api_models.py core/app.py"
FLAT="core_schema.py core_repository.py core_commands.py core_liar_dice.py core_api_models.py core_app.py"
ADMINPAIRS="admin_app.py:admin/app.py admin_admin.js:admin/static/admin.js admin_index.html:admin/templates/index.html admin_core_client.py:admin/core_client.py"
COPIED=0
WORKERS="dzmm-browser-worker dzmm-ai-worker dzmm-ai-memory-worker"

# 期望哈希（对应分支 nuo/performance_ganize 的 HEAD；改代码后须同步更新，否则脚本会拒跑）
declare -A WANT=(
  [core_schema.py]=684c40f8d5efdc8afce4433bdd597e879f2964535241e2616fec1883aeb35e20
  [core_repository.py]=b4083bb502abc85450ffe0c9c4d25ffe6456805beb3e2a21191b8c2902fad9cb
  [core_commands.py]=ea7dd97497f5fd8c222fad15ad84bc4ed07778eb8c83e1d91e28068dbab03c5b
  [core_liar_dice.py]=fe555ae6639917386664c399375d04cc0d695e5e853303d8edb6666ca6325f81
  [core_api_models.py]=8f3998ecb38d591850ad1ce880eb9d3f76f30945ddb5bce7ce0796711b04423d
  [core_app.py]=c7ba1e7023987dcf90c822832b441980357e7b5b221e5c1652eca60756c1d1f5
  [admin_app.py]=df77026a3803b92a231ca785fe1b686b8260be21317ecd327779da630fd7f4ea
  [admin_admin.js]=3decf868c2f5dd3c92b331cf0eaf6fe604fe02c821c1be807193172ce807f68c
  [admin_index.html]=a1c2aae9bfc984a06f479e50f7636171e6e94a812ba2b30083470483bbf2daa4
  [admin_core_client.py]=f36336943d018712bfd7b5b067ae4c2a9e10a1d39f230e22c3c161090311c48a
  [mig_102.py]=b9ab7471ac041e01b7a1cca8aff4a51adc8a615bb0db73c839d18ac6c7bbbe5a
  [mig_103.py]=ae99a1e075f4848fe652a8910c098a22f5b747875c0adeb0e84b9f7ef19c9573
)

restore() {
  echo "→ 回滚文件"
  i=0
  for rel in $PYFILES; do
    i=$((i+1)); flat=$(echo $FLAT | cut -d' ' -f$i)
    [ -f "$BK/cur_$flat" ] && cp -p "$BK/cur_$flat" "$SRC/$rel"
    [ -f "$BK/venv_$flat" ] && cp -p "$BK/venv_$flat" "$VENV/$rel"
  done
  for pair in $ADMINPAIRS; do
    flat=${pair%%:*}; rel=${pair#*:}
    [ -f "$BK/cur_$flat" ] && cp -p "$BK/cur_$flat" "$SRC/$rel"
    [ -f "$BK/venv_$flat" ] && cp -p "$BK/venv_$flat" "$VENV/$rel"
  done
  systemctl restart dzmm-core dzmm-admin-web 2>/dev/null || true
  wait_core || true
  systemctl reset-failed $WORKERS 2>/dev/null || true
  systemctl start $WORKERS 2>/dev/null || true
}
fail() { echo "❌ 失败：$1"; [ "$COPIED" = "1" ] && restore; exit 1; }

wait_core() {
  echo "  等 core 就绪（最长 60s）..."
  for i in $(seq 1 30); do
    if curl -sf --max-time 3 http://127.0.0.1:18120/healthz >/dev/null; then
      echo "  ✓ core 第 $((i*2)) 秒就绪"; return 0
    fi
    sleep 2
  done
  echo "  ✗ 60 秒内未就绪"; return 1
}

echo "== 0) 校验 /tmp 里的 12 个文件（防上次部署的同名残留）=="
bad=0
for f in "${!WANT[@]}"; do
  got=$(sha256sum "/tmp/$f" 2>/dev/null | cut -d' ' -f1)
  if [ "$got" != "${WANT[$f]}" ]; then
    printf "  ✗ %-22s 期望 %s 实得 %s\n" "$f" "${WANT[$f]:0:12}" "${got:0:12}"
    bad=1
  else
    printf "  ✓ %-22s %s\n" "$f" "${got:0:12}"
  fi
done
[ "$bad" = "1" ] && { echo "有文件不匹配，拒绝部署（重新 scp 或更新脚本内哈希）"; exit 1; }

echo "== 1) 备份到 $BK =="
mkdir -p "$BK" || fail "无法创建备份目录"
i=0
for rel in $PYFILES; do
  i=$((i+1)); flat=$(echo $FLAT | cut -d' ' -f$i)
  [ -f "$VENV/$rel" ] && cp -p "$VENV/$rel" "$BK/venv_$flat"
  [ -f "$SRC/$rel" ] && cp -p "$SRC/$rel" "$BK/cur_$flat"
done
for pair in $ADMINPAIRS; do
  flat=${pair%%:*}; rel=${pair#*:}
  [ -f "$VENV/$rel" ] && cp -p "$VENV/$rel" "$BK/venv_$flat"
  [ -f "$SRC/$rel" ] && cp -p "$SRC/$rel" "$BK/cur_$flat"
done
cp -p "$CUR/migrations/versions/"*.py "$BK/" 2>/dev/null || true
echo "  备份 $(ls -1 "$BK" | wc -l) 个文件"

echo "== 2) 落地迁移文件并迁移（core 仍跑旧代码；纯 ADD COLUMN 对旧代码无影响）=="
cp /tmp/mig_102.py "$CUR/migrations/versions/20261010_102_backfill_main_chain.py" || fail "迁移文件拷贝失败"
cp /tmp/mig_103.py "$CUR/migrations/versions/20261011_103_liar_dice_timeouts.py" || fail "迁移文件拷贝失败"
set -a; source /etc/dzmm/dzmm.env; set +a
cd "$CUR" || fail "无法进入 $CUR"
$AL upgrade head || fail "alembic upgrade head 失败（core 未停、代码未动）"
$AL current

echo "== 3) 落地源码（venv 与 checkout 两份）=="
COPIED=1
i=0
for rel in $PYFILES; do
  i=$((i+1)); flat=$(echo $FLAT | cut -d' ' -f$i)
  cp "/tmp/$flat" "$VENV/$rel" || fail "拷贝 $flat 到 venv 失败"
  cp "/tmp/$flat" "$SRC/$rel" || fail "拷贝 $flat 到 checkout 失败"
done
for pair in $ADMINPAIRS; do
  flat=${pair%%:*}; rel=${pair#*:}
  cp "/tmp/$flat" "$VENV/$rel" || fail "拷贝 $flat 到 venv 失败"
  cp "/tmp/$flat" "$SRC/$rel" || fail "拷贝 $flat 到 checkout 失败"
done

echo "== 4) 重启 core + 后台，等就绪后再拉起 worker =="
# 先停 worker 再重启 core：否则 worker 会在 core 重启窗口里 Connection refused 崩溃重启，
# 触发 "Start request repeated too quickly" 短暂进入 failed（实测每次约 5 秒）
systemctl stop $WORKERS 2>/dev/null || true
systemctl restart dzmm-core || fail "dzmm-core 重启失败"
wait_core || { journalctl -u dzmm-core -n 30 --no-pager; fail "core 未就绪"; }
systemctl restart dzmm-admin-web || fail "dzmm-admin-web 重启失败"
sleep 2
systemctl reset-failed $WORKERS 2>/dev/null || true
systemctl start $WORKERS 2>/dev/null || true
sleep 8

echo "== 5) 验收 =="
for u in dzmm-core dzmm-admin-web $WORKERS; do
  printf "  %-26s %s\n" "$u" "$(systemctl is-active $u)"
done
curl -sf --max-time 5 http://127.0.0.1:18120/healthz && echo "  core healthz OK"
$AL current
echo "== 6) 数据库确认 =="
/opt/dzmm/venv/bin/python - <<'PY'
import os, psycopg
url = os.environ["DZMM_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
with psycopg.connect(url) as c:
    print("  settings 列:", [r[0] for r in c.execute(
        "select column_name from information_schema.columns where table_name='liar_dice_settings'").fetchall()])
    print("  games 新列:", [r[0] for r in c.execute(
        "select column_name from information_schema.columns where table_name='liar_dice_games' "
        "and column_name in ('round_end_deadline','dealing_deadline')").fetchall()])
    print("  设置行:", c.execute(
        "select turn_seconds, enabled, min_players, signup_timeout_minutes, continue_timeout_minutes,"
        " deal_timeout_seconds from liar_dice_settings").fetchall())
PY
echo
echo "✅ 完成。备份：$BK"
echo "回滚（文件）：把 $BK/cur_* 拷回 $SRC/... 、$BK/venv_* 拷回 $VENV/... ，再 systemctl restart dzmm-core dzmm-admin-web"
echo "回滚（数据库）：cd $CUR && $AL downgrade -1"
