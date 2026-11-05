#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
    echo "Run as root: sudo bash deploy/linux/configure.sh oj.example.com" >&2
    exit 1
fi
if [[ $# -ne 1 ]] || [[ ! $1 =~ ^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]]; then
    echo "Usage: $0 <public-domain>" >&2
    exit 1
fi

DOMAIN=$1
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
CONFIG_DIR=/etc/xinbaoyan
APP_ENV="$CONFIG_DIR/app.env"
INFRA_ENV="$CONFIG_DIR/infra.env"

if [[ -e $APP_ENV && -e $INFRA_ENV ]]; then
    echo "Existing configuration preserved: $CONFIG_DIR"
    exit 0
fi
if [[ -e $APP_ENV || -e $INFRA_ENV ]]; then
    echo "Only one environment file exists; inspect $CONFIG_DIR before continuing." >&2
    exit 1
fi

getent group xinbaoyan >/dev/null || { echo "Missing xinbaoyan group; run bootstrap.sh first." >&2; exit 1; }
install -d -m 750 -o root -g xinbaoyan "$CONFIG_DIR"

DOMAIN="$DOMAIN" SCRIPT_DIR="$SCRIPT_DIR" CONFIG_DIR="$CONFIG_DIR" python3 - <<'PY'
import os
import secrets
import shutil
from pathlib import Path

source = Path(os.environ["SCRIPT_DIR"])
target = Path(os.environ["CONFIG_DIR"])
domain = os.environ["DOMAIN"]
values = {
    "CHANGE_ME_SECRET": secrets.token_hex(32),
    "CHANGE_ME_JUDGE_SECRET": secrets.token_hex(32),
    "CHANGE_ME_MYSQL": secrets.token_hex(32),
    "CHANGE_ME_MYSQL_ROOT": secrets.token_hex(32),
    "CHANGE_ME_REDIS": secrets.token_hex(32),
    "__DOMAIN__": domain,
}
for template, destination in (("app.env.example", "app.env"), ("infra.env.example", "infra.env")):
    content = (source / template).read_text(encoding="utf-8")
    for marker in sorted(values, key=len, reverse=True):
        content = content.replace(marker, values[marker])
    path = target / destination
    path.write_text(content, encoding="utf-8")
    path.chmod(0o640)
    shutil.chown(path, user="root", group="xinbaoyan")
PY

echo "Random database, Redis and signing secrets generated in $CONFIG_DIR (values not printed)."
echo "Before deployment, edit $APP_ENV and replace every CHANGE_ME_SMTP* value."
