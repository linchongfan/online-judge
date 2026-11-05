# Linux 单机自动化部署方案

本文给出可直接执行的 Ubuntu 24.04 LTS **单机部署流程**，配套脚本位于 [`deploy/linux/`](./linux/) 与 [`deploy/judge-linux/`](./judge-linux/)。前端、业务后端、判题沙箱、MySQL 和 Redis 均部署在同一台服务器。

> **端口与版本**：前端 Nginx 使用公网 `80/443`；FastAPI 后端仅监听 `127.0.0.1:8000`；MySQL 固定为 `8.4.13`，Redis 固定为 `8.10.3`。MySQL、Redis 和后端端口均不对公网开放。
>
> **判题边界**：Linux isolate 沙箱与后端同机，但用户代码仍在独立 namespace、cgroup、低权 UID 和只读 rootfs 中执行。`local` 仅用于无害开发测试，生产策略会拒绝它。普通 Docker 或 `subprocess` 不能当作生产判题沙箱。沙箱验收全部通过前，不启动生产判题 Worker。

## 1. 单机架构与发布策略

```text
同一台 Linux 服务器
┌─────────────────────────────────────────────────────────────┐
│ 公网 80/443                                                   │
│ Nginx ───────────────────────► Vue 静态文件（current/dist）    │
│   │ /api/                                                   │
│   ▼                                                         │
│ FastAPI 后端：127.0.0.1:8000（systemd，2 workers）             │
│   ├── MySQL 8.4.13：127.0.0.1:3306                            │
│   ├── Redis 8.10.3：127.0.0.1:6379                            │
│   ├── 判题结果消费者（systemd，单实例）                         │
│   └── Outbox/租约维护进程（systemd，单实例）                    │
│                                                             │
│ 判题 Worker（独立低权账号，使用本机 Redis 和 127.0.0.1 心跳）    │
│   └── isolate + cgroup v2 + namespace + 最小只读 rootfs        │
│       └── 用户代码：独立 UID、禁网、资源硬限制、任务后清理        │
└─────────────────────────────────────────────────────────────┘
```

公网只需要开放 `80/443`；`8000/3306/6379` 均由本机服务使用。虽然沙箱与后端同机，判题 Worker 仍不持有 MySQL、SMTP 或 Web `SECRET_KEY`，用户代码不能继承 Worker 的 Redis 凭据。单机部署会扩大沙箱缺陷对整机的影响，因此 cgroup、namespace、rootfs、禁网和看门狗任何一项未通过验收，都不能开放公开提交。

发布采用不可变版本目录：

- `/opt/xinbaoyan/releases/<时间戳>`：每次发布的源码、虚拟环境和前端构建产物。
- `/opt/xinbaoyan/current`：指向当前版本的符号链接。
- `/var/lib/xinbaoyan/data`：测试数据等持久化文件，不随版本切换删除。
- `/etc/xinbaoyan/app.env`：业务配置与密钥。
- `/etc/xinbaoyan/infra.env`：MySQL、Redis 和私网监听配置。
- `/var/backups/xinbaoyan`：本地备份；生产还应复制到异地。
- systemd journal：应用日志，不依赖 release 内可写目录。

消费者和维护进程都按**单实例**部署。不要通过 `systemctl` 模板或多机直接增加它们的副本，除非先验证消费恢复、Outbox 重投和租约巡检的并发语义。

## 2. 资源与前置条件

### 2.1 建议资源

| 项目 | 最低验证配置 | 小规模生产建议 |
| --- | --- | --- |
| Linux 单机（业务 + 判题） | 4 vCPU、8 GB 内存、80 GB SSD | 8 vCPU、16 GB 内存、160 GB SSD |
| 备份 | 本地剩余空间可保留 14 天 | 异地副本、定期恢复演练 |

所有组件同机只适用于小规模首版。判题编译和 Java/Python 运行时会与 Web、MySQL 争用资源，应通过 Worker 并发、cgroup 和系统资源预留限制影响；负载增长后优先拆分判题节点或数据库。

### 2.2 上线前检查

1. 一台全新或已备份的 **Ubuntu 24.04 LTS x86_64** 主机；脚本会检查系统版本。
2. 域名 `oj.example.com` 的 A/AAAA 记录已指向业务机，且 80、443 可达。
3. 准备证书注册邮箱、生产 SMTP 参数和管理员账号信息。
4. SSH 仅对受控来源开放；云安全组默认拒绝其他入站。
5. 源码通过 Git 从 GitHub 克隆到服务器 `/opt/xinbaoyan-src`（公开仓库可直接克隆；私有仓库需先在服务器配置 SSH 密钥或访问令牌）。
6. 首次 bootstrap 需要访问 GitHub、Ubuntu 软件源、npm、Docker Hub（仅 compose 模式）和 Let's Encrypt。受限网络应预先准备镜像与代理。

