# 新保研在线判题网站

基于 Vue 3 + FastAPI 的在线判题系统。前端认证、题库、做题、提交、个人中心、竞赛及五类管理页面均已接入真实 API，后端提供测试数据、异步判题、竞赛和管理接口。

## 文档导航

- **[Docker 容器化部署](deploy/DOCKER_DEPLOYMENT.md)**：当前线上方案，前后端/消费者/维护/判题全部容器化，复用 1Panel 的 MySQL 与 Redis。
- **[Linux 单机自动化部署方案](deploy/LINUX_AUTOMATED_DEPLOYMENT.md)**：systemd + 宿主机 Nginx 的可选方案，含证书、备份、回切与排障。
- **[生产部署与运维](deploy/README.md)**：上线顺序、安全边界、备份和失陷处置。
- **[系统设计与安全防御计划](计划.md)**：功能范围、数据设计、威胁模型与验收标准。

## 运行环境

- 业务后端：Python **3.12**（当前开发验证版本 3.12.3）
- 前端：Bun **1.4.2**（Linux 部署脚本固定版本）、Vue 3、TypeScript、Vite
- 生产数据与队列：MySQL **8.4.13**、Redis **8.10.3**、Celery
- 生产用户代码工具链基线：
  - C/C++：GCC/G++ 13（C99 / C++11 语言标准），界面显示为 `C` / `C++`
  - Java：OpenJDK 17，`--release 8` 保持 Java 8 语言/API 目标，入口为 `public class Main`，界面显示为 `Java`
  - Python：独立 Python 3.12，界面显示为 `Python3`
- 界面语言名称统一为 **C++ / C / Java / Python3**，与 `judge/languages.py` 的适配器一一对应。
- 当前 Windows 开发机仍使用旧工具链；Linux 生产基线以上述版本为准，并在 CI 中做四语言判题结果比对。

## 本地启动业务后端

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe scripts/seed.py
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

未配置 `.env` 时，后端使用 `data/dev.db` SQLite 方便本地开发，验证码写入 `data/mail_outbox/`。正式部署应复制 `.env.example` 为 `.env`，更换所有密钥，并配置 MySQL、Redis、SMTP。

- API 文档：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- OpenAPI：`/api/v1/openapi.json`
- 健康检查：`/api/v1/health/live`、`/api/v1/health/ready`
- 开发种子账号：`admin / Admin12345`、`demo / Demo12345`。不要用于生产。

生产管理员应使用交互式 CLI 创建：

```bash
.venv/Scripts/python.exe scripts/create_admin.py <username> <email>
```

## 独立判题服务

判题 Worker 不连接业务数据库。业务后端通过事务 Outbox 和 Celery 投递任务，Worker 将 HMAC 签名事件与结果写入独立结果队列，后端消费者验证后幂等落库。

判题链路的可靠性语义（本轮补齐）：

- 任务投递成功仅表示进入队列；Worker 实际开始执行时发布签名 `started` 事件，业务侧据此进入 `JUDGING` 并打开执行租约，执行租约按“编译限时 + 各测试点时间限制倍数 + 冗余”计算，正常执行不会被误判超时。
- 已投递但长时间未开始的任务（消息在队列中丢失）由 `judge_task_queue_timeout_seconds`（默认 600 秒）巡检兜底；执行中租约过期的任务按 Worker 丢失处理，两者都会创建下一 attempt 重试，超过 `judge_task_max_attempts` 后提交标记 SE。
- 结果消费者使用 `BRPOPLPUSH`：消息先进入处理队列，成功落库后才确认；暂时性故障按指数退避重试（上限 8 次），签名非法、格式错误或状态冲突的消息进入死信队列 `judge:results:dead`，进程重启自动恢复未确认消息。
- 隐藏测试点不返回用户程序的运行时 stderr（防止通过 RE 回显泄露隐藏输入）；仅公开样例返回脱敏诊断。
- 管理端“停止接单”通过心跳下发：Worker 收到开关后暂停领取新任务（进行中任务仍会完成），恢复后自动继续；心跳超时 60 秒的节点在管理页显示为离线。

### 本机开发判题（当前环境已装好）

本机已安装好下列组件，可直接跑真实判题（返回 AC/WA/CE 等真实结果）：

- **Redis 8.10.3**：`tools/redis8/Redis-8.10.3-Windows-x64-msys2/redis-server.exe`（已启动在 6379 端口）
- **Dev-C++ 5.11（TDM-GCC 4.9.2）**：`C:\Program Files (x86)\Dev-Cpp\MinGW64\bin`
- **JDK 1.8（Amazon Corretto 8）**：`C:\Program Files\Amazon Corretto\jdk1.8.0_512\bin`
- **Python 3.8.6**：`C:\Python386\python.exe`

启动判题链路的三个进程（均已通过 `.env` 自动加载环境变量）：

