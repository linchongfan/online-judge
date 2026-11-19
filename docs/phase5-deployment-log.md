# 阶段 5 GitHub 与服务器部署日志

> 日期：2026-11-19
> GitHub 分支：`fix/performance-phase-5` → 已合并 `master`
> 运行提交：`54f8fbc`（功能提交 `35b6102`）
> 部署位置：`/opt/xinbaoyan-src`、`/opt/xinbaoyan-docker`
> 本文不记录任何服务器、数据库或 Redis 凭据。

## 1. 提交

| 提交 | 内容 |
| --- | --- |
| `35b6102` | `perf: 优化题库统计与竞赛计分`（批量统计、增量计分、上传隔离、部署资产） |
| `54f8fbc` | `merge: 性能与部署可复现性优化`（合并到 `master`） |

均已在 GitHub；`master` 已推进到 `54f8fbc`。

## 2. 部署步骤

1. 备份：`/var/backups/xinbaoyan/phase5-20261119T104233Z`，已验证 gzip、MySQL `Dump completed`、SHA256SUMS。
2. 回滚镜像标签：`xinbaoyan-backend:pre-phase5`、`xinbaoyan-frontend:pre-phase5`。
3. 服务器 `git checkout -B master origin/master`，确认 `HEAD=54f8fbc`。
4. 重建 backend 与 frontend 镜像（frontend 构建内运行 Vitest 和生产构建）。
5. 执行 `alembic upgrade head`（本阶段无新迁移）。
6. 用仓库内 `deploy/docker/nginx.conf` 替换服务器 `/opt/xinbaoyan-docker/nginx.conf`（旧文件备份为 `nginx.conf.bak-phase5`），上传超时 30s → 180s。
7. 更新 API、结果消费者、维护进程、前端容器；judge 代码本阶段未变，未重启。

## 3. 验证证据

```text
GET /api/v1/problems?page_size=100
→ items=100 total=104 elapsed_ms=64                （统计字段正常）

GET /api/v1/problems/1000/neighbors
→ {"prev":null,"next":1001,"index":1,"total":104}

GET http://127.0.0.1:9898/ → HTTP 200
GET /api/v1/health/ready   → {"status":"ready"}
```

真实 API → Celery → Worker → 结果消费者：

```text
PASS cpp-ac / c-ac / java-ac / py-ac / py-wa / py-ce
ACCEPTANCE PASSED
```

队列与日志：

```text
PENDING/JUDGING 提交数：0
judge:slots:global：0；按提交预留键：0
API / 结果消费者 / 维护进程近 10 分钟：无 Traceback、无 ERROR
```

## 4. 未验证项

- 测试数据上传未做线上实测：缺少可用的管理员登录方式，且线上没有删除题目的接口，
  验证会产生无法清理的草稿数据。该路径由 3 个 API 级测试覆盖
  （版本递增、非法 ZIP 无孤儿目录、无效版本记录）。
- 竞赛排行榜未做线上实测：线上当前没有竞赛数据；等价性由
  `test_incremental_contest_result_matches_full_recompute` 与既有
  ACM 罚时断言覆盖。
- 未做上传吞吐压测，线程池上限 2 为保守值。

## 5. 备份保留说明（与以往不同）

此前部署完成后会删除部署备份。本次**保留** `phase5-20261119T104233Z`，原因：

- 定时备份容器 `xinbaoyan-docker-backup-1` 仍因 `infra.env` 中 MySQL root 凭据
  错误而失败（日志：`Access denied for user 'root'@'172.18.0.1'`），
  最近一次成功备份是 `20261105T075255Z`。
- 在定时备份修复前删除唯一一份已验证的手工备份会让系统处于无可用恢复点的状态。

因此本次未删除该备份，也未删除 `pre-phase5` 回滚标签。修复 `infra.env` 凭据
并确认定时备份恢复产出后，可再清理。