## 3. 从 GitHub 获取并首次发布

以下命令在服务器上以 root 或 sudo 执行：

```bash
# 1. 克隆代码（公开仓库无需认证）
sudo apt-get update && sudo apt-get install -y git
sudo git clone https://github.com/linchongfan/online-judge.git /opt/xinbaoyan-src
cd /opt/xinbaoyan-src

# 2. 安装系统依赖、创建低权账号和目录、生成随机密钥、申请证书、安装 systemd/Nginx 配置。
sudo LETSENCRYPT_EMAIL=ops@example.com \
  bash deploy/linux/bootstrap.sh oj.example.com

# 3. bootstrap 不回显密钥。设置 SMTP 和现有基础设施的真实凭据。
sudoedit /etc/xinbaoyan/app.env
sudoedit /etc/xinbaoyan/infra.env
```

图中 1Panel 已运行 MySQL `8.4.13` 和 Redis `8.10.3` 时，保持 `/etc/xinbaoyan/infra.env` 的 `INFRA_MODE=external`，不会再创建第二套容器。先在 1Panel 创建数据库 `xinbaoyan`、仅拥有该库权限的账号 `oj`，并确认 Redis 已设置密码。然后：

- 将 `infra.env` 的 `MYSQL_PASSWORD`、`MYSQL_ROOT_PASSWORD`、`REDIS_PASSWORD` 设置为服务器现有实例的真实凭据。
- 将 `app.env` 的 `DATABASE_URL`、`REDIS_URL`、`CELERY_BROKER_URL`、`CELERY_RESULT_BACKEND` 同步为相同账号和密码。
- 只有全新服务器且没有现有数据库/Redis 时，才设置 `INFRA_MODE=compose`，由项目 Compose 创建相同版本实例。

外部模式会执行真实 `SELECT 1` 与 Redis `PING` 检查；备份使用本机 `mysqldump`，不依赖 1Panel 容器名称。

发布完成并通过健康检查后，`deploy.sh` 会自动创建两个初始账号（幂等，已存在则跳过）：

| 角色 | 账号 | 密码 |
| --- | --- | --- |
| 管理员 | `admin@123321` | `admin@123321` |
| 测试用户 | `test@123456` | `test@123456` |

用户名规则已支持 `@`。首次登录后请立即修改密码；禁用自动创建可用 `sudo CREATE_DEFAULT_USERS=0 bash deploy/linux/deploy.sh`，覆盖默认值可在部署前设置 `DEFAULT_ADMIN_USERNAME`、`DEFAULT_ADMIN_PASSWORD`、`DEFAULT_ADMIN_EMAIL`、`DEFAULT_TEST_*` 环境变量。

```bash
# 构建、测试、连接现有基础设施、备份、迁移、发布并健康检查。
sudo bash deploy/linux/deploy.sh

curl --fail https://oj.example.com/api/v1/health/ready
```

`app.env` 中必须替换：

```dotenv
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_FROM=noreply@oj.example.com
SMTP_USERNAME=your-smtp-user
SMTP_PASSWORD=your-smtp-password
SMTP_USE_TLS=true
```

当前邮件实现使用 SMTP STARTTLS，推荐 587 端口；不要直接把 465 隐式 TLS 配置当作已支持能力。含空格、`#`、引号或 shell 特殊字符的手工配置值必须同时满足 systemd EnvironmentFile 与 shell 的引用规则。脚本生成的数据库和 Redis 密码为 64 位十六进制字符串，可避免 URL 转义问题。

创建首个生产管理员（不要执行 `scripts/seed.py`）：

```bash
sudo -u xinbaoyan bash -c '
  cd /opt/xinbaoyan/current
  set -a
  source /etc/xinbaoyan/app.env
  set +a
  .venv/bin/python scripts/create_admin.py <username> <email>
'
```

命令会交互读取密码。不要在命令行、CI 日志或 shell 历史中传管理员密码，也不要沿用 `Admin12345`。

## 4. 自动化脚本做什么

