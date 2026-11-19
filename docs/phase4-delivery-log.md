# 阶段 4 交付日志（供 k3.1 核验）

> 执行方：kimi-for-coding　日期：2026-11-19
> 依据：`docs/kimi-for-coding-plan.md` 阶段 4（前端业务正确性）
> 承接：阶段 3 已部署上线（服务器运行 `7cb4d93`）。未提交、未推送。

## 一、修改日志

### 4.1 判题轮询与竞赛上下文（`src/views/ProblemWorkspaceView.vue`）

- 轮询错误 watcher 改为**仅对 401/403/404 永久错误**停止轮询并释放 UI；网络错误/5xx 保留 submission ID，由 `useSubmissionPolling` 现有指数退避继续重试（此前任何瞬时错误都会停掉整个轮询）。
- 竞赛上下文加载：仅 `404/409/410`（不存在/取消）降级练习并弹出可见提示；`status !== 'ongoing'` 同样提示后按练习打开；**网络/5xx 抛错阻止工作区加载**（`loadError = '竞赛信息暂时无法加载，请稍后重试'`），不再静默把竞赛提交变成练习提交。

### 4.2 样例/正式/历史状态分离

- 新增 `viewingHistory` 判别：打开历史结果时 `polling.stop()` 并置位；轮询 `onUpdate` 在查看历史期间不写回 `currentSubmission`，历史视图不再被实时结果覆盖；新提交/样例运行自动复位。配合 4.6 的 `loadProblemSubmissions` 代际防护，快速换题时旧题记录也不会覆盖新题。

### 4.3 幂等键复用

- 新增 `nextIdempotencyKey(kind)`：以 `题号:操作:语言:代码内容` 为指纹，响应未明确返回前（成功或失败）同一逻辑操作复用同一幂等键；收到明确响应、代码变更（`watch(code)`、切语言）后清除。请求成功但响应丢失时的用户重试会命中服务端同一提交，不再产生重复提交。

### 4.4 会话与认证（`src/stores/session.ts`、`src/router/index.ts`、`src/api/client.ts`、`src/components/AppHeader.vue`）

- session 新增 `degraded` 状态：初始化遇网络/5xx 时置位且保持未初始化，下次导航自动重试；路由守卫对 `requiresAuth` 页面**不再把 degraded 当游客重定向登录页**；管理页保持严格（degraded 一律回 `/problems`）。
- `client.ts`：刷新请求的瞬时失败不再清除内存 Access Token（只有刷新凭据被 401/403 拒绝才经 `authFailureHandler` 清理会话）。
- 退出登录：`logout()` 错误向上传播但本地会话必然清理；AppHeader 按结果区分提示——服务端撤销成功显示"已退出登录"，请求失败显示"网络异常：已在本机退出，服务端会话可能仍有效"。

### 4.5 相邻题接口（后端 + 前端）

- 新增 `GET /api/v1/problems/{id}/neighbors`（按发布题目 id 排序返回 `prev/next/index/total`），服务/路由/响应模型齐备并有 API 测试；前端工作区用它替换原先"只取前 100 题 ID"的做法，修复第 100 题之后上一题/下一题失效；竞赛/学习计划上下文仍用各自完整题目列表。首末题给出"已经是第一题/最后一题"提示。

### 4.6 竞态代际防护

- `SubmissionListView`：关闭详情时递增 `detailGeneration` 使在途请求失效；轮询刷新校验 `selectedSubmission.id` 与代际，杜绝 A→B 覆盖和关闭后回填。
- 管理端：学习计划编辑（`openEdit`）、参赛名单（`openParticipants`）、测试数据上传（`handleUpload`，含上传中切换题目的保护）增加代际/归属校验。

### 4.7 组件测试

- 引入 `@vue/test-utils` + `happy-dom`（jsdom 31 与当前 Vitest 环境不兼容，实测会在环境层报错；happy-dom 稳定）。
- 新增/更新：`session.spec.ts`（degraded 置位与恢复）、`router.spec.ts`（degraded 不重定向、degraded 禁入管理页）、`appHeader.spec.ts`（退出成功/失败双语义，mock element-plus 与路由）。

## 二、最终验证

