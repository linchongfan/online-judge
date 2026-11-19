# 阶段 4 GitHub、部署与备份清理日志

> 日期：2026-11-19
> GitHub 分支：`fix/judge-hardening-phase-1-2`
> 运行提交：`5dbf32e`
> 部署位置：`/opt/xinbaoyan-src`、`/opt/xinbaoyan-docker`
> 本文不记录任何服务器、数据库或 Redis 凭据。

## 1. 提交与部署

- 阶段 4 提交：`5dbf32e fix(web): 修复会话与做题页业务正确性`，已推送；尚未合并到 `master`。
- 部署前备份：`/var/backups/xinbaoyan/phase4-20261119T063730Z`，备份时已验证 gzip、MySQL `Dump completed` 和 SHA256SUMS。
- 回滚镜像标签：`pre-phase4`（验证后已按要求清理）。
- 构建期间曾出现 SSH banner 与 HTTP 响应超时；服务器恢复后确认前后端镜像均已成功构建，没有跳过构建或测试。
- 更新容器：API、结果消费者、维护进程、前端；备份容器随后也更新到当前 backend 镜像。
- 未运行任何旧 consumer/isolate 补丁。

## 2. 验证证据

### 接口与前端

```text
GET /api/v1/problems/1000/neighbors
→ {"prev":null,"next":1001,"index":1,"total":104}

GET http://127.0.0.1:9898/
→ HTTP 200
```

### 真实 API → Celery → Worker → 结果消费者

```text
PASS cpp-ac: AC
PASS c-ac: AC
PASS java-ac: AC
PASS py-ac: AC
PASS py-wa: WA
PASS py-ce: CE
ACCEPTANCE PASSED
```

- `/api/v1/health/ready` 返回 `status=ready`。
- API、消费者、维护进程、前端和 judge-worker 均正常运行。
- 更新后日志未发现新增异常或 cleanup 错误。

## 3. 备份清理

部署和验收全部通过后，按用户要求删除了此前为部署创建的回滚资产：

- 数据备份目录：
  - `deploy-20261118T141514Z`
  - `deploy-20261118T141547Z`
  - `phase3-20261119T035131Z`
  - `phase4-20261119T063730Z`
- judge 配置备份：`judge.env.bak-d4d31c5`、`judge.env.bak-phase3`。
- 部署说明备份：`README.md.bak-d4d31c5`。
- 回滚镜像标签：`pre-d7427be`、`pre-phase3`、`pre-phase4`。

备份容器最初仍引用 `xinbaoyan-backend:pre-d7427be`，因此先将其更新到当前 backend 镜像，再删除最后一个回滚标签；没有强删使用中的镜像。清理后上述目录和标签均不存在，其他历史数据与日常备份未改动。

最终健康检查：`status=ready`。