| 文件 | 职责 |
| --- | --- |
| `bootstrap.sh` | 安装固定 Bun 版本与系统依赖，创建账号/目录，调用配置生成，申请证书，安装 Nginx 和 systemd 单元 |
| `configure.sh` | 首次生成 MySQL、Redis、Web 和判题结果的独立随机密钥；已有配置不覆盖 |
| `deploy.sh` | 连接服务器现有 MySQL/Redis（external），或启动同版本 Compose 实例（compose）；构建 release、测试、备份、迁移和健康检查 |
| `backup.sh` | 使用本机 `mysqldump --single-transaction` 和 tar 备份，生成 SHA-256，保留默认 14 天 |
| `docker-compose.yml` | 仅在 `INFRA_MODE=compose` 时创建 MySQL 8.4.13 与 Redis 8.10.3，只监听 `127.0.0.1` |
| `judge-linux/` | 同机 isolate 工具链、rootfs、Worker、看门狗与验收资产 |
| `xinbaoyan-*.service` | API、消费者、维护进程与备份服务；应用使用低权用户和 systemd 文件系统限制 |
| `nginx.conf` | HTTPS、HTTP 跳转、同源 API 代理、安全响应头、请求体和基础频率限制 |

发布脚本的关键行为：

1. 任意 `CHANGE_ME` 占位符仍存在时拒绝上线。
2. MySQL、Redis 未通过实际连接检查时不继续。
3. 默认运行 Python 与前端测试，再构建前端。测试不会加载生产 `app.env`，避免清理生产 Redis 限流键。
4. 迁移前备份失败会停止发布。
5. Alembic 只在新 release 中执行一次 `upgrade head`，不在每个 Web 进程启动时建表。
6. 切换 `current` 后重启三个应用服务，检查 `/api/v1/health/ready`。
7. 健康检查失败且存在旧版本时自动回切应用代码；**不会自动执行数据库降级**。
8. 成功后启用每日 03:30（带随机延迟）的本地备份定时器。

如测试已在可信 CI 中针对同一提交全部通过，可跳过服务器重复测试：

```bash
sudo RUN_TESTS=0 bash deploy/linux/deploy.sh
```

不要把跳过测试作为日常默认，也不要在未构建相同提交的情况下复用该选项。

## 5. 日常更新与版本回切

### 5.1 更新

在 GitHub 上推送新提交后，在服务器上拉取并重新发布：

```bash
cd /opt/xinbaoyan-src
sudo git pull --ff-only
sudo bash deploy/linux/deploy.sh
```

注意：

- 用 `--ff-only` 防止服务器上产生合并提交；若拉取被拒绝，说明服务器上的文件被改动过，先核对差异再处理，不要强行合并。
- 不要修改 `/opt/xinbaoyan-src` 里的受版本控制文件来做服务器本地定制；环境差异一律通过 `/etc/xinbaoyan/`、`/etc/xinbaoyan-judge/` 下的配置表达，否则下次 `git pull` 会冲突。
- 仓库若为私有，服务器克隆需先配置凭据，例如 SSH 部署密钥（推荐，只读权限）：

```bash
ssh-keygen -t ed25519 -f ~/.ssh/github_deploy -N ""
cat ~/.ssh/github_deploy.pub   # 添加到 GitHub 仓库 Settings → Deploy keys（勾选 read-only）
git config --global core.sshCommand "ssh -i ~/.ssh/github_deploy"
sudo git clone git@github.com:linchongfan/online-judge.git /opt/xinbaoyan-src
```

查看当前版本与服务：

```bash
readlink -f /opt/xinbaoyan/current
systemctl status xinbaoyan-api.service xinbaoyan-consumer.service xinbaoyan-maintenance.service
curl --fail http://127.0.0.1:8000/api/v1/health/ready
```

至少保留一个已知良好 release。清理旧版本前先确认它不是 `current`、不是回滚目标，并确认旧虚拟环境不再被任何进程使用。

### 5.2 应用回切

先确认目标 release 的代码与当前数据库结构兼容：

```bash
sudo bash -c '
  target=/opt/xinbaoyan/releases/<已知良好版本>
  test -d "$target"
  ln -sfn "$target" /opt/xinbaoyan/current.rollback
  mv -Tf /opt/xinbaoyan/current.rollback /opt/xinbaoyan/current
  systemctl restart xinbaoyan-api.service xinbaoyan-consumer.service xinbaoyan-maintenance.service
'
curl --fail http://127.0.0.1:8000/api/v1/health/ready
```

数据库不能靠切换目录回滚。若新迁移不兼容旧代码，应停止发布并使用经过评审的前向修复迁移，或在维护窗口执行完整恢复。不要自动运行 `alembic downgrade` 处理失败发布。

