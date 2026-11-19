# 阶段 1 交付日志（供 k3.1 核验）

> 执行方：kimi-for-coding　日期：2026-11-18
> 依据：`docs/kimi-for-coding-plan.md` 阶段 1（1.1 / 1.2 / 1.3）
> 未提交、未推送；未操作线上数据库、账号或部署。

## 一、修改日志

### 1.1 测试点公开范围（隐藏数据保密）

| 文件 | 变更 |
| --- | --- |
| `app/api/v1/admin.py:425,434` | `is_sample` 与 `sample_count` 由 `category != "hidden"` 改为 `category == "sample"`。只有显式 `sample/` 目录的测试点会作为公开样例返回给题目详情接口。 |
| `tests/test_problem_api.py` | 新增 `test_uploaded_default_layout_cases_are_never_exposed_as_samples`：参数化四种 ZIP 布局（根目录平铺、单顶层目录、`sample/`+`hidden/` 分组、顶层目录内分组），断言上传响应 `sampleCount`、题目详情 `samples` 只含 sample 内容，且 default/hidden 数据不出现在详情中。修复前该测试在根目录布局下失败（`sampleCount` 错误返回 1）。 |
| `scripts/audit_test_data_samples.py`（新增） | 历史数据审计/修复命令。利用 `TestCase.input_key` 保留的存储路径前缀（`sample/1.in` vs `1.in`）推导原始目录类别，核对并（`--apply` 时）修复 `is_sample` 与 `sample_count`；修复会冲突于 `(version_id, case_number, is_sample)` 唯一约束的版本整版跳过并报告"需重新上传"。审计模式发现不匹配时退出码为 1。**未对任何历史数据执行批量变更**——需运维在目标环境先审计、确认后再 `--apply`。 |
| `tests/test_audit_test_data_samples.py`（新增） | 5 项测试：路径前缀判定、脏数据+错误计数识别、正确/INVALID 版本排除、修复与二次审计清零、唯一约束冲突整版跳过。 |

### 1.2 Redis 结果消费

| 文件 | 变更 |
| --- | --- |
| `app/tasks/consumer.py` | ① 提取 `_consume_once(client, block_ms)`，`BRPOPLPUSH` 返回值按**单值**处理（新增 `_to_bytes`，兼容 bytes/str），取代原 `item[1]` 按元组取值的错误写法；`consume_results` 循环调用它，行为不变。② `_handle_message` 在 `json.loads` 后校验 envelope 必须为 dict，非对象 JSON（数组/字符串/数字）进入死信并 ack，消除毒消息无限回队。 |
| `tests/test_consumer_integration.py`（新增） | 6 项**真实 Redis**集成测试（不 mock 队列客户端）：签名结果消费+落库+ack、非法 JSON 死信、非对象 envelope 死信（回归毒消息循环）、错误签名死信、瞬时失败带 attempts 计数重试后成功、孤儿 processing 消息恢复。模块在 Redis 不可达时整体 skip，不影响无 Redis 的 CI。 |

### 1.3 生产初始化与 HTTPS 配置

| 文件 | 变更 |
| --- | --- |
| `scripts/ensure_default_users.py` | 移除全部内置固定凭据（原 `admin@123321`/`test@123456`）。默认（`CREATE_DEFAULT_USERS` 未设为 `1`）为**完全不建号**的空操作；启用时管理员凭据必须经 `DEFAULT_ADMIN_*` 环境变量完整提供；测试用户需额外 `CREATE_DEFAULT_TEST_USER=1` 显式 opt-in，否则即使提供 `DEFAULT_TEST_*` 也拒绝创建。 |
| `tests/test_default_users.py` | 按新契约重写：6 项测试覆盖默认不建号、凭据不全报错、显式凭据建管理员、测试用户 opt-in 约束、幂等。 |
| `deploy/linux/deploy.sh:119-125` | `CREATE_DEFAULT_USERS` 默认值由 `1` 改为 `0`，注释更新。 |
| `deploy/linux/configure.sh` | 移除纯 IP 模式的 `REFRESH_COOKIE_SECURE=false` 与 CORS http 降级；传入裸 IP 直接报错退出，要求域名+HTTPS。 |
| `deploy/linux/bootstrap.sh` | 同上：拒绝裸 IP；删除 IP-only 分支（不再跳过 certbot、不再使用 nginx-ip.conf）。 |
| `deploy/linux/nginx-ip.conf` | 删除（仅被已删除的 IP-only 分支引用）。 |
| `scripts/seed_c_curriculum.py` | 不再硬编码查找 `admin@123321`；优先 `CURRICULUM_OWNER` 环境变量指定账号，否则取任一管理员，找不到时给出创建指引。 |
| `README.md`、`deploy/LINUX_AUTOMATED_DEPLOYMENT.md` | 删除固定账号表；改为 `create_admin.py` 交互建号说明、显式 opt-in 自动建号说明、HTTPS 强制说明；增加"旧部署必须删除/轮换 `admin@123321`、`test@123456` 并撤销其会话"的人工检查项。 |

