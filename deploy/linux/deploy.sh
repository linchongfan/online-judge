#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
    echo "Run as root: sudo bash deploy/linux/deploy.sh" >&2
    exit 1
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd -- "$SCRIPT_DIR/../.." && pwd)
BASE_DIR=/opt/xinbaoyan
INFRA_DIR="$BASE_DIR/infra"
APP_ENV=/etc/xinbaoyan/app.env
INFRA_ENV=/etc/xinbaoyan/infra.env
RUN_TESTS=${RUN_TESTS:-1}

for command in python3.12 bun docker rsync curl systemctl; do
    command -v "$command" >/dev/null || { echo "Missing command: $command; run bootstrap.sh first." >&2; exit 1; }
done
[[ -r $APP_ENV && -r $INFRA_ENV ]] || { echo "Missing environment files; run bootstrap.sh first." >&2; exit 1; }
if grep -q 'CHANGE_ME' "$APP_ENV" "$INFRA_ENV"; then
    echo "Replace all CHANGE_ME placeholders before deployment." >&2
    exit 1
fi

set -a
source "$INFRA_ENV"
set +a
: "${MYSQL_DATABASE:?}" "${MYSQL_USER:?}" "${MYSQL_PASSWORD:?}" "${MYSQL_ROOT_PASSWORD:?}" "${REDIS_PASSWORD:?}"

COMPOSE=(docker compose --env-file "$INFRA_ENV" -f "$INFRA_DIR/docker-compose.yml")
INFRA_MODE=${INFRA_MODE:-external}
if [[ $INFRA_MODE != external && $INFRA_MODE != compose ]]; then
    echo "INFRA_MODE must be 'external' or 'compose'." >&2
    exit 1
fi

mysql_ready() {
    if [[ $INFRA_MODE == external ]]; then
        MYSQL_PWD="$MYSQL_PASSWORD" mysql --host=127.0.0.1 --port=3306 --protocol=TCP \
            --user="$MYSQL_USER" --execute="SELECT 1" "$MYSQL_DATABASE" >/dev/null 2>&1
    else
        "${COMPOSE[@]}" exec -T -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql \
            mysqladmin ping -h 127.0.0.1 -uroot --silent >/dev/null 2>&1
    fi
}

redis_ready() {
    if [[ $INFRA_MODE == external ]]; then
        [[ $(redis-cli -h 127.0.0.1 -p 6379 -a "$REDIS_PASSWORD" --no-auth-warning ping 2>/dev/null) == PONG ]]
    else
        [[ $("${COMPOSE[@]}" exec -T redis redis-cli -a "$REDIS_PASSWORD" ping 2>/dev/null) == PONG ]]
    fi
}

if [[ $INFRA_MODE == compose ]]; then
    "${COMPOSE[@]}" up -d
fi

for attempt in $(seq 1 60); do
    if mysql_ready && redis_ready; then
        break
    fi
    if [[ $attempt -eq 60 ]]; then
        echo "MySQL or Redis did not become healthy." >&2
        if [[ $INFRA_MODE == compose ]]; then
            "${COMPOSE[@]}" ps
        fi
        exit 1
    fi
    sleep 2
done

RELEASE_ID=$(date -u +%Y%m%dT%H%M%SZ)-$$
RELEASE_DIR="$BASE_DIR/releases/$RELEASE_ID"
PREVIOUS_RELEASE=$(readlink -f "$BASE_DIR/current" 2>/dev/null || true)
install -d -m 755 "$RELEASE_DIR"

rsync -a --delete \
    --exclude=.git --exclude=.env --exclude=.venv --exclude=node_modules --exclude=dist \
    --exclude=data --exclude=logs --exclude=tools --exclude=bgimg --exclude=gui-test-screenshots \
    --exclude=.mypy_cache --exclude=.pytest_cache --exclude=.ruff_cache --exclude=__pycache__ \
    --exclude='*.pyc' --exclude=tsconfig.tsbuildinfo \
    "$PROJECT_ROOT/" "$RELEASE_DIR/"

cd "$RELEASE_DIR"
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
if [[ $RUN_TESTS == 1 ]]; then
    .venv/bin/python -m pip install '.[dev]'
else
    .venv/bin/python -m pip install .
fi

bun install --frozen-lockfile
if [[ $RUN_TESTS == 1 ]]; then
    # Tests intentionally run without production app.env: API tests use isolated SQLite
    # and must never clear rate-limit keys in the production Redis instance.
    env -u APP_ENV -u DATABASE_URL -u REDIS_URL .venv/bin/python -m pytest
    bun run test
fi
bun run build

# Validate production settings in a subshell; test commands above never inherit them.
(
    set -a
    source "$APP_ENV"
    set +a
    .venv/bin/python -c 'from app.core.config import get_settings; get_settings()'
)

# Back up before every schema migration. A failed backup stops the release.
"$INFRA_DIR/backup.sh"
(
    set -a
    source "$APP_ENV"
    set +a
    .venv/bin/python -m alembic upgrade head
    # Create the two announced default accounts once (idempotent).
    # Disable with CREATE_DEFAULT_USERS=0.
    if [[ ${CREATE_DEFAULT_USERS:-1} == 1 ]]; then
        .venv/bin/python scripts/ensure_default_users.py
    fi
)

activate_release() {
    local target=$1
    ln -sfn "$target" "$BASE_DIR/current.next"
    mv -Tf "$BASE_DIR/current.next" "$BASE_DIR/current"
    systemctl restart xinbaoyan-api.service xinbaoyan-consumer.service xinbaoyan-maintenance.service
}

systemctl enable xinbaoyan-api.service xinbaoyan-consumer.service xinbaoyan-maintenance.service
activate_release "$RELEASE_DIR"

healthy=false
for attempt in $(seq 1 30); do
    if curl --fail --silent --show-error --max-time 3 http://127.0.0.1:8000/api/v1/health/ready >/dev/null \
        && systemctl is-active --quiet xinbaoyan-consumer.service \
        && systemctl is-active --quiet xinbaoyan-maintenance.service; then
        healthy=true
        break
    fi
    sleep 2
done

if [[ $healthy != true ]]; then
    echo "Release health check failed; inspect journalctl -u xinbaoyan-api.service." >&2
    if [[ -n $PREVIOUS_RELEASE && -d $PREVIOUS_RELEASE ]]; then
        echo "Switching application code back to $PREVIOUS_RELEASE; database migrations are not reversed." >&2
        activate_release "$PREVIOUS_RELEASE"
    fi
    exit 1
fi

systemctl enable --now xinbaoyan-backup.timer
nginx -t
systemctl reload nginx
PUBLIC_ORIGIN=$(grep -E '^CORS_ORIGINS=' "$APP_ENV" | cut -d= -f2- | cut -d, -f1)

cat <<EOF
Deployment successful: $RELEASE_DIR
Previous release: ${PREVIOUS_RELEASE:-none}
Public health check: ${PUBLIC_ORIGIN}/api/v1/health/ready
Keep at least one known-good release; database rollback requires a reviewed, compatible migration or restore plan.
EOF
