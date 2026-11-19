# 阶段 3 交付日志（供 k3.1 核验）

> 执行方：kimi-for-coding　日期：2026-11-19
> 依据：`docs/kimi-for-coding-plan.md` 阶段 3（判题可靠性与数据一致性）
> 承接：阶段 1、2 已部署上线（服务器运行 `d4d31c5`）。未提交、未推送；未操作线上环境。

## 一、修改日志

### 3.1 Outbox 原子 claim + 稳定 nonce + 错误分类（`app/tasks/dispatcher.py`、`app/models/entities.py`）

- `OutboxMessage` 新增 `nonce`（每 attempt 稳定投递标识，首次 claim 时生成、永不再变）与 `next_attempt_at`（退避时间）。
- **投递模型为 at-least-once**：条件 UPDATE 原子领取（`status=pending` 且不在退避窗口内才认领，`COALESCE` 保留既有 nonce）→ 提交 → 构建 payload → 发送；发送前崩溃由 sweeper 的队列超时恢复；发送后重复投递因 nonce 稳定产生**完全相同的签名结果**，消费者按 `result_hash` 幂等吸收（部署中观察到的 `CONFLICTING_JUDGE_RESULT` 死信根因即旧实现每次投递生成新 nonce，已被消除）。
- **错误分类**：payload 构建失败（提交/版本缺失、无可运行测试点）为永久错误 → outbox `FAILED` + 任务/提交 SE，不再每 5 秒无限重试；broker 发送失败为临时错误 → `attempts+1`、指数退避（上限 300s）、达到 8 次后终态失败。修复过程中发现并修正：`_claim` 未提交即被异常路径回滚（nonce/状态实际未落库）、终态分支返回值错误两个自身缺陷。

### 3.2 结果消费者与巡检一致化（`app/tasks/results.py`、`app/tasks/sweeper.py`）

- `process_judge_result`/`process_judge_started` 读取任务加 `with_for_update` 行锁；任务/提交的状态写入改为**条件 UPDATE**（`WHERE status IN (PENDING,JUDGING) AND attempt=当前最新`），并发产生的更新行数为 0 时放弃写入，旧 attempt 结果不可能覆盖新 attempt。
- 提交到达终态时**释放队列预留槽位**（`queue_capacity.release`）；sweeper 的最终失败路径同样释放；重试 attempt 继续占用槽位。
- sweeper 加 `with_for_update`；队列超时判断引入健康 Worker 启发式：存在 120 秒内心跳的在岗 Worker 时，队列丢失判定阈值放宽为 `queue_timeout × 3`，避免健康积压下重复排队。

### 3.3 Redis Lua 原子验证码与限流（`app/services/verification.py`、`app/services/rate_limit.py`）

- 验证码验证改为单条 Lua 脚本完成 取→计数→比较→消费/递增，并发请求无法再共享 5 次尝试预算或重复消费有效码。兼容 Redis < 6（无 `KEEPTTL`，用 `PTTL`+`PX` 保留 TTL——本地测试 Redis 5.0.14 实测发现并修正）。
- 限流 `INCR`+`EXPIRE` 合并为单条 Lua，消除进程崩溃留下无 TTL 永久键的窗口。

### 3.4 队列容量原子预留 + 幂等冲突（`app/services/queue_capacity.py`（新增）、`app/services/submissions.py`）

- 新服务：提交受理时在 Redis 以 Lua 原子预留全局/用户槽位（`judge:slots:*`），终态释放；预留带 1 小时 TTL 兜底进程崩溃，生产环境预留不可用时 fail-closed；非生产无 Redis 时回退原 DB 计数。
- 同一幂等键并发唯一冲突：`IntegrityError` → 回滚 → 重取已有提交并做 payload 一致性校验（一致返回已有提交，不一致 409 `IDEMPOTENCY_CONFLICT`），不再向上冒泡为 5xx。

### 3.5 MEDIUMTEXT 迁移（`alembic/versions/c3d4e5f6a7b8_widen_text_columns.py`）

- MySQL 下 `submission.source_code`、`solution_code.code`、`study_plan.description` 由 TEXT 升级为 MEDIUMTEXT（源码上限 65,536 UTF-8 字节原已超 TEXT 的 65,535 字节上限；题解/计划按字符校验，utf8mb4 下同样可超限）。非 MySQL（含测试用 SQLite）为 no-op。新增迁移链升级/降级往返测试。

## 二、测试

