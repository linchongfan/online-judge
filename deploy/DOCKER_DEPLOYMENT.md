# Docker 容器化部署（当前生产方案）

本文描述本项目在线上的实际运行方式：前端、后端、结果消费者、维护进程、备份与判题 Worker 全部以容器运行，MySQL 与 Redis 复用服务器上已有的 1Panel 实例。

> 部署资产位于服务器 `/opt/xinbaoyan-docker/`（`backend.Dockerfile`、`frontend.Dockerfile`、`judge.Dockerfile`、`docker-compose.yml`、`nginx.conf`、`patch-judge-image.sh`），以 `/opt/xinbaoyan-src` 作为构建上下文。仓库里保留 `deploy/linux/` 的 systemd 方案作为可选替代路径。

## 1. 运行拓扑

```text
公网 9898
   │
   ▼
frontend 容器（Nginx：静态站 + /api 反代）
   │ 127.0.0.1:8000
   ▼
api 容器（FastAPI，2 workers）──────► MySQL 8.4.13（1Panel 容器）
   │                              └► Redis 8.10.3（1Panel 容器，db0 结果队列 / db1 Celery）
   ├── result-consumer 容器（单实例）
   ├── maintenance 容器（单实例，Outbox + 租约巡检）
   ├── backup 容器（每日 mysqldump + 数据目录打包）
   └── judge-worker 容器（isolate + cgroup v2 + namespace + 临时 rootfs）
```

所有长期服务使用 `network_mode: host`，因此容器直接访问 `127.0.0.1` 上的 MySQL/Redis，与原有 1Panel 端口配置一致；对公网只暴露前端端口。

| 服务 | 镜像 | 对外端口 | 说明 |
| --- | --- | --- | --- |
| frontend | `xinbaoyan-frontend:local` | `9898` | Nginx + 构建产物，`/api/` 反代到 8000 |
| api | `xinbaoyan-backend:local` | 仅本机 8000 | FastAPI，健康检查 `/api/v1/health/ready` |
| result-consumer | `xinbaoyan-backend:local` | — | 判题结果消费者，必须单实例 |
| maintenance | `xinbaoyan-backend:local` | — | Outbox 重投与超期任务巡检，必须单实例 |
| backup | `xinbaoyan-backend:local` | — | 每日备份到 `/var/backups/xinbaoyan` |
| judge-worker | `xinbaoyan-judge:local` | — | isolate 沙箱，`--profile judge` 启动 |

## 2. 依赖的宿主机配置

1. **MySQL / Redis**：1Panel 已运行的 `mysql:8.4.13`、`redis:8.10.3`，监听本机端口；数据库 `xinbaoyan` 与账号 `oj` 需提前创建。
2. **配置目录**：`/etc/xinbaoyan/app.container.env`（业务容器用）、`/etc/xinbaoyan/infra.env`、`/etc/xinbaoyan-judge/judge.env`，权限 600/640，均不进镜像。
3. **持久化目录**：`/var/lib/xinbaoyan/data`（测试数据）、`/var/backups/xinbaoyan`（备份）、`/var/lib/xinbaoyan-judge/{work,meta,isolate}`。
4. **cgroup v2**：判题容器需要 `cgroup: host`、`/sys/fs/cgroup/isolate` 读写挂载，并预先启用 `cpu memory pids io` 控制器：

```bash
echo "+cpu +memory +pids +io" > /sys/fs/cgroup/cgroup.subtree_control
mkdir -p /sys/fs/cgroup/isolate
echo "+cpu +memory +pids +io" > /sys/fs/cgroup/isolate/cgroup.subtree_control
```

5. **判题镜像权限**：容器以 root 启动（isolate 需要 setuid root 才能建立命名空间并降权），并授予 `SYS_ADMIN, SYS_CHROOT, SETUID, SETGID, SYS_RESOURCE, CHOWN, DAC_OVERRIDE, FOWNER, KILL, NET_ADMIN`；不挂载 Docker Socket，不使用 `privileged`。用户代码仍在独立低权 UID、cgroup 与 network namespace 中执行。

## 3. 日常命令