```text
pytest 全量（TEST_REDIS_URL=redis://127.0.0.1:6379/15）:
  190 passed, 19 skipped, 4 warnings        # 阶段3部署时 189；净增 1 项相邻题测试
ruff app judge tests scripts:  All checks passed!
mypy app judge scripts:         Success: no issues found in 79 source files
Vitest:                        6 files, 24 passed（阶段3时 19）
前端 build:                    ✓ built in 13.58s
git diff --check:              通过
```

## 二之二、k3.1 核验后的修正（第二轮）

k3.1 核验发现 2 个 P1 + 2 个 P2，已全部修正：

| 问题 | 修正 |
| --- | --- |
| [P1] 刷新瞬时失败仍抛原始 401 → 会话被归类为永久未登录（已复现 degraded=false） | `client.ts`：`request()` 仅在刷新错误为 401/403 时调用 authFailureHandler 并抛原始 401；网络/超时/5xx 改为**传播刷新错误本身**，`session.ts` 据此进入 degraded |
| [P1] `clearSession()` 未清除 degraded（已复现 degraded=true 后收到 401 仍滞留） | `clearSession()` 统一重置 `degraded=false`；新增 `authRefresh.spec.ts` 三个场景测试（刷新网络失败→degraded；degraded→刷新 401→永久清除；刷新 403→永久登出） |
| [P1] `catch` 无条件 `clearPendingKey()`，响应丢失后重试生成新键 → 可能重复提交 | 新增 `isSubmissionResponseUnknown()`（网络/0、408、5xx、非 ApiError 视为未知）；runSample/submitCode 仅在**明确拒绝**时清除键，未知时保留并提示"网络异常：提交结果未知，请重试同一操作"；format.spec 补判定测试 |
| [P2] `openCreate()` 不递增 editGeneration，旧详情响应可覆盖新建表单 | `openCreate()` 递增代际；openEdit 的 catch/finally 也按代际生效 |
| [P2] `loadNeighbors()` 依赖旧 contest/plan 值提前返回且响应无代际校验 | 改为按 `route.query` 判断上下文；响应按 `loadGeneration` 校验，从竞赛/计划切回练习可正确加载，快速换题不串 |

**修正后验证**：本地全量 `190 passed, 19 skipped`；Vitest `29 passed`（净增 5 项认证链/判定测试）；ruff/mypy/build 全绿。未提交推送。

## 二之三、k3.1 复验后的修正（第三轮）

| 问题 | 修正 |
| --- | --- |
| [P2] `loadNeighbors` 可能先返回写入 `neighbors`，随后 `loadWorkspace` 在题目请求完成后又执行 `neighbors.value = null`，间歇性清空相邻题 | `neighbors.value = null` 移到 `loadWorkspace()` 开头（任何 await 之前、generation 递增之后），并行的相邻题响应不再被后续清除 |

**修正后验证**：`bun run build` 通过；Vue SFC 时序由代码结构保证（清空前置于所有异步点）。未提交推送。

## 三、未覆盖项

1. 工作区大改未做浏览器端 E2E 实测；竞赛降级提示文案、历史隔离、相邻题导航建议由浏览器走查确认。
2. Monaco/Element Plus 全量挂载测试未引入（当前为关键逻辑组件级测试）。
3. 计划中的 URL 同步筛选、其余 backlog（无障碍、竞赛列表统计等）不在本阶段。
4. 阶段 4 未提交推送，待 k3.1 核验。

## 四、变更集（相对阶段 3 部署提交 be98dde）

```text
M  src/api/client.ts              M  src/stores/session.ts
M  src/router/index.ts            M  src/components/AppHeader.vue
M  src/views/ProblemWorkspaceView.vue   M  src/views/SubmissionListView.vue
M  src/views/admin/AdminStudyPlansView.vue  M  src/views/admin/AdminContestsView.vue
M  src/views/admin/AdminProblemsView.vue
M  src/api/problems.ts            M  src/types/index.ts
M  app/api/v1/problems.py         M  app/services/problems.py
M  app/schemas/problem.py         M  tests/test_problem_api.py
M  tests/unit/session.spec.ts     M  package.json  M  bun.lock
?? tests/unit/router.spec.ts      ?? tests/unit/appHeader.spec.ts
?? docs/phase4-delivery-log.md
```
