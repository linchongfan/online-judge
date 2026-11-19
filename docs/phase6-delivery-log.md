# 阶段 6 交付日志（供核验）

> 执行方：kimi-for-coding　日期：2026-11-19
> 依据：`docs/kimi-for-coding-plan.md` 阶段 6（CI、可维护性与体验 backlog）
> 承接：阶段 5 已部署（`54f8fbc`，日志 `2246df6`）。本阶段未提交、未推送（核验后执行）。

## 一、修改日志

### 6.1 GitHub Actions（`.github/workflows/ci.yml`，新增）

四个 job：

1. **backend**：Ruff、mypy、pytest；带 Redis 7 服务，`TEST_REDIS_URL=.../15`。
2. **integration**：MySQL 8.4 + Redis 服务；在 MySQL 上执行 `alembic upgrade head`，
   并用 SQLAlchemy Inspector 断言 `outbox_message.nonce/next_attempt_at` 存在、
   三个长文本列为 `MEDIUMTEXT`；随后运行 dispatcher、队列容量、验证码并发、
   消费者集成、题库统计与上传相关测试。
3. **frontend**：Bun 1.4.2，`bun install --frozen-lockfile` 后依次运行
   `lint`、`typecheck`、`test`、`build`、`budget`。
4. **judge-vm**：仅 `workflow_dispatch` 触发，`runs-on: [self-hosted, linux, judge-vm]`，
   运行 `test_isolate_meta.py`、`test_linux_isolate.py` 与破坏性
   `-m linux_judge_vm`；可选输入 `e2e_base_url` + secrets 触发
   `scripts/e2e_judge_acceptance.py` 四语言验收。危险测试不进入普通 PR 流水线。

### 6.2 ESLint + Vue 可访问性（`eslint.config.js`、`package.json`）

- 新增 flat config：`@eslint/js` recommended + `typescript-eslint` recommended +
  `eslint-plugin-vue` essential + `eslint-plugin-vuejs-accessibility` recommended。
- 新增脚本：`lint`、`typecheck`（独立 `vue-tsc --noEmit`）、`budget`、`verify`。
- 修复的违规（均为真实可访问性/正确性问题，非纯格式）：
  - 竞赛列表标题 `<h3 @click>` 改为可聚焦的 `<button class="title-link">`，保留原视觉；
  - 题目管理隐藏文件输入补充 `aria-label`；
  - 两道自定义分隔条（已具备 `role="separator"`、`tabindex` 与键盘处理）添加
    带理由的 `eslint-disable-next-line`，因为规则不认识可聚焦 splitter 模式；
  - 竞赛上下文错误补充 `cause`；删除无用赋值、无用导入与空 try/catch。

### 6.3 测试隔离（`tests/redis_testing.py`、`tests/conftest.py`、`tests/test_test_isolation.py`）

- 新增 `resolve_test_redis_url()`：优先 `TEST_REDIS_URL`；否则把配置的 Redis
  URL 改到逻辑库 **15**；若解析结果为 db 0 直接拒绝运行。
- conftest 新增 autouse fixture：覆盖 `settings.redis_url`，并重置
  rate limiter / 验证码 / 队列容量已缓存的客户端，确保没有任何测试写入应用 db 0。
- `client` 夹具清理键前同样拒绝 db 0。
- 新增 3 项隔离测试：默认解析不为 db 0、显式 `TEST_REDIS_URL` 优先、
  无库路径的 URL 自动落到 db 15。

### 6.4 开发基础设施与文档

- `docker-compose.yml`：MySQL/Redis 端口改为 `127.0.0.1` 绑定，并在文件头注明
  固定占位凭据仅供本地开发、不得对公网开放。
- `README.md`：
  - 测试数字更新（199 passed / 19 skipped；前端 29）；
  - 检查命令补 `scripts` 范围、`lint`、`typecheck`、`budget`、`verify`；
  - CI 描述改为指向真实 workflow，明确 `judge-vm` 仅在手动触发的一次性判题机运行；
  - 本地 JDK 由 Corretto 8 改为 OpenJDK 17（JDK 8 的 javac 不支持 `--release 8`）。
- `docs/admin-problem-guide.md`：上限与代码对齐——
  测试点 101（202 文件 ÷ 2）、ZIP 50 MB、解压总量 256 MB（单文件 8 MB、压缩比 200 不变）。

### 6.5 体积预算与清理

- 新增 `scripts/check_bundle_budget.mjs`：初始 `index-*.js` ≤ 1.6 MB、
  单 chunk ≤ 4 MB、全部 JS ≤ 8 MB；`bun run budget` 在构建后执行。
- 删除未跟踪的原型数据 `src/data/{mock,solutions,solutionVariants}.ts`
  （全仓库无引用，且从未纳入版本控制）。
- 未实施（明确留待后续）：Playwright/axe 浏览器 E2E、OpenAPI 生成 TS 类型、
  大 SFC 拆分、Element Plus/Monaco 按需加载。理由：前两项需要完整前后端与浏览器
  运行环境，拆分与按需加载属于大范围重构，不宜与本阶段 CI/文档修正混在同一变更集。

## 二、验证结果

```text
pytest（TEST_REDIS_URL=.../15）:  199 passed, 19 skipped, 4 warnings
pytest（不设 TEST_REDIS_URL）:   193 passed, 25 skipped（6 个消费者集成测试按设计跳过）
ruff app judge tests scripts:     All checks passed!
mypy app judge scripts:           Success: no issues found in 79 source files
bun run lint:                     通过（0 error）
bun run typecheck:                通过
bun run test:                     29 passed
bun run build:                    ✓ built in 18.02s
bun run budget:                   110 chunks, total 5,599,251 bytes, entry index-DHEqiPnN.js
git diff --check:                 通过
```

## 三、未覆盖项与风险

1. **CI 尚未在 GitHub 上实际运行过**：本阶段只做了本地等价检查与 YAML 解析；
   首次推送后需观察 Actions 结果（尤其 MySQL 服务与 judge-vm 标签）。
2. `judge-vm` 需要预先注册带 `judge-vm` 标签的自托管判题机，否则该作业会一直排队。
3. 浏览器 E2E、axe、OpenAPI 类型生成未实施（见 6.5）。
4. 测试 Redis 默认落到 db 15，若某个环境已占用 db 15 需显式设置 `TEST_REDIS_URL`。
5. 前端体积预算目前只限制体积，不限制具体依赖；Element Plus/Monaco 按需加载仍在 backlog。