```bash
cd /opt/xinbaoyan-docker

# 业务栈
docker compose up -d

# 含判题 Worker
docker compose --profile judge up -d

# 状态 / 日志
docker compose ps
docker logs --tail 100 xinbaoyan-docker-api-1
docker logs --tail 100 xinbaoyan-docker-judge-worker-1

# 健康检查
curl -sS http://127.0.0.1:9898/api/v1/health/ready
```

## 4. 发布新版本

```bash
cd /opt/xinbaoyan-src && git pull --ff-only
cd /opt/xinbaoyan-docker

# 后端（api / consumer / maintenance / backup 共用）
docker build -f backend.Dockerfile -t xinbaoyan-backend:local /opt/xinbaoyan-src
# 若修改了 app/tasks/consumer.py，需重新应用兼容补丁
./patch-backend-image.sh
docker compose up -d --force-recreate api result-consumer maintenance backup

# 前端
docker build -f frontend.Dockerfile -t xinbaoyan-frontend:local /opt/xinbaoyan-src
docker compose up -d --force-recreate frontend

# 判题镜像：重建后必须重新打补丁
docker build -f judge.Dockerfile -t xinbaoyan-judge:local /opt/xinbaoyan-src
./patch-judge-image.sh
docker compose --profile judge up -d --force-recreate judge-worker
```

数据库迁移与默认账号由一次性任务完成：

```bash
docker compose run --rm migrate
```

## 5. 服务器侧判题补丁

项目自带的 `judge/linux_isolate.py` 与 isolate 2.0 的实际行为存在差异，线上通过 `patch-judge-image.sh` 注入修正副本（同时写入 `/app/judge` 与虚拟环境 `site-packages`）：

- 移除 isolate 不支持的 `--quota` 与 `--dir=:ro` 参数；
- stdin/stdout/stderr 放入 `/box`，并等待 isolate 创建后再读取；
- 每次运行前清理上一阶段残留的重定向文件；
- 任务目录 chown 给 box UID（无权限时退化为 0777）；
- 解析 isolate 的 `key: value` 元数据，正确映射 TLE/MLE/RE；
- 清理前放宽 box 生成文件权限，避免删除失败；
- 每次初始化前清理残留 cgroup，避免 `Device or resource busy`；
- 挂载只读 `/etc`，让 JDK 能读取 `java.security`；
- 内存优先取 cgroup `memory.peak`，内核 < 5.19 时回退到 isolate `max-rss`。

同类兼容补丁也用于 `app/tasks/consumer.py`：新版 redis-py 的 `BRPOPLPUSH` 直接返回 bytes，而原代码按元组取 `item[1]`，会导致结果堆积在队列、提交长期 PENDING。

## 6. 备份与恢复

`backup` 容器每天执行 `deploy/linux/backup.sh`，产物位于 `/var/backups/xinbaoyan/<UTC 时间戳>/`：

- `mysql.sql.gz`：`mysqldump --single-transaction` 导出；
- `storage.tar.gz`：`/var/lib/xinbaoyan/data`；
- `SHA256SUMS`。

恢复时先停止对外服务，导入 SQL、还原数据目录，再启动容器并核对测试数据版本与哈希。Redis 只承载队列，不作为成绩唯一来源。

## 7. 回滚

```bash
cd /opt/xinbaoyan-docker
docker compose --profile judge down
systemctl enable --now nginx    # 恢复宿主机 Nginx + systemd 方案
```

宿主机 systemd 单元与旧 Nginx 配置保持未修改，可随时切回；代码侧回滚使用镜像标签，例如部署前先 `docker tag xinbaoyan-frontend:local xinbaoyan-frontend:previous`。

## 8. 已知限制

- 前端当前为明文 HTTP（纯 IP 部署，无受信任证书）；配置域名后应切回 HTTPS 方案。
- `judge-worker` 容器以 root 启动，这是 isolate 的要求；用户代码依然降权运行。
- 判题并发为 1（solo pool），提高并发前需重新评估整机资源与计时稳定性。
- 服务器侧补丁属于过渡方案，上游修复后应移除。
