# 阶段 1–2 GitHub 与服务器部署日志

> 日期：2026-11-18
> GitHub 分支：`fix/judge-hardening-phase-1-2`
> 最终运行提交：`d4d31c5`
> 部署位置：`/opt/xinbaoyan-src`、`/opt/xinbaoyan-docker`
> 本文不记录任何服务器、数据库或 Redis 凭据。

## 1. 提交记录

| 提交 | 内容 |
| --- | --- |
| `d7427be` | 阶段 1、2 主体修复：测试点公开范围、Redis 消费、默认账号、isolate/Worker 安全边界及测试 |
| `46d383c` | 按最长前缀选择 `/box` 与工具链映射，修正 Linux spawn 测试断言 |
| `61729da` | 支持私有、受限 tmpfs 的显式 quota 兼容开关 |
| `f5677d7` | stdin 暂存文件权限修正 |
| `66c7408` | 每次 spawn 前将独立任务目录 chown 给对应 box UID/GID |
| `d4d31c5` | `--cleanup --cg` 及 cgroup 忙碌时有界重试、失败日志 |

上述提交均已推送到 GitHub。分支尚未合并进 `master`。

## 2. 部署前保护

- 应用数据库和存储备份：`/var/backups/xinbaoyan/deploy-20261118T141547Z`。
- 备份使用 `--no-tablespaces`，已验证 gzip 和 MySQL `Dump completed` 标记。
- 原备份服务使用旧 MySQL root 凭据时失败；未修改现有账号。其后已用应用数据库连接完成独立备份。
- 回滚镜像：`xinbaoyan-backend:pre-d7427be`、`xinbaoyan-frontend:pre-d7427be`、`xinbaoyan-judge:pre-d7427be`。
- judge 配置备份：`/etc/xinbaoyan-judge/judge.env.bak-d4d31c5`。

## 3. 部署方式

1. 服务器从 GitHub 分支拉取源码，最终 `HEAD=d4d31c5`。
2. 使用现有 `backend.Dockerfile`、`frontend.Dockerfile`、`judge.Dockerfile` 构建镜像。
3. **未运行** `patch-backend-image.sh` 或 `patch-judge-image.sh`，避免旧补丁覆盖上游修复。
4. judge 使用容器自身根文件系统：`JUDGE_LINUX_ROOTFS=/`；使用私有 `512MiB` tmpfs，并显式设置 `JUDGE_DISABLE_DISK_QUOTA=1`。其他部署仍默认启用 isolate quota。
5. 执行 Alembic 检查并更新 API、结果消费者、维护进程、前端和 judge-worker 容器。
6. `/opt/xinbaoyan-docker/README.md` 已标注后续不得再应用旧补丁。

## 4. 验证证据

### 服务器单元/集成测试

在 Linux 候选后端镜像中，使用独立 Redis 测试 DB：

```text
164 passed, 27 skipped, 1 warning
```

跳过项为 Windows 专用测试和需要显式授权的破坏性 VM 测试；未在业务服务器上运行 `linux_judge_vm`。

### 候选 judge 真实 isolate 验收

```text
PASS ac: AC
PASS wa: WA
PASS tle: TLE
PASS mle: MLE
PASS re: RE
PASS net: RE（禁网）
PASS hostfile: RE（宿主文件不可读）
ALL JUDGE CHECKS PASSED
残留 box cgroup：0
```

### 正式容器 API → Celery → Worker → 结果消费者端到端

```text
PASS cpp-ac: AC
PASS c-ac: AC
PASS java-ac: AC
PASS py-ac: AC
PASS py-wa: WA
PASS py-ce: CE
ACCEPTANCE PASSED
```

### 其他检查

- `/api/v1/health/ready` 返回 `status=ready`。
- 前端 `http://127.0.0.1:9898/` 返回 HTTP 200。
- 所有应用与 judge 容器处于运行状态，API 为 healthy。
- `scripts/audit_test_data_samples.py` 只读审计返回 `No mismatches found`；未执行 `--apply`。
- 正式验收后 box cgroup 数量为 0。

## 5. 剩余事项与风险

1. 本次 C++ 端到端提交产生一条 `CONFLICTING_JUDGE_RESULT` 死信；提交最终状态仍为 AC。它对应阶段 3 的 Outbox 原子领取/重复结果问题，未在本次阶段 1、2 范围内修复，不能视为长期零告警。
2. 当前服务器应用环境仍为 `APP_ENV=development` 且非 HTTPS 配置，本次未擅自修改；生产 HTTPS/TLS 终止需要单独实施。
3. 验收使用现有测试账号登录成功，说明该账号仍有效；应按阶段 1 安全建议删除或轮换默认测试/管理员账号并撤销旧会话。
4. 原有定时备份脚本的数据库 root 凭据问题仍需单独修正；本次只完成了独立部署前备份。
5. 真实 `linux_judge_vm` 破坏性套件仍需在一次性专用 VM 执行，未在业务服务器上运行。