| 文件 | 内容 |
| --- | --- |
| `tests/test_dispatcher_phase3.py`（新增，5 项） | nonce 跨重复投递稳定且第二次不再发送；永久错误终态且不重试；临时错误退避（热循环立即重发被阻止）、有界次数后终态；相同结果重复投递幂等；旧 attempt 结果被吸收且不污染新 attempt。 |
| `tests/test_queue_capacity.py`（新增，3 项） | 全局/用户上限在回退路径生效；同键并发冲突返回已有提交；同键不同内容 409。 |
| `tests/test_verification_integration.py`（新增，2 项，真实 Redis） | 8 线程并发错误猜测不超过 5 次预算；有效码 4 线程并发消费恰好一次成功。 |
| `tests/test_migrations.py`（新增，1 项） | Alembic `upgrade head`/`downgrade base` SQLite 往返。 |
| `tests/conftest.py` | 测试前置清理增加 `judge:slots:*`。 |

调试过程中发现并修复的**自身实现缺陷**（非测试问题）：`_claim` 缺少提交导致 nonce/认领状态在异常路径被回滚；瞬时错误达到上限后返回值未区分终态。另修正测试会话 `expire_on_commit=False` 导致的手工重置不落库问题（测试侧）。

## 三、最终验证

```text
pytest 全量（TEST_REDIS_URL=redis://127.0.0.1:6379/15）:
  185 passed, 19 skipped, 3 warnings        # 阶段2部署时 172；净增 13 项
ruff app judge tests scripts:  All checks passed!
mypy app judge scripts:         Success: no issues found in 79 source files
bun run test:                   19 passed
bun run build:                  ✓ built in 16.66s
bash -n 三个部署脚本:            通过
git diff --check:               通过
```

## 三之二、k3.1 核验后的修正（第二轮）

k3.1 核验发现 2 个 P0/P1 + 2 个 P2，已全部修正：

| 问题 | 修正 |
| --- | --- |
| [P0] Outbox 新增 `nonce`/`next_attempt_at` 无迁移，临时 MySQL `upgrade head` 后两列不存在，直接部署会 `Unknown column` | 新增迁移 `d4e5f6a7b8c9_add_outbox_delivery_fields.py`（add_column/drop_column 双向）；`alembic/env.py` 支持 `ALEMBIC_DATABASE_URL` 覆盖（此前强制使用应用 `DATABASE_URL`，导致迁移测试实际未测临时库）；迁移测试改为真实临时库升级并断言两列存在后再降级 |
| [P1] 用户槽位预留失败时 `release(user_id)` 同时减少全局与用户计数（Lua 已回滚用户 INCR），多减一次；释放非幂等；预留在校验完成前执行导致验证失败泄漏 | 预留改为按 `submission_id` 绑定（`judge:slot:sub:{id}` 记录属主用户），释放按提交幂等（Lua 仅在 reservation key 存在时递减）；用户拒绝路径改为只回滚全局槽位（修复中先误用 submission 关联 release，已被"拒绝后仍占满 per-user 上限"测试捕获）；预留移到 `_create_record` 内、全部校验与幂等冲突检查之后，后续失败显式补偿释放；开发环境回退路径无预留可泄漏 |
| [P2] 终态结果的 `started_at` 写为 NULL（`Submission.started_at is not None` 对 ORM 属性恒真） | 改为 `func.coalesce(Submission.started_at, task.started_at or now)`；新增直接终态结果的回归测试 |
| [P2] dispatcher 读取测试数据的 `OSError`/`UnicodeError` 未归类为永久错误 | `_build_payload` 捕获并转为 `PermanentDispatchError`（不再进入重试路径）；新增回归测试 |

**修正后验证**：本地全量 `189 passed, 19 skipped`；服务器候选镜像 `177 passed, 31 skipped`；临时 MySQL `upgrade head` 后 `outbox_message` 含 `nonce`/`next_attempt_at`，三个文本列均为 `mediumtext`；ruff/mypy/Vitest/build 全绿。评审环境已清理，线上容器未改动。

## 四、未覆盖项

1. 条件 UPDATE 的并发行为（`rowcount=0` 分支）在 SQLite 顺序执行下只能验证逻辑分支；**MySQL 下的真实并发竞争需集成环境验证**。
2. 队列槽位预留/释放的端到端平衡（预留→判题→释放）在本机由单元测试覆盖各点，长期泄漏监控需上线后观察 `judge:slots:*`。
3. `linux_judge_vm` 破坏性套件仍未执行。
4. 阶段 3 尚未提交推送；待 k3.1 核验后连同阶段 1、2 的后续修正一起处理。

## 五、变更集（相对阶段 2 部署提交 1a3cc58）

```text
M  app/models/entities.py        M  app/services/submissions.py
M  app/services/verification.py  M  app/services/rate_limit.py
M  app/tasks/dispatcher.py       M  app/tasks/results.py
M  app/tasks/sweeper.py          M  tests/conftest.py
?? app/services/queue_capacity.py
?? alembic/versions/c3d4e5f6a7b8_widen_text_columns.py
?? tests/test_dispatcher_phase3.py  ?? tests/test_queue_capacity.py
?? tests/test_verification_integration.py  ?? tests/test_migrations.py
```