## 6. 同机部署 Linux 判题沙箱

判题 Worker 与 FastAPI 使用同一份 `/opt/xinbaoyan/current` 发布代码，但使用独立的 `xinbaoyan-judge` 账号、配置和状态目录。业务 Redis 与结果队列仍使用 0 号库，Celery 使用 1 号库；队列地址均为 `127.0.0.1`，不需要 WireGuard。

### 6.1 安装工具链与 rootfs

完成第 3 节业务发布后，在同一台服务器执行：

```bash
cd /opt/xinbaoyan-src
sudo bash deploy/judge-linux/bootstrap.sh --yes
sudo bash deploy/judge-linux/build-rootfs.sh --yes
sudo bash deploy/judge-linux/install-services.sh
```

`bootstrap.sh` 安装 GCC 13、OpenJDK 17、Python 3.12 和固定版本 isolate；`build-rootfs.sh` 生成最小 rootfs 与 SHA-256 清单；`install-services.sh` 创建低权账号，从业务配置派生**仅限判题所需**的 Redis 和签名配置，并安装 Worker/看门狗。判题配置位于 `/etc/xinbaoyan-judge/judge.env`，不包含 MySQL、SMTP 或 Web `SECRET_KEY`。

安装脚本不会自动启动 Worker。isolate 使用 setuid/cgroup/namespace 能力，不要给 Worker 通用 sudo，也不要把业务 API 的 systemd 限制配置原样复制到判题 Worker。

### 6.2 验收后启动

```bash
cd /opt/xinbaoyan/current
sudo -u xinbaoyan-judge bash -c '
  set -a
  source /etc/xinbaoyan-judge/judge.env
  set +a
  cd /opt/xinbaoyan/current
  JUDGE_VM=1 .venv/bin/python -m pytest -m linux_judge_vm
'

sudo systemctl enable --now xinbaoyan-judge-worker.service
sudo systemctl enable --now xinbaoyan-judge-watchdog.timer
```

验收覆盖 AC/TLE/MLE、硬输出限制、禁网、宿主文件不可见与多任务清理。还应完成四语言兼容性、进程树强杀恢复、死信/租约恢复和受控重建演练。任一隔离能力未通过都不得开放真实用户提交。`JUDGE_ALLOW_UNSAFE_TESTS=1` 不能出现在生产判题配置中。

### 6.3 同机资源与安全边界

- 用户程序只有独立低权 UID、任务目录和只读 rootfs，不继承 Worker 的 Redis 密钥。
- 沙箱默认没有主机网络；宿主机防火墙还应阻止判题 UID 访问本机 `3306/6379/8000` 和云元数据地址。
- Worker 以本机 `127.0.0.1:6379` 获取任务，并通过 `127.0.0.1:8000` 发送签名心跳；该权限仅属于 Worker，不属于用户程序。
- 首版 Worker 并发保持 1。调整并发前必须验证整机 CPU/内存预留、判题计时稳定性与数据库/Web 可用性。

## 7. 备份与恢复

### 7.1 备份检查

```bash
systemctl list-timers xinbaoyan-backup.timer
sudo systemctl start xinbaoyan-backup.service
sudo journalctl -u xinbaoyan-backup.service -n 50
ls -l /var/backups/xinbaoyan/<备份时间>
```

每份备份包含 `mysql.sql.gz`、`storage.tar.gz` 和 `SHA256SUMS`。默认本地保留 14 天，可在备份服务环境中调整 `BACKUP_RETENTION_DAYS`。应通过受控备份系统复制到异地，本地目录不等于完整灾难恢复方案。

数据库与文件备份不是跨系统原子快照。严格一致性要求下，应在维护窗口暂停上传和发布操作后再备份；恢复后必须核对测试数据版本与 SHA-256。

### 7.2 恢复演练

在隔离环境或批准维护窗口中，先停止公开提交、判题 Worker 接单和三个业务服务，再校验备份：

```bash
cd /var/backups/xinbaoyan/<备份时间>
sha256sum -c SHA256SUMS
```

恢复数据库与文件前保留当前现场。以下操作会覆盖现有数据，只能在明确选择的恢复点执行：