```bash
# 1. Redis（如果还没启动）
tools/redis8/Redis-8.10.3-Windows-x64-msys2/redis-server.exe --bind 127.0.0.1 --port 6379

# 2. Celery 判题 Worker（solo 池，Windows 下不用 prefork；自带心跳线程，
#    心跳携带真实活跃/完成计数和“接单开关”）
.venv/Scripts/python.exe scripts/run_judge_worker.py

# 3. 判题结果消费者（可靠消费：处理队列 + 死信队列）
.venv/Scripts/python.exe scripts/run_consumer.py

# 4. 判题维护进程（Outbox 补偿重投 + 队列/租约过期巡检）
.venv/Scripts/python.exe scripts/run_judge_maintenance.py
```

端到端判题验收脚本（6 个场景：四语言 AC + WA + CE）：

```bash
.venv/Scripts/python.exe scripts/e2e_judge_acceptance.py
```

**注意**：本机开发判题使用的是 `LocalSubprocessBackend`，只用于无害程序验证，**不是生产安全沙箱**。生产 Linux 单机部署使用 `isolate + cgroup v2 + namespace + 只读 rootfs`，完成低权限、硬内存/进程/输出/磁盘限制、禁网、文件系统隔离及看门狗验收后才能开放提交。不得仅依靠普通 subprocess 或 Docker 容器运行不可信代码。

## Windows 开发/备用判题机加固

本节用于 Windows 开发或备用判题节点，不是当前 Linux 单机生产部署路径。所有脚本需以**管理员**身份运行。

### 1. 创建低权服务账号

```powershell
powershell -ExecutionPolicy Bypass -File scripts\create_judge_user.ps1
```

脚本会创建 `judge_svc` 账号（随机密码写入 `%ProgramData%\xinbaoyan\judge_svc.cred`），拒绝交互/网络/远程桌面登录，并输出最小 ACL 清单：

- 工具链目录（Dev-Cpp、Corretto、Python386）→ `judge_svc` **只读**
- `JUDGE_WORK_ROOT`（如 `D:\judge-work`）→ `judge_svc` **读写**
- 项目源码、`data\`、`.env` → **拒绝访问**

### 2. 配置网络隔离

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_judge_firewall.ps1 -Enable
```

为 `judge_svc` 添加入站允许、出站阻止的防火墙规则，放行 `127.0.0.1:6379`（任务队列/结果队列）与 loopback。启用后设置环境变量再启动 Worker：

```powershell
$env:JUDGE_FIREWALL_ACTIVE = "1"
```

该脚本默认适用于同机 Redis。Linux 单机生产部署不使用此 Windows 防火墙脚本；只有启用 Windows 备用远程判题节点时，才需要为受控私网队列和签名心跳调整规则并重新验收。

### 3. 使用 Windows 沙箱后端运行 Worker

```powershell
$env:JUDGE_ENV = "production"
$env:JUDGE_SANDBOX_BACKEND = "windows"
$env:JUDGE_WORK_ROOT = "D:\judge-work"
.venv\Scripts\python.exe scripts\run_judge_worker.py
```

`WindowsSandboxBackend`（`judge/windows_sandbox.py`）实现了：

- **受限令牌**：`CreateRestrictedToken` 派生（禁用所有权限、移除高危组），用 `CreateProcessWithTokenW` 启动用户程序
- **Job Object**：`KILL_ON_JOB_CLOSE` + 硬内存上限（`JOB_OBJECT_LIMIT_PROCESS_MEMORY`）+ CPU 时间限制（`JOB_OBJECT_LIMIT_PROCESS_TIME`），超限即整树终止
- **文件系统隔离**：每个任务在 `JUDGE_WORK_ROOT` 下创建独立临时目录，ACL 收紧至当前用户/SYSTEM/Administrators
- **网络隔离**：由外层防火墙承担（不伪造能力），未启用时 `SandboxPolicy.production()` 会明确报错提示

### 4. 安装看门狗

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_judge_watchdog.ps1
```

注册 `XinbaoyanJudgeWatchdog` 计划任务（开机自启、SYSTEM 运行）。看门狗（`scripts/judge_watchdog.py`）负责：

- Worker 进程消失或内存超阈值（默认 2GB）→ 清理残留任务目录并重启
- 每 30 秒扫描 `JUDGE_WORK_ROOT`，删除超过 1 小时的残留目录
- 日志写入 `logs/judge_watchdog.log`（不记录源码与测试数据）

### 5. 生产验收清单

- [ ] `judge_svc` 无法交互登录，无法访问项目源码与 `.env`
- [ ] 用户程序无法访问外网（防火墙规则生效）
- [ ] 无限循环程序在墙钟限制内被终止，进程树无残留
- [ ] 大内存程序被 Job Object 硬限制终止
- [ ] 超大输出被截断，任务目录被清理
- [ ] 强行结束 Worker 后，看门狗自动重启并清理现场

## 前端

```bash
bun install
bun run dev
bun run build
```

浏览器访问 `http://127.0.0.1:5173`。Vite 将 `/api` 代理到 `127.0.0.1:8000`；Access Token 仅保存在内存，刷新会话通过 HttpOnly Refresh Cookie 与 CSRF Cookie 完成。生产环境使用 Nginx 同源代理。