**未做事项（按计划约束）**：未修改 `app/core/config.py` 的生产 Secure Cookie 校验；未对线上账号/会话做任何操作；未运行破坏性沙箱测试。

## 二、测试日志

### 基线（修改前）

```
pytest:            123 passed, 14 skipped, 1 warning in 63.93s
ruff app judge tests:   All checks passed!
mypy app judge:         Success: no issues found in 66 source files
bun run test:           4 files, 19 tests passed
bun run build:          ✓ built in 17.50s（仅既有 chunk 体积告警）
```

### 环境说明

- 本机无 Docker、无已安装的 Redis。为执行计划要求的"真实 Redis 集成测试"，临时下载 Windows 版 Redis 5.0.14.1（tporadowski 构建）解压到 `~/.tmp-redis/`，前台运行于 `127.0.0.1:6379`，测试完成后已停止并保留目录备查。**未污染项目目录与仓库。**
- 集成测试运行期间该实例仅承载本测试自建并自动清理的三个队列键（`judge:results*`）。

### TDD 过程

1. `test_uploaded_default_layout_cases_are_never_exposed_as_samples` 在修复前 **FAILED**（根目录布局 `sampleCount` 断言：期望 0 实际 1），修复后通过。
2. 消费者集成测试在 `_consume_once` 修复前 **收集错误**（`_consume_once` 尚不存在）；按旧解析逻辑（`item[1]` 按元组取值）对 bytes 返回值会取到错误数据/触发异常，新实现改为单值处理并通过全部 6 项测试。

### 最终验证（修改后）

```
pytest 全量:            139 passed, 14 skipped, 1 warning in 27.22s
  ├─ tests/test_problem_api.py            3 passed（含新增四类布局回归）
  ├─ tests/test_audit_test_data_samples.py 5 passed（新增）
  ├─ tests/test_consumer_integration.py    6 passed（新增，真实 Redis 5.0.14.1）
  └─ tests/test_default_users.py           6 passed（重写）
ruff app judge tests:   All checks passed!
ruff scripts:           All checks passed!（本次顺带修复 scripts 范围内 5 个既有/新增告警，全量 0 错误）
mypy app judge:         Success: no issues found in 66 source files
mypy scripts:           Success: no issues found in 12 source files
mypy tests（扩展范围）:  12 errors in 4 files——全部位于既有文件
  （conftest.py、test_judge_config.py、test_judge_protocol.py、test_linux_isolate.py），
  本次新增/修改的测试文件 0 错误；按计划在后续工程化阶段单独处理。
bash -n bootstrap.sh/configure.sh/deploy.sh:  shell syntax OK
bun run test:           4 files, 19 tests passed
bun run build:          ✓ built in 14.81s
```

基线→最终：pytest 123 → 139 passed（净增 16 项，跳过数不变）；warnings 4 → 1（仅剩既有的 starlette 弃用告警；后续在 Windows 上复跑时偶发 1 个 `test_windows_sandbox.py` 的句柄资源告警，属环境性既有问题，与本次变更无关）。

## 二之二、k3.1 核验后的修正（第二轮）

k3.1 核验提出 3 个问题，已全部修正：

