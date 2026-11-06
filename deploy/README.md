# 生产部署与运维

## 部署形态

线上采用 **Docker 容器化**：前端、业务后端、结果消费者、维护进程、备份与判题 Worker 全部以容器运行，MySQL 与 Redis 复用服务器上已有的 1Panel 实例。

- **前端**：Nginx 容器，对外 `9898`，`/api/` 反代到本机 8000。
- **后端**：FastAPI 容器，仅监听 `127.0.0.1:8000`。
- **MySQL**：`8.4.13`，1Panel 容器，仅本机 `3306`。
- **Redis**：`8.10.3`，1Panel 容器，仅本机 `6379`（db0 结果队列 / db1 Celery）。
- **判题**：独立 `judge-worker` 容器，isolate + cgroup v2 + namespace，`--profile judge` 启动。
- **持久化**：测试数据、备份、判题 work/meta 均在容器外的宿主机目录。

## 文档入口

- **[Docker 容器化部署](./DOCKER_DEPLOYMENT.md)**：当前线上方案的服务清单、cgroup 前置、发布/补丁/备份/回滚。
- **[Linux 单机自动化部署方案](./LINUX_AUTOMATED_DEPLOYMENT.md)**：systemd + 宿主机 Nginx 的替代方案。
- **[业务部署脚本与模板](./linux/)**、**[判题部署资产](./judge-linux/)**：供 systemd 方案使用。
- 根目录 [`README.md`](../README.md)：本地开发、功能说明与测试。

## 同机隔离边界

同机不等于用户代码可以直接使用宿主环境：

- 用户代码必须在独立低权 UID、cgroup v2、mount/network namespace 和最小只读 rootfs 中执行。
- 判题 Worker 使用独立账号和 `/etc/xinbaoyan-judge/judge.env`，不得持有 MySQL、SMTP 或 Web `SECRET_KEY`。
- 用户程序不得访问宿主机 MySQL、Redis、FastAPI、其他任务目录或云元数据；沙箱禁网之外仍需宿主机防火墙兜底。
- `local` 后端只允许无害开发测试，普通 Docker 或 `subprocess` 不能作为生产安全边界。
- 首版 Worker 并发为 1；提高并发前必须验证整机资源预留、计时稳定性与 Web/数据库可用性。
- 单机部署会扩大沙箱缺陷的影响，任一隔离、清理或恢复能力未通过验收，都不得开放公开提交。

## 上线顺序（容器方案）

1. 准备 Ubuntu 服务器（已装 Docker 与 1Panel）、域名或公网 IP、SMTP、独立随机密钥；只开放 SSH 与前端端口。
2. 在 1Panel 创建数据库 `xinbaoyan` 与仅限该库的账号，确认 Redis 已设密码。
3. 准备 `/etc/xinbaoyan/app.container.env`、`/etc/xinbaoyan/infra.env`、`/etc/xinbaoyan-judge/judge.env`，权限 600/640，不进镜像。
4. 构建 `backend` / `frontend` / `judge` 三个镜像，执行 `docker compose run --rm migrate` 完成迁移与默认账号创建。
5. 启动 api、result-consumer、maintenance、backup、frontend，验证 `/api/v1/health/ready`、登录、题库、上传、竞赛与管理权限。
6. 配置 cgroup v2 子树并授予判题容器最小能力集，先跑隔离验收（AC/WA/TLE/MLE/RE、禁网、宿主文件不可读、清理）。
7. 只有验收通过后才 `--profile judge up -d judge-worker` 并开放公开提交。
8. 演练停止接单、Worker 离线、超时重试、死信处置、备份恢复与整机重建。

## 配置与发布原则

- `.env` 不进仓库；业务配置位于 `/etc/xinbaoyan/`，判题配置位于 `/etc/xinbaoyan-judge/`，均由 root 管理、对应服务组只读。
- `SECRET_KEY` 与 `JUDGE_RESULT_SECRET` 必须独立且随机；数据库、Redis、SMTP 凭据不得复用开发默认值。
- 配置与持久化目录通过只读/读写挂载进入容器，不烘焙进镜像；容器重建不丢数据。
- 消费者与维护进程必须单实例；扩副本前先验证队列、Outbox 与租约语义。
- 镜像重建后需重新执行 `patch-backend-image.sh` / `patch-judge-image.sh`（服务器侧兼容补丁）。
- 数据库只前向迁移，失败发布回滚镜像标签而非降级数据库。回滚前必须确认新旧版本与表结构兼容。
- 生产 API 文档默认关闭；日志不得记录源码、密码、令牌、隐藏测试数据或内部沙箱路径。

## 备份恢复

- MySQL 每日逻辑备份并保留异地副本，测试环境定期执行恢复演练；发布前额外备份。
- 测试数据版本目录与数据库恢复点保持一致，恢复后核对每个版本的 SHA-256。
- Redis 仅作缓存/队列，不作为竞赛成绩唯一数据源；成绩必须可由 `submission` 明细重算。
- 数据库与文件不是天然跨系统原子快照；严格一致性备份应在维护窗口暂停上传、判题和发布。
- 恢复后执行认证、题库、历史提交、竞赛成绩重算和队列巡检，不直接重放恢复点前执行中的旧沙箱任务。

## 疑似沙箱突破或节点失陷

立即停止公开提交和判题 Worker，隔离整台服务器，保留任务 ID、系统日志、isolate/rootfs/工具链版本和资源指标。撤销可能暴露的凭据，核对受影响提交与成绩，并从可信镜像重建。由于业务与沙箱同机，必须按整机可能受影响处理，不能把重启 Worker 当作完整处置。
