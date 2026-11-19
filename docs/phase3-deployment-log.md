# 阶段 3 GitHub 与服务器部署日志

> 日期：2026-11-19
> GitHub 分支：`fix/judge-hardening-phase-1-2`
> 运行提交：`7cb4d93`
> 部署位置：`/opt/xinbaoyan-src`、`/opt/xinbaoyan-docker`
> 本文不记录任何服务器、数据库或 Redis 凭据。

## 1. 提交与备份

- 阶段 3 提交：`7cb4d93 fix(judge): 强化判题投递与队列一致性`，已推送到 GitHub 当前修复分支；尚未合并到 `master`。
- 部署前数据库与存储备份：`/var/backups/xinbaoyan/phase3-20261119T035131Z`。
- 备份已验证 gzip、MySQL `Dump completed` 和 SHA256SUMS。
- 回滚镜像：`xinbaoyan-backend:pre-phase3`、`xinbaoyan-frontend:pre-phase3`、`xinbaoyan-judge:pre-phase3`。
- judge 配置备份：`/etc/xinbaoyan-judge/judge.env.bak-phase3`。

## 2. 部署步骤

1. 服务器从 GitHub 拉取 `7cb4d93`。
2. 使用现有 Dockerfile 重建 backend 与 judge 镜像，未运行任何旧 consumer/isolate 补丁。
3. 执行 `docker compose run --rm migrate`，完成两个迁移：
   - `c3d4e5f6a7b8`：三个长文本列升级为 MEDIUMTEXT；
   - `d4e5f6a7b8c9`：Outbox 新增 `nonce`、`next_attempt_at`。
4. 通过 SQLAlchemy Inspector 确认生产 MySQL 中：
   - `outbox_message` 两列均存在；
   - `submission.source_code`、`solution_code.code`、`study_plan.description` 均为 MEDIUMTEXT。
5. 更新 API、结果消费者、维护进程和 judge-worker 容器。

## 3. 验证证据

### 候选验证（部署前）

```text
本地全量：       189 passed, 19 skipped
服务器候选镜像： 177 passed, 31 skipped
ruff / mypy：    全部通过
Vitest / build： 19 passed / 构建成功
```

### 正式容器 API → Celery → Worker → 结果消费者

```text
PASS cpp-ac: AC
PASS c-ac: AC
PASS java-ac: AC
PASS py-ac: AC
PASS py-wa: WA
PASS py-ce: CE
ACCEPTANCE PASSED
```

### 队列与资源检查

| 指标 | 验收前 | 验收后 |
| --- | --- | --- |
| `judge:results:dead` 数量 | 1（历史死信） | 1（未新增） |
| 全局队列槽位 | 无旧计数 | 0 |
| 测试用户槽位 | 无旧计数 | 0 |
| 按提交预留的 reservation keys | — | 0 |
| 残留 isolate box cgroup | — | 0 |

- `/api/v1/health/ready` 返回 `status=ready`。
- 结果消费者与 judge-worker 近 10 分钟日志未发现新的异常或 cleanup 错误。
- 容量拒绝、重复释放和终态结果时间字段均另有本地/候选回归测试覆盖。

## 4. 剩余事项

1. 本分支尚未合并到 `master`；是否合并未在本次部署中处理。
2. 默认测试账号仍能登录，应尽快删除或轮换默认账号并撤销旧会话。
3. 当前服务器应用仍为 development/非 HTTPS 配置，生产 TLS 与 `APP_ENV` 需单独整改。
4. 原定时备份的 MySQL root 凭据问题仍需单独修正；本次使用的是部署前独立备份。
5. 条件 UPDATE 在真实高并发下的长期表现及槽位平衡需继续观察，不在本次短时验收中作绝对保证。