| 问题 | 修正 |
| --- | --- |
| [P1] 消费者集成测试直接删除配置 Redis 的队列，有误清共享/生产实例风险 | `tests/test_consumer_integration.py` 改为仅在显式设置 `TEST_REDIS_URL`（推荐，专用实例）或 `APP_ENV=test` 时才运行；否则整体 skip，不再触碰配置指向的 Redis。修正验证：设置 `TEST_REDIS_URL=redis://127.0.0.1:6379/15` 时 6 passed；未设置时 6 skipped，且开发实例 db0 未被触碰。 |
| [P2] `test_default_users.py` 未隔离 `CREATE_DEFAULT_USERS`，外部环境变量会导致测试失败（已复现） | 新增 autouse fixture `_isolate_default_user_env`，统一清理 `CREATE_DEFAULT_USERS`、`CREATE_DEFAULT_TEST_USER`、`DEFAULT_ADMIN_*`、`DEFAULT_TEST_*` 共 8 个变量。修正验证：在导出 `CREATE_DEFAULT_USERS=1` 及全套 `DEFAULT_ADMIN_*` 的污染环境下 6 passed。 |
| [P2] 部署文档与新策略矛盾（`configure.sh` 帮助仍写 `public-domain-or-ip`；`DOCKER_DEPLOYMENT.md` 仍描述纯 IP HTTP） | `configure.sh` 帮助改为 `<public-domain>`；`DOCKER_DEPLOYMENT.md` 已知限制改为"对外必须 HTTPS，明文 HTTP 仅供临时联调"；并补充说明：consumer 补丁问题已在本仓库上游修复，部署本版本后应移除 `patch-backend-image.sh` 中的 consumer 补丁。 |

补充说明：k3.1 指出日志中"PytestCollectionWarning 4 → 1"措辞有误，已更正为"warnings 4 → 1"。

### 变更集（git status，未提交）

```
M  app/api/v1/admin.py          M  app/tasks/consumer.py
M  README.md                   M  deploy/LINUX_AUTOMATED_DEPLOYMENT.md
M  deploy/linux/bootstrap.sh   M  deploy/linux/configure.sh
M  deploy/linux/deploy.sh      D  deploy/linux/nginx-ip.conf
M  scripts/ensure_default_users.py  M  scripts/seed_c_curriculum.py
M  tests/test_default_users.py M  tests/test_problem_api.py
?? scripts/audit_test_data_samples.py
?? tests/test_audit_test_data_samples.py
?? tests/test_consumer_integration.py
```

（`tsconfig.tsbuildinfo` 曾因 `bun run build` 变动，已还原；该文件未纳入 .gitignore 的问题列入阶段 6 backlog。）

## 三、待 k3.1 核验要点

1. `admin.py` 两处 `== "sample"` 是否为最小且完整的修复面（`services/test_data.py` 的 `sample_count` 计数原本即正确，未改动）。
2. 审计脚本以 `input_key` 前缀还原类别的假设是否适用于线上历史数据（建议先在备份库/只读账号上运行不带 `--apply` 的审计确认清单）。
3. consumer 的 `_consume_once` 抽取是否保持了原循环的崩溃恢复语义（processing 列表滞留消息由启动时 `_recover_stale_processing` 恢复，未改动）。
4. `ensure_default_users.py` 新契约与 `deploy.sh` 默认值、文档三者是否一致；`seed_c_curriculum.py` 的 `CURRICULUM_OWNER` 回退逻辑是否满足导入场景。
5. 部署脚本拒绝裸 IP 是否会阻断任何已知的合法部署路径（按现有文档，systemd/Docker 两方案均以域名为前提）。

### 第二轮修正后的复核结果（供 k3.1 复验）

```text
TEST_REDIS_URL=redis://127.0.0.1:6379/15 pytest tests/test_consumer_integration.py
  → 6 passed（真实 Redis，独立 db15）
未设置 TEST_REDIS_URL（APP_ENV=development）pytest tests/test_consumer_integration.py
  → 6 skipped，开发实例未被触碰
CREATE_DEFAULT_USERS=1 + DEFAULT_ADMIN_* 全量导出 pytest tests/test_default_users.py
  → 6 passed（环境隔离生效）
```
