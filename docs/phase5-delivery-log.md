# 阶段 5 交付日志（供 k3.1 核验）

> 执行方：kimi-for-coding　日期：2026-11-19
> 依据：`docs/kimi-for-coding-plan.md` 阶段 5（性能与部署可复现性）
> 承接：阶段 4 已合并到 `master` 并部署（`9c26eb3`）。未提交、未推送。

## 一、修改日志

### 5.1 题库列表统计批量化（`app/services/problems.py`、`app/api/v1/problems.py`）

- 原实现 `problem_stats()` 每题执行 4 个聚合查询 + 登录用户再 1 个进度查询，
  列表页按题调用，100 题最多约 500 次 SQL。
- 新增 `problem_stats_batch(db, problem_ids, user_id)`：三个 `GROUP BY` 查询
  （计数/通过/已判、去重通过人数、当前用户进度）一次覆盖整页；
  `serialize_list_items()` 批量序列化，列表接口改用它。
- `problem_stats()` 与 `serialize_list_item()` 保留原签名，内部复用批量实现，
  单题详情与后台调用无需改动、口径一致。
- **实测**：使用同一个测试库统计 SELECT 次数，
  `pageSize=100` 时 3 道题 = 5 次、30 道题 = 5 次（旧实现随题数线性增长）。
- 新增回归：`tests/test_performance_phase5.py`
  - `test_problem_list_query_count_does_not_grow_with_page_size`：题数 3 → 28，查询数不得增长；
  - `test_batch_stats_match_single_problem_stats`：批量与单题结果逐字段相等，
    且样例运行不计入统计（2 次正式提交、1 次样例运行 → submission_count=2）。

### 5.2 竞赛结果增量更新（`app/services/contests.py`、`app/tasks/results.py`、`app/tasks/sweeper.py`）

- 新增 `recompute_contest_user_results(db, contest, user_id)`：
  - 一次查询取该用户在整场比赛的提交（按 `created_at, id` 排序），Python 内分组；
  - 复用原有 ACM 罚时口径（首个 AC 时间差 + 该题首次 AC 前 `PENALTY_STATUSES` × 20 分钟）；
  - 批量 upsert 该用户的 `ContestProblemResult`（一次查询现有行）与 `ContestResult`；
  - `_rerank_contest()` 基于物化的 `ContestResult` 行、按
    `(-solved, penalty, user_id)` 重排并保留并列名次语义。
- 结果消费者每个终态只更新**当前用户**并重排名次；巡检最终失败路径同样改为用户级。
- 报名流程改为用户级重算；取消报名后重新排名，删除的用户不再占名次。
- 管理员全量对账 `recompute_contest_results()` 保留，但改为批量：
  一次取该场全部报名提交，按用户内存分组，再统一 upsert，查询数与用户数无关。
- 新增回归：`test_incremental_contest_result_matches_full_recompute`
  —— 真实提交经 `process_judge_result` 增量计分后，再跑全量对账，
  `ContestResult` 的 `(solved, penalty, rank)` 完全一致。

### 5.3 测试数据上传（`app/api/v1/admin.py`、`deploy/linux/nginx.conf`、`src/api/admin.ts`）

- ZIP 校验/解压/fsync 从 FastAPI 事件循环移出：新增模块级
  `ThreadPoolExecutor(max_workers=2)`，通过 `run_in_executor` 执行，
  并发上传有界，不再阻塞同进程其他请求。
- 版本号分配事务化：先对 `Problem` 行 `SELECT ... FOR UPDATE` 再取 `MAX(version)`；
  唯一约束冲突返回 409 `TEST_DATA_VERSION_CONFLICT`，不再冒泡为 5xx。
- 失败清理：存储阶段异常删除目标版本目录并回滚；数据库提交失败同样删除已发布的
  不可变目录，避免孤儿版本目录。
- 超时对齐：Nginx `/api/` 读写超时 30s → 180s；前端上传超时 120s → 180s
  （后端校验大包 + 逐文件 fsync 可超过 30s）。
- 新增回归 `tests/test_test_data_upload.py`：
  - 连续上传版本号为 1、2；
  - 非法 ZIP 返回 422 且不产生存储目录；
  - 缺配对文件的 ZIP 记录为 `invalid` 版本。
- 现有上传测试继续通过，证明线程池路径正常。

### 5.4 部署资产纳入仓库（新增 `deploy/docker/`）

- 新增：`backend.Dockerfile`、`frontend.Dockerfile`、`judge.Dockerfile`、
  `docker-compose.yml`、`nginx.conf`、`app.container.env.example`、`README.md`。
- 内容对应线上已验证拓扑，并显式记录：
  - 禁止再运行废弃的 `patch-backend-image.sh` / `patch-judge-image.sh`；
  - judge 使用 `JUDGE_LINUX_ROOTFS=/` 与 `JUDGE_DISABLE_DISK_QUOTA=1`
    （私有 512MiB tmpfs 作为磁盘硬上限）；
  - 镜像内 isolate v2.0 下载带 SHA-256 校验。
- 示例环境文件只含键名与占位符，不含任何真实凭据。

### 5.5 载荷引用化与相对存储键设计（新增 `docs/payload-reference-design.md`）

- 按计划只出设计、不改架构：现有内联 hidden 数据的风险、三种获取方式
  （共享只读卷 / 短期签名 URL / 对象存储）、相对键迁移与双读、回滚策略、
  验收标准与风险。

## 二、最终验证

```text
pytest 全量（TEST_REDIS_URL=redis://127.0.0.1:6379/15）:
  196 passed, 19 skipped, 4 warnings        # 阶段4时 190；净增 6 项
ruff app judge tests scripts:  All checks passed!
mypy app judge scripts:         Success: no issues found in 79 source files
Vitest:                        29 passed
前端 build:                    ✓ built in 17.57s
git diff --check:              通过
```

## 三、未覆盖项

1. 查询数回归基于 SQLite 测试库；MySQL 执行计划与锁行为仍需集成环境观察。
2. 竞赛增量计分只验证了单用户/单题等价性；多用户多题、并列名次、取消报名后的
   排名建议在集成环境再跑一轮对比。
3. 上传线程池上限 2 为经验值，未做吞吐压测；超大包的真实耗时仍需线上观察。
4. `deploy/docker/` 与线上 `/opt/xinbaoyan-docker` 的一致性未做自动 diff 校验，
   后续可加 CI 检查。
5. 阶段 5 未提交推送，待 k3.1 核验。

## 四、变更集（相对 `master` 9c26eb3）

```text
M  app/api/v1/admin.py            M  app/api/v1/problems.py
M  app/services/problems.py       M  app/services/contests.py
M  app/tasks/results.py           M  app/tasks/sweeper.py
M  deploy/linux/nginx.conf        M  src/api/admin.ts
?? deploy/docker/backend.Dockerfile      ?? deploy/docker/frontend.Dockerfile
?? deploy/docker/judge.Dockerfile        ?? deploy/docker/docker-compose.yml
?? deploy/docker/nginx.conf              ?? deploy/docker/app.container.env.example
?? deploy/docker/README.md
?? docs/payload-reference-design.md
?? tests/test_performance_phase5.py      ?? tests/test_test_data_upload.py
```