## 生产部署（Docker 容器化）

线上采用全容器拓扑：前端 Nginx 容器对外开放 `9898`，FastAPI、结果消费者、维护进程、备份与判题 Worker 分别运行在独立容器中；MySQL 8.4.13 与 Redis 8.10.3 复用服务器上已有的 1Panel 实例。后端、数据库与 Redis 端口均不对公网开放。

```bash
# 服务器上
cd /opt/xinbaoyan-src && git pull --ff-only
cd /opt/xinbaoyan-docker
docker build -f backend.Dockerfile  -t xinbaoyan-backend:local  /opt/xinbaoyan-src
docker build -f frontend.Dockerfile -t xinbaoyan-frontend:local /opt/xinbaoyan-src
docker build -f judge.Dockerfile    -t xinbaoyan-judge:local    /opt/xinbaoyan-src
./patch-backend-image.sh && ./patch-judge-image.sh
docker compose up -d --force-recreate api result-consumer maintenance backup frontend
docker compose --profile judge up -d --force-recreate judge-worker
```

完整步骤、cgroup 前置、补丁说明、备份与回滚见 **[Docker 容器化部署](deploy/DOCKER_DEPLOYMENT.md)**。

`deploy/linux/` 与 `deploy/judge-linux/` 保留了 systemd + 宿主机 Nginx 的替代方案（Ubuntu 22.04/24.04，22.04 会自动添加 deadsnakes PPA 安装 Python 3.12），适用于需要自动申请 HTTPS 证书或不想引入容器编排的环境，详见 **[Linux 单机自动化部署方案](deploy/LINUX_AUTOMATED_DEPLOYMENT.md)**。

首次部署完成后会自动创建两个初始账号（幂等，重复部署跳过）：

| 角色 | 账号 | 密码 |
| --- | --- | --- |
| 管理员 | `admin@123321` | `admin@123321` |
| 测试用户 | `test@123456` | `test@123456` |

首次登录后请立即在个人中心修改密码。禁用自动创建：systemd 方案用 `CREATE_DEFAULT_USERS=0`，容器方案跳过 `migrate` 服务中的建号步骤即可。`local` 沙箱后端不得用于真实用户代码。

## 配置与持久化

本地开发复制 `.env.example` 为 `.env`；生产环境不要沿用示例密钥。关键配置包括：

| 配置 | 用途 |
| --- | --- |
| `SECRET_KEY`、`JUDGE_RESULT_SECRET` | Web 会话与判题结果签名，生产必须独立随机 |
| `DATABASE_URL` | 开发默认 SQLite；生产使用 MySQL 8.4.13 |
| `REDIS_URL` | 限流、判题结果队列（0 号库） |
| `CELERY_BROKER_URL`、`CELERY_RESULT_BACKEND` | Celery 队列与结果后端，默认分别使用 1、2 号库 |
| `REFRESH_COOKIE_SECURE`、`CORS_ORIGINS` | 生产 HTTPS Cookie 与受控来源 |
| `SMTP_*` | 找回密码邮件；生产未配置 SMTP 时找回流程会报错 |
| `STORAGE_ROOT` | 测试数据版本等持久化文件，必须放在 release 外并纳入备份 |

Linux 生产配置在 `/etc/xinbaoyan/`，持久化数据在 `/var/lib/xinbaoyan/data`，发布版本在 `/opt/xinbaoyan/releases/`。同机判题配置独立放在 `/etc/xinbaoyan-judge/`，只包含本机队列与签名所需变量，不复制 MySQL 或 Web 会话密钥。

## 测试与检查

```bash
.venv/Scripts/python.exe -m pytest        # 113 passed, 14 skipped（Linux 专属用例在 Windows 跳过）
.venv/Scripts/python.exe -m ruff check app judge tests
.venv/Scripts/python.exe -m mypy app judge
bun run test                              # 11 passed
bun run build
```

API 测试覆盖认证、角色权限、Refresh Token 轮换、题目发布、ZIP 安全校验、隐藏数据边界、提交幂等、竞赛时间/报名约束、ACM 罚时、结果回调去重、默认账号幂等创建，以及判题后端的 TLE/MLE 元数据映射。Linux 判题侧另有 `tests/test_linux_isolate.py`（参数与元数据映射）和 `tests/test_linux_judge_vm.py`（需在判题机执行 `JUDGE_VM=1 pytest -m linux_judge_vm`）。

线上判题已按四语言实测：C++ / C / Java / Python3 的正确解均返回 AC，错误解 WA、语法错误 CE、死循环 TLE、超量内存 MLE，且用户程序无法访问本机 Redis 与宿主机配置文件。端到端脚本 `scripts/e2e_judge_acceptance.py` 支持 `--base-url / --account / --password / --problem-id` 参数化。
