#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
    echo "Run as root after deploy/linux/bootstrap.sh and deploy/judge-linux/bootstrap.sh." >&2
    exit 1
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
APP_ENV=/etc/xinbaoyan/app.env
INFRA_ENV=/etc/xinbaoyan/infra.env
JUDGE_CONFIG_DIR=/etc/xinbaoyan-judge
JUDGE_ENV="$JUDGE_CONFIG_DIR/judge.env"
JUDGE_STATE_DIR=/var/lib/xinbaoyan-judge

for path in "$APP_ENV" "$INFRA_ENV" /opt/xinbaoyan/current/.venv/bin/python \
            /var/lib/xinbaoyan-judge/rootfs /usr/bin/isolate; do
    [[ -e $path ]] || { echo "Missing prerequisite: $path" >&2; exit 1; }
done

if ! id xinbaoyan-judge >/dev/null 2>&1; then
    useradd --system --home-dir "$JUDGE_STATE_DIR" --shell /usr/sbin/nologin xinbaoyan-judge
fi
install -d -m 750 -o root -g xinbaoyan-judge "$JUDGE_CONFIG_DIR"
install -d -m 750 -o xinbaoyan-judge -g xinbaoyan-judge \
    "$JUDGE_STATE_DIR/work" "$JUDGE_STATE_DIR/meta"

if [[ ! -e $JUDGE_ENV ]]; then
    APP_ENV="$APP_ENV" INFRA_ENV="$INFRA_ENV" JUDGE_ENV="$JUDGE_ENV" \
    TEMPLATE="$SCRIPT_DIR/judge.env.example" python3.12 - <<'PY'
import os
import shutil
from pathlib import Path


def load(path: str) -> dict[str, str]:
    values = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


app = load(os.environ["APP_ENV"])
infra = load(os.environ["INFRA_ENV"])
content = Path(os.environ["TEMPLATE"]).read_text(encoding="utf-8")
content = content.replace("CHANGE_ME_REDIS", infra["REDIS_PASSWORD"])
content = content.replace("CHANGE_ME_JUDGE_SECRET", app["JUDGE_RESULT_SECRET"])
path = Path(os.environ["JUDGE_ENV"])
path.write_text(content, encoding="utf-8")
path.chmod(0o640)
shutil.chown(path, user="root", group="xinbaoyan-judge")
PY
fi

install -m 700 -o root -g root "$SCRIPT_DIR/judge_watchdog.sh" /opt/xinbaoyan-judge-watchdog.sh
install -m 644 -o root -g root "$SCRIPT_DIR/xinbaoyan-judge-worker.service" /etc/systemd/system/
install -m 644 -o root -g root "$SCRIPT_DIR/xinbaoyan-judge-watchdog.service" /etc/systemd/system/
install -m 644 -o root -g root "$SCRIPT_DIR/xinbaoyan-judge-watchdog.timer" /etc/systemd/system/
systemctl daemon-reload

cat <<'EOF'
Linux judge services installed but intentionally not started.
Run the same-host acceptance suite first:
  cd /opt/xinbaoyan/current
  sudo -u xinbaoyan-judge bash -c 'set -a; source /etc/xinbaoyan-judge/judge.env; set +a; cd /opt/xinbaoyan/current; JUDGE_VM=1 .venv/bin/python -m pytest -m linux_judge_vm'
After acceptance:
  sudo systemctl enable --now xinbaoyan-judge-worker.service
  sudo systemctl enable --now xinbaoyan-judge-watchdog.timer
EOF
