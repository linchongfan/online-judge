# 判题载荷引用化与相对存储键：设计方案（仅设计，未实施）

> 状态：设计文档。阶段 5 只做评估与方案，代码与数据迁移需单独立项。
> 关联：`app/tasks/dispatcher.py`、`judge/linux_isolate.py`、`app/api/v1/admin.py`。

## 1. 现状

- 每次投递把**全部测试点的输入和标准答案**内联进 Celery/Redis 消息
  （`_build_payload` 读取 `{version.storage_path}/{case.input_key}`）。
- 数据库 `test_data_version.storage_path` 与 `test_case.*_key` 解析出的
  路径是**服务器绝对路径**。

影响：

1. 隐藏数据在 Redis 中长时间驻留，泄露面扩大；消息体可达数百 MB。
2. 判题节点必须与 API 共享同一文件系统布局，无法独立扩缩容。
3. 备份恢复到不同挂载点后，历史记录中的绝对路径失效。

## 2. 目标

1. 消息体只携带**不可变版本引用**（`test_data_version_id` + `content_hash`），
   判题节点按需拉取并校验。
2. 数据库只存**相对键**（如 `test-data/problem-1000/<version-id>`），
   运行时由 `STORAGE_ROOT` 解析。
3. 兼容历史绝对路径数据，可回滚、可双读。

## 3. 版本引用获取方式（三选一，建议 B → C 演进）

### A. 共享只读卷（最小改动）

- 判题容器挂载 `/var/lib/xinbaoyan/data:ro`（当前 judge 已挂 work/meta，
  未挂 data）。
- Worker 用 `STORAGE_ROOT` + 版本相对键读取并计算 sha256，与消息中的
  `content_hash` 比对后执行。
- 优点：无需新服务；缺点：仍要求同一主机/共享存储。

### B. 短期签名 URL（推荐起点）

- API 在投递消息时生成一次性、限时的下载 URL（HMAC 签名 + 版本 id +
  过期时间），指向新增的只读内部端点：
  `GET /api/v1/internal/test-data/{version_id}?expires=...&signature=...`
- 该端点只允许判题服务签名访问，按文件流式返回 zip 或按需单文件。
- Worker 先下载到本地临时目录，校验 `content_hash` 与逐文件 sha256，
  校验失败按 SE 处理（fail closed）。
- 优点：判题节点无共享存储依赖；缺点：需要内网鉴权与带宽预算。

### C. 对象存储（长期）

- 版本目录上传至 S3 兼容存储，签名 URL 直连；API 只存对象 key。
- 需要新增上传管道与生命周期策略。

## 4. 相对存储键迁移

### 4.1 新写入

- `TestDataService` 的 `version_dir` 由调用方传入相对键，服务内部仍用
  `STORAGE_ROOT` 解析绝对路径落盘。
- `test_data_version.storage_path` 存相对键 `test-data/problem-<id>/<version-id>`。
- `test_case.input_key` / `output_key` 已是相对路径（如 `sample/1.in`），不变。

### 4.2 历史数据

1. 新增一次性迁移脚本：
   - 对每行 `storage_path`，若为绝对路径且以当前 `STORAGE_ROOT` 为前缀，
     改写为相对键；否则列入人工清单（不猜测）。
   - 校验目标目录存在且非符号链接；不存在则标记 `INVALID` 并告警。
2. 运行时解析函数：

   ```python
   def resolve_version_dir(storage_path: str) -> Path:
       path = Path(storage_path)
       return path if path.is_absolute() else (settings.storage_root / path)
   ```

   `dispatcher._build_payload`、`services/problems.serialize_detail`、
   审计脚本全部改用该函数，保证迁移前后都能读。

### 4.3 回滚策略

- 迁移脚本保留 `--revert`：按导出的映射表还原绝对路径。
- 双读期至少一个发布周期，确认无绝对路径访问后再收紧。

## 5. 验收标准

1. 消息体大小与测试点数量无关（仅引用 + 哈希）。
2. 篡改/缺失测试数据 → 任务 SE，且 dead-letter 原因可读。
3. 迁移脚本 dry-run 输出完整清单；恢复后路径仍可解析。
4. 真实判题四语言 AC/WA/CE 与迁移前一致。

## 6. 风险与开放问题

- 签名 URL 端点必须严格限制来源（仅判题服务网络/凭证），否则取代号
  “共享目录”风险。
- 大版本频繁重判会放大下载带宽；需按 `content_hash` 做判题节点本地缓存。
- 对象存储迁移涉及备份脚本（`deploy/linux/backup.sh` 目前打包 data 目录）。
