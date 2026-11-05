#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
    echo "Run as root: sudo bash deploy/linux/backup.sh" >&2
    exit 1
fi

INFRA_ENV=/etc/xinbaoyan/infra.env
INFRA_DIR=/opt/xinbaoyan/infra
BACKUP_ROOT=${BACKUP_ROOT:-/var/backups/xinbaoyan}
RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-14}
TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)

[[ -r $INFRA_ENV ]] || { echo "Missing $INFRA_ENV" >&2; exit 1; }
set -a
source "$INFRA_ENV"
set +a
: "${MYSQL_DATABASE:?}" "${MYSQL_ROOT_PASSWORD:?}"

install -d -m 700 "$BACKUP_ROOT"
exec 9>"$BACKUP_ROOT/.backup.lock"
flock -n 9 || { echo "Another backup is already running." >&2; exit 1; }

TEMP_DIR=$(mktemp -d "$BACKUP_ROOT/.tmp.$TIMESTAMP.XXXXXX")
FINAL_DIR="$BACKUP_ROOT/$TIMESTAMP"
cleanup() { rm -rf -- "$TEMP_DIR"; }
trap cleanup EXIT

COMPOSE=(docker compose --env-file "$INFRA_ENV" -f "$INFRA_DIR/docker-compose.yml")

if [[ ${INFRA_MODE:-external} == external ]]; then
    MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump --host=127.0.0.1 --port=3306 --protocol=TCP \
        -uroot --single-transaction --quick --routines --triggers --events \
        --set-gtid-purged=OFF --databases "$MYSQL_DATABASE" | gzip -9 > "$TEMP_DIR/mysql.sql.gz"
else
    "${COMPOSE[@]}" exec -T -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql \
        mysqldump -uroot --single-transaction --quick --routines --triggers --events \
        --set-gtid-purged=OFF --databases "$MYSQL_DATABASE" | gzip -9 > "$TEMP_DIR/mysql.sql.gz"
fi

tar -C /var/lib/xinbaoyan -czf "$TEMP_DIR/storage.tar.gz" data
(
    cd "$TEMP_DIR"
    sha256sum mysql.sql.gz storage.tar.gz > SHA256SUMS
)
chmod 600 "$TEMP_DIR"/*
mv "$TEMP_DIR" "$FINAL_DIR"
trap - EXIT

find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -name '20*' \
    -mtime "+$RETENTION_DAYS" -exec rm -rf -- {} +

echo "Backup complete: $FINAL_DIR"