```bash
set -a
source /etc/xinbaoyan/infra.env
set +a

# 数据库导入；先确认目标实例确实是待恢复实例。
if [[ ${INFRA_MODE:-external} == external ]]; then
  gzip -dc mysql.sql.gz | sudo env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" \
    mysql --host=127.0.0.1 --port=3306 --protocol=TCP -uroot
else
  gzip -dc mysql.sql.gz | docker compose \
    --env-file /etc/xinbaoyan/infra.env \
    -f /opt/xinbaoyan/infra/docker-compose.yml \
    exec -T -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql mysql -uroot
fi

# 将现有目录改名保留，再恢复归档中的 data/。
sudo mv /var/lib/xinbaoyan/data "/var/lib/xinbaoyan/data.before-restore-$(date -u +%Y%m%dT%H%M%SZ)"
sudo tar -C /var/lib/xinbaoyan -xzf storage.tar.gz
sudo chown -R xinbaoyan:xinbaoyan /var/lib/xinbaoyan/data
```

恢复后执行 Alembic 状态检查、认证、题库、历史提交、竞赛成绩重算和队列巡检。不要直接重放恢复点前处于执行中的旧沙箱任务；按业务审批决定重判或标记系统异常。

## 8. 运维、监控与排障

### 8.1 常用命令

```bash
# 应用日志（不要向日志写入源码、测试点、密码或令牌）
journalctl -u xinbaoyan-api.service -u xinbaoyan-consumer.service \
  -u xinbaoyan-maintenance.service --since '30 min ago'

# 基础设施
cd /opt/xinbaoyan/infra
docker compose --env-file /etc/xinbaoyan/infra.env -f docker-compose.yml ps
docker compose --env-file /etc/xinbaoyan/infra.env -f docker-compose.yml logs --tail=100 mysql redis

# HTTPS 与证书
nginx -t
certbot certificates
certbot renew --dry-run
```

建议至少告警：API ready 失败、消费者/维护进程非 active、Worker 心跳离线、死信队列非空、队列等待时间与提交 SE 异常、MySQL/Redis/磁盘容量、备份失败和证书到期。

### 8.2 常见故障

| 现象 | 优先检查 |
| --- | --- |
| Nginx 502 | API 是否 active、`127.0.0.1:8000` 健康检查、API journal、当前 release 是否完整 |
| 发布停在健康检查前 | MySQL/Redis 容器健康、密码是否一致、备份是否成功、Alembic 输出 |
| 找回密码失败 | SMTP 占位符、587/STARTTLS、SMTP 凭据与 API journal；生产不会写本地验证码文件 |
| 上传返回 413 | Nginx `client_max_body_size` 与 `TEST_DATA_MAX_COMPRESSED_BYTES`，两者需一起评估 |
| 提交长期 PENDING | Celery Worker 在线状态、Outbox 维护日志、Redis 1 号库任务队列 |
| 提交长期 JUDGING | Worker 的 started 事件、结果消费者、0 号库 processing/dead 队列、执行租约巡检 |
| 结果进入死信 | 签名密钥是否一致、attempt/nonce 状态冲突、重复结果与数据库异常；不要直接盲重放 |
| 证书申请失败 | DNS、80 入站、AAAA 是否正确、certbot 日志；修复后再运行 bootstrap |

## 9. 上线验收清单

- [ ] `/etc/xinbaoyan/*.env` 为 root 管理、应用组只读，无示例密钥，未进入 Git。
- [ ] 生产使用 MySQL，未执行开发 seed，首个管理员通过交互 CLI 创建。
- [ ] HTTPS、HTTP 跳转、Secure Refresh Cookie、CORS、注册登录和找回密码通过。
- [ ] MySQL、Redis 与后端 8000 端口均未暴露公网，仅监听本机回环地址。
- [ ] API、消费者、维护进程重启后自动恢复，消费者与维护进程均为单实例。
- [ ] 题库、测试数据上传、提交、竞赛和管理员权限在真实 API 上验收。
- [ ] 判题沙箱的禁网、资源硬限制、进程树清理和看门狗全部通过后才开放提交。
- [ ] 新发布健康检查失败时能回切应用；已验证迁移与回滚版本兼容。
- [ ] 备份定时器正常，异地副本存在，且完成过隔离环境恢复演练。
- [ ] 日志、接口和判题诊断不泄露密码、令牌、源码、隐藏测试点或内部路径。

## 10. CI/CD 演进建议

当前脚本采用服务器构建，便于首版落地。后续可改为：CI 固定提交与依赖 → 运行测试 → 构建并签名 release 包 → 上传制品库 → 业务机拉取校验 → `RUN_TESTS=0` 发布。部署触发使用专用最小权限 SSH 账号和短期凭据，生产密钥只存在服务器或密钥管理系统，不下发到构建日志。多机扩容前，先将会话/限流/队列、持久化测试数据、迁移锁和单实例维护任务纳入统一设计。
