# Container deployment (Docker)

This directory is the source-controlled copy of the container assets that are
running in production. It replaces the old workflow where Dockerfiles, Compose
and Python patches lived only under `/opt/xinbaoyan-docker` on the server.

## Build from a clean checkout

```bash
git clone https://github.com/linchongfan/online-judge.git /opt/xinbaoyan-src
cd /opt/xinbaoyan-src
git checkout master   # or the release commit you verified

docker build -f deploy/docker/backend.Dockerfile  -t xinbaoyan-backend:local  .
docker build -f deploy/docker/frontend.Dockerfile -t xinbaoyan-frontend:local .
docker build -f deploy/docker/judge.Dockerfile    -t xinbaoyan-judge:local    .
```

The frontend image runs `bun run test` and `bun run build` during the build, so
a broken frontend cannot be published.

## Configure

Secrets are not in the repository. Copy the example and fill in real values:

```bash
install -d -m 750 /opt/xinbaoyan-docker /etc/xinbaoyan-judge
cp deploy/docker/app.container.env.example /opt/xinbaoyan-docker/app.container.env
# edit /opt/xinbaoyan-docker/app.container.env
```

`/etc/xinbaoyan/infra.env` (MySQL/Redis credentials for the backup job) and
`/etc/xinbaoyan-judge/judge.env` (judge runtime) follow the same pattern; see
`deploy/linux/` and `deploy/judge-linux/`.

## Run

```bash
docker compose -f deploy/docker/docker-compose.yml up -d
docker compose -f deploy/docker/docker-compose.yml --profile judge up -d
curl --fail http://127.0.0.1:8000/api/v1/health/ready
```

## No patch scripts

Older deployments ran `patch-backend-image.sh` / `patch-judge-image.sh` to
overwrite `app/tasks/consumer.py` and `judge/linux_isolate.py` inside the
images. Those fixes are now in the repository (stable outbox nonce, isolate
meta parsing, `--no-default-dirs`, cgroup cleanup, per-case scratch
directories). **Do not re-apply the old patches** — they would overwrite the
current implementation with an older revision.

## Judge sandbox notes

* The judge image builds the pinned IOI isolate v2.0 with a SHA-256 check.
* `docker-compose.yml` sets `JUDGE_LINUX_ROOTFS=/` and
  `JUDGE_DISABLE_DISK_QUOTA=1`: the box uses the container's private,
  `shm_size`-bounded tmpfs, and tmpfs does not implement quotactl. Keep
  `shm_size` as the hard disk ceiling.
* The judge container needs `cgroup: host`, the `SYS_ADMIN`/`SYS_CHROOT`
  capabilities and the `/sys/fs/cgroup/isolate` bind mount listed in the
  Compose file.

## Verify a deployment

```bash
# Four languages through the real API -> Celery -> Worker -> consumer path.
docker exec xinbaoyan-docker-api-1 python scripts/e2e_judge_acceptance.py \
  --base-url http://127.0.0.1:8000/api/v1 \
  --account <test-account> --password <test-password> --problem-id 1000

# Historical sample-flag audit (read-only; add --apply only after review).
docker exec xinbaoyan-docker-api-1 python scripts/audit_test_data_samples.py
```
