#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${EUID} -ne 0 ]]; then
    echo "Run as root: sudo LETSENCRYPT_EMAIL=admin@example.com bash deploy/linux/bootstrap.sh oj.example.com" >&2
    exit 1
fi
if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <public-domain-or-ip>" >&2
    exit 1
fi
: "${LETSENCRYPT_EMAIL:=unused@example.com}"

DOMAIN=$1
IS_IP=0
if [[ $DOMAIN =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    IS_IP=1
fi
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
BASE_DIR=/opt/xinbaoyan
INFRA_DIR="$BASE_DIR/infra"

source /etc/os-release
if [[ ${ID:-} != ubuntu ]]; then
    echo "This bootstrap supports Ubuntu only." >&2
    exit 1
fi
case ${VERSION_ID:-} in
    24.04)
        PYTHON_PKG="python3.12"
        PYTHON_VENV_PKG="python3.12-venv"
        ;;
    22.04)
        # Jammy ships Python 3.10; the project requires >=3.12,<3.13, so add the
        # deadsnakes PPA before installing Python 3.12.
        PYTHON_PKG="python3.12"
        PYTHON_VENV_PKG="python3.12-venv"
        if ! apt-cache show python3.12 >/dev/null 2>&1; then
            apt-get install -y software-properties-common
            add-apt-repository -y ppa:deadsnakes/ppa
            apt-get update
        fi
        ;;
    *)
        echo "This bootstrap supports Ubuntu 22.04 LTS and 24.04 LTS only (got ${PRETTY_NAME:-unknown})." >&2
        exit 1
        ;;
esac

export DEBIAN_FRONTEND=noninteractive
apt-get update

# docker.io conflicts with the Docker CE stack (containerd.io). When the
# Docker CE packages are already present, skip docker.io and only ensure the
# docker CLI / compose plugin requirements are met.
DOCKER_PKGS=(docker.io docker-compose-v2)
if dpkg -l containerd.io >/dev/null 2>&1 || dpkg -l docker-ce >/dev/null 2>&1; then
    DOCKER_PKGS=()
    echo "Docker CE packages detected; skipping docker.io to avoid containerd conflict."
fi

apt-get install -y \
    ca-certificates certbot curl default-mysql-client git gzip nginx nodejs npm openssl \
    "$PYTHON_PKG" "$PYTHON_VENV_PKG" redis-tools rsync tar util-linux \
    ${DOCKER_PKGS[@]+"${DOCKER_PKGS[@]}"}

if ! command -v bun >/dev/null 2>&1 || [[ $(bun --version) != 1.4.2 ]]; then
    npm install -g bun@1.4.2
fi

systemctl enable --now docker

if ! id xinbaoyan >/dev/null 2>&1; then
    useradd --system --home-dir "$BASE_DIR" --shell /usr/sbin/nologin xinbaoyan
fi
install -d -m 755 -o root -g root "$BASE_DIR" "$BASE_DIR/releases" "$INFRA_DIR"
install -d -m 750 -o xinbaoyan -g xinbaoyan /var/lib/xinbaoyan /var/lib/xinbaoyan/data
install -d -m 700 -o root -g root /var/backups/xinbaoyan

bash "$SCRIPT_DIR/configure.sh" "$DOMAIN"

install -m 644 -o root -g root "$SCRIPT_DIR/docker-compose.yml" "$INFRA_DIR/docker-compose.yml"
install -m 700 -o root -g root "$SCRIPT_DIR/backup.sh" "$INFRA_DIR/backup.sh"
for unit in xinbaoyan-api.service xinbaoyan-consumer.service xinbaoyan-maintenance.service \
            xinbaoyan-backup.service xinbaoyan-backup.timer; do
    install -m 644 -o root -g root "$SCRIPT_DIR/$unit" "/etc/systemd/system/$unit"
done
install -d -m 755 -o root -g root /etc/letsencrypt/renewal-hooks/deploy /var/www/certbot
install -m 700 -o root -g root "$SCRIPT_DIR/renewal-hook.sh" /etc/letsencrypt/renewal-hooks/deploy/xinbaoyan-nginx.sh

if [[ $IS_IP == 1 ]]; then
    # No trusted certificate authority issues certificates for bare IPs; run
    # plain HTTP on port 80 and skip certbot entirely.
    echo "IP-only deployment detected: skipping Let's Encrypt, using plain HTTP on port 80."
    sed "s/__DOMAIN__/$DOMAIN/g" "$SCRIPT_DIR/nginx-ip.conf" > /etc/nginx/sites-available/xinbaoyan.conf
    rm -f /etc/nginx/sites-enabled/xinbaoyan-acme.conf
else
    if [[ ! -s /etc/letsencrypt/live/$DOMAIN/fullchain.pem ]]; then
        sed "s/__DOMAIN__/$DOMAIN/g" "$SCRIPT_DIR/nginx-acme.conf" > /etc/nginx/sites-available/xinbaoyan-acme.conf
        ln -sfn /etc/nginx/sites-available/xinbaoyan-acme.conf /etc/nginx/sites-enabled/xinbaoyan-acme.conf
        nginx -t
        systemctl enable --now nginx
        systemctl restart nginx
        certbot certonly --webroot --webroot-path /var/www/certbot \
            --domain "$DOMAIN" --email "$LETSENCRYPT_EMAIL" \
            --agree-tos --non-interactive --keep-until-expiring
        unlink /etc/nginx/sites-enabled/xinbaoyan-acme.conf
    fi
    sed "s/__DOMAIN__/$DOMAIN/g" "$SCRIPT_DIR/nginx.conf" > /etc/nginx/sites-available/xinbaoyan.conf
fi
ln -sfn /etc/nginx/sites-available/xinbaoyan.conf /etc/nginx/sites-enabled/xinbaoyan.conf
nginx -t
systemctl enable --now nginx
systemctl restart nginx
systemctl daemon-reload
if [[ $IS_IP == 0 ]]; then
    systemctl enable --now certbot.timer
fi

cat <<EOF
Bootstrap complete.
1. Edit /etc/xinbaoyan/app.env and replace all CHANGE_ME_SMTP* placeholders.
2. Run: sudo bash $SCRIPT_DIR/deploy.sh
3. For same-host judging, follow deploy/judge-linux/ before enabling the judge worker.
EOF
