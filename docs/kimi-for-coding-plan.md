# online-judge 审查结论与 kimi-for-coding 执行计划

> 审查日期：2026-11-18  
> 审查方式：静态、只读代码审查。未运行测试、未连接线上环境，运行时影响仍需按本文验收步骤复现。

## 背景与总体评价

本地 `origin` 指向 `linchongfan/online-judge`。审查覆盖 Vue/FastAPI 前端后端、Celery/Redis 判题链、Linux/Windows 沙箱、测试及部署脚本。

项目已有不少良好基础：不可变测试数据版本、事务 Outbox、结果签名、令牌刷新、ZIP 安全校验和较多后端测试。当前主要问题是若干安全与正确性缺陷混在已有架构中，且缺少真实 Redis/MySQL、组件级和沙箱端到端门禁。

**执行建议：让 kimi-for-coding 先只领取阶段 1，提交小 diff 和完整测试证据；审核合并后再依次领取后续阶段。禁止一次性实施全部阶段。**

## 一、优先审查结论

| 优先级 | 已确认问题 | 代码证据与影响 |
| --- | --- | --- |
| P0 | 默认布局测试点被公开 | `app/api/v1/admin.py:425-435` 用 `category != "hidden"` 设置样例，导致 `default` 也成为公开样例；`app/services/problems.py:111-123` 会返回其输入输出。应只公开 `category == "sample"`。 |
| P0 | Redis 结果消费者解析错误 | `app/tasks/consumer.py:97-108` 对 `BRPOPLPUSH` 的单个 bytes 返回值使用 `item[1]`，会只取第二个字节或触发异常，结果可能反复恢复、无法正常落库。 |
| P0 | 生产部署默认创建固定管理员 | `deploy/linux/deploy.sh:119-123` 默认启用建号，`scripts/ensure_default_users.py:29-36` 包含公开固定密码。新部署未及时改密即可获得已知管理员凭据。 |
| P0 | Linux isolate 元数据解析与固定版本不兼容 | `judge/linux_isolate.py:528-534` 按 JSON 解析，而项目固定的 isolate 2.0 输出 `key:value`；`:446-480` 还使用错误或不一致的键，并把 `SG` 当成超时。现有 `tests/test_linux_isolate.py:198-226` mock 掉真实解析，未发现该问题。 |
| P0 | 定制 rootfs 没进入实际执行路径 | `judge/linux_isolate.py:260-264` 构造 rootfs mount，但 `:356-379` 实际只挂载 `/box` 和工具链，且未传 `--no-default-dirs`，文档声称的最小 rootfs 边界不成立。 |
| P0（条件性） | Windows 生产判题不能视为安全沙箱 | 看门狗默认以 SYSTEM 最高权限运行（`scripts/install_judge_watchdog.ps1:13-16,39-44`），受限令牌仍保留原用户身份（`judge/windows_sandbox.py:553-584`）。若未启用 Windows 生产后端则不影响当前部署；在完成重新设计和实测前应 fail closed。 |
| P1 | 正式提交存在隐藏输入经共享目录和样例 stderr 泄露的路径 | `judge/worker.py:83-96,107-134` 所有测试点复用可写目录，是否返回 stderr 只看当前 case；`:196-214` 返回首个失败点诊断，测试点顺序又无保证。正式提交应一律不返回用户程序 stderr，并为每个测试点使用独立 scratch 目录。 |
| P1 | Outbox 投递和任务状态存在竞态 | `app/tasks/dispatcher.py:35-76` 无原子领取且每次生成新 nonce；API 即时投递和维护扫描可重复发送。永久 payload 错误会无限重试，sweeper 与结果消费者也缺少一致的状态迁移约束。 |
| P1 | 验证码尝试次数与消费非原子 | `app/services/verification.py:46-64` 使用 GET 后 SET/DEL，并发请求可共享旧 attempts 或重复消费。限流的 INCR/EXPIRE 也应原子化。 |
| P1 | 前端抵消轮询退避、竞赛加载失败变练习 | `src/composables/useSubmissionPolling.ts:94-110` 本可退避，但 `src/views/ProblemWorkspaceView.vue:349-356` 遇任何错误都停止；`:314-330` 吞掉竞赛请求所有异常，后续 `:248` 提交可能不带 contestId。 |
| P1 | 数据库字段与接口限制不一致 | 源码允许 65,536 UTF-8 字节，但 MySQL `TEXT` 最多 65,535 字节；题解、学习计划也存在 TEXT 容量风险。SQLite 测试无法发现。 |
| P2 | 明显扩展性与工程化短板 | 题库逐题多次统计 SQL；竞赛每次终态全量重算；测试数据上传在 async 路由同步解压/fsync；前端仅工具函数测试，无组件/E2E；仓库无 CI；生产 Docker 资产和部分补丁不在仓库。 |

后续 backlog 还包括：

- 第 100 题之后上一题/下一题失效。
- 样例、正式提交、历史结果串态。
- 会话初始化把刷新临时故障当成未登录。
- 管理详情旧响应覆盖新对象。
- 公开标签统计未发布题，多个 solved/Worker 统计口径不一致。
- 无障碍名称、标签页语义和文本对比度不足。
- README 测试数、CI 描述及出题限制与代码不一致。

## 二、交给 kimi-for-coding 的执行约束

1. **严格分阶段，一阶段一个独立变更集或 PR；先完成并验收当前阶段，再进入下一阶段，禁止一次性大重构。**
2. 开始前运行现有测试、typecheck、build 并记录基线；已有失败要原样报告，不得通过删测试、放宽断言或提高警告阈值“修复”。
3. 每项缺陷先添加能复现问题的回归测试，再改实现；保留现有 API 兼容性，确需 breaking change 时单独说明。
4. 不读取或提交真实 `.env` 和密钥，不操作线上数据库，不轮换线上账户，不部署。历史数据修复先输出审计清单和可回滚迁移方案。
5. `linux_judge_vm` 标记的破坏性测试只能在一次性 Linux 判题 VM 运行；不得在开发机或共享 Runner 上执行。Windows 沙箱首轮只做生产禁用和文档告警，不在缺少真实隔离验收的情况下宣称已修复。
6. 优先复用现有 `TestDataService`、`useSubmissionPolling`、`ApiError`、`scripts/create_admin.py`、`scripts/e2e_judge_acceptance.py`，不要另起重复框架或引入无实际收益的 repository 层。
7. 除非用户另行要求，不提交、不推送、不创建 PR；在工作树中完成变更并汇报 diff 与验证结果。

## 三、分阶段实施计划

### 阶段 1：先修保密性与线上可运行性

#### 1.1 测试点公开范围

修改：`app/api/v1/admin.py`、`app/services/problems.py`、相关 API/ZIP 测试。

- 将 `is_sample` 和 `sample_count` 统一为仅 `category == "sample"`。
- 增加 `sample/`、`default/`、根目录、隐藏目录四类 ZIP 的 API 回归测试；断言题目详情只返回 sample，default/hidden 的输入输出均不可见。
- **不得直接把所有历史 `is_sample=true` 改成 false。** 当前记录不足以可靠还原原目录类别：实现历史版本审计/修复命令，优先依据可验证的原始数据；无法确认时提示重新上传或采用“保密优先”的显式人工流程，并记录影响范围。

#### 1.2 Redis 结果消费

修改：`app/tasks/consumer.py`，新增真实 Redis 集成测试。

- 直接处理 `BRPOPLPUSH` 返回的 bytes；兼容 `decode_responses` 时可用统一转换，但不能按 tuple/list 取值。
- 在 `.get()` 前验证 JSON envelope 为 dict，非法类型进入死信并 ack，避免毒消息循环。
- 测试 started/终态落库、ack、处理中队列崩溃恢复、非法 JSON、非对象 JSON、错误签名、临时 DB 错误有界重试与死信。

#### 1.3 生产初始化与 HTTPS 配置

修改：`deploy/linux/deploy.sh`、`scripts/ensure_default_users.py`、`deploy/linux/configure.sh`、部署文档。

- 默认关闭默认管理员和测试用户创建；生产复用交互式 `scripts/create_admin.py`，测试账号只能显式 opt-in，禁止固定生产密码。
- 保留 `app/core/config.py` 的生产 Secure Cookie 校验；纯 IP HTTP 不作为生产模式支持，改为明确要求 HTTPS 或受控 TLS 终止，不通过关闭安全校验来“修复”部署。
- 文档增加已有部署的人工检查项：轮换或删除默认账户并撤销有效会话。代码 agent 不直接执行这些线上操作。

### 阶段 2：判题沙箱与隐藏数据边界

修改重点：`judge/linux_isolate.py`、`judge/worker.py`、`judge/sandbox.py`、`judge/config.py`、`tests/test_linux_isolate.py`、`tests/test_linux_judge_vm.py`、Windows 生产配置与文档。

- 按 isolate 2.0 的真实 `key:value` 格式实现解析及数值转换；正确读取 `time`、`time-wall`、cgroup 内存键，明确映射 `TO -> TLE`、`ML -> MLE`、`SG -> RE`、内部错误 `SE`，未知状态 fail closed。
- 解析测试使用真实文本 fixture，禁止 mock `_read_meta` 本身；覆盖空文件、坏行、重复键、非数值、各终止状态。
- 实际执行命令启用 `--no-default-dirs` 并按 isolate 2.0 语义显式挂载定制 rootfs、任务目录和工具链；增加命令断言和沙箱内视图验收，证明所需运行库可用且宿主非必要目录不可见。
- 修正 Linux VM fixture，使其显式继承并断言 production + isolate，而不是默认 development/local。
- 正式提交不返回用户程序 runtime stderr；仅独立样例运行可返回脱敏诊断。每个测试点使用全新 scratch 目录，编译产物以只读方式共享，测试点排序确定化但不把排序当安全边界。
- 添加对抗回归：隐藏点保存 stdin、后续样例读取并写 stderr，正式提交响应仍不得包含隐藏数据。
- Windows 后端在 production 启动时直接拒绝并给出清晰错误，直到另有 AppContainer、专用容器或 VM 方案及真实 ACL、网络、多进程、内存验收。

### 阶段 3：判题可靠性与数据一致性

修改重点：`app/tasks/dispatcher.py`、`app/tasks/results.py`、`app/tasks/sweeper.py`、`app/models/entities.py`、Alembic、`app/services/submissions.py`、`app/services/verification.py`、`app/services/rate_limit.py`。

- 为 Outbox 增加带租约的原子 claim/条件更新，持久化每个 task attempt 的稳定消息 ID/nonce；采用 **at-least-once + 消费/执行去重**，不要声称能做到 broker 与 DB 的 exactly-once。
- 区分永久 payload/数据错误和临时 broker 错误：永久错误进入明确失败态；临时错误指数退避、有上限并告警，不再每 5 秒无限重试。
- 统一结果消费者与 sweeper 对 task/submission 的条件状态迁移或行锁，旧 attempt 不得覆盖新 attempt；队列超时判断考虑正常积压，避免健康 Worker 下重复排队。
- 用 Redis Lua 原子完成验证码比较、失败计数、消费及限流窗口；补并发测试，证明 5 次上限和一次性消费成立。
- 队列容量采用原子预留和释放；同幂等键并发唯一冲突应回滚后返回已有提交并校验 payload 一致，而不是映射成 503。
- 统一源码、题解、计划描述的字符/字节限制与 MySQL 字段类型；需要扩容时使用 Alembic 迁移到合适 TEXT 类型，测试 utf8mb4 多字节边界和 upgrade/downgrade 策略。

### 阶段 4：前端业务正确性

修改重点：`src/views/ProblemWorkspaceView.vue`、`src/api/client.ts`、`src/stores/session.ts`、`src/router/index.ts`、`src/views/SubmissionListView.vue` 及相关管理详情页。

- 轮询仅对 401/403/404 等永久错误停止；网络/5xx 保留 submission ID、显示重试状态并沿用现有退避。
- 只有明确的取消、归档等业务状态才可降级练习；网络/5xx 时阻止竞赛提交并提示重试，任何降级都明确显示上下文。
- 将样例运行、正式提交、历史预览拆成明确状态或判别联合；查看历史时停止或隔离当前轮询，避免旧响应覆盖。
- 一个逻辑提交在响应未知时复用幂等键，收到明确响应或用户修改代码/操作类型后再更换。
- 区分会话未认证与刷新服务暂时不可用，degraded 状态不按游客重定向；退出请求失败只能提示“已在本机退出”。
- 后端提供相邻题 ID 或按位置分页，修复 100 题后的导航；用请求代际或 AbortController 修复换题、计划编辑、参赛名单、上传和提交详情竞态。
- 引入 `@vue/test-utils` + happy-dom/jsdom，为上述场景写组件测试，不再只测 composable 和工具函数。

### 阶段 5：性能与部署可复现性

先测量，再优化。

- 将 `app/services/problems.py` 的逐题统计改为当前页 problem IDs 的集合式 GROUP BY；用查询计数测试确保不再随题数线性增长。
- 将 `app/services/contests.py` 的结果到达路径改为当前用户/题增量更新，排行榜可异步批量重排；保留管理员全量对账并改成批量查询。先用代表性数据 benchmark，避免改变 ACM 罚时口径。
- 把 ZIP 解压/fsync 移出 FastAPI 事件循环，使用受控线程池或后台任务并限制并发；事务化版本分配、失败清理孤儿目录，统一前端、Nginx、后端超时。
- 将线上使用的 Dockerfile、Compose、patch 脚本纳入版本控制，消除对 `/opt/xinbaoyan-docker` 隐式补丁的依赖；从干净 checkout 构建并冒烟。
- “Celery payload 不再携带所有隐藏数据、改传版本引用”和“数据库存相对存储键”先出独立设计，确认判题节点共享存储或签名 URL、缓存和迁移方案后再实施，不在本阶段顺手改架构。

### 阶段 6：CI、可维护性与体验 backlog

- 新增 GitHub Actions：Ruff、mypy、pytest、Vitest、独立 `typecheck`、production build；增加 MySQL 8.4 + Redis 集成 job，执行 Alembic 和关键并发/消费测试。
- 沙箱四语言矩阵放独立、受控 Linux judge job；复用 `scripts/e2e_judge_acceptance.py` 验证 C/C++/Java/Python 的 AC、WA、CE 及 TLE/MLE/RE，不把危险测试放普通 PR Runner。
- 增加 ESLint/Vue 可访问性规则、Playwright 关键链路和 axe；先覆盖登录、做题、竞赛、管理上传发布，再逐步扩大。
- 修正文档中的 CI 描述、测试数量、ZIP 限制和 JDK 版本；开发 Redis/MySQL 端口绑定 loopback，测试夹具强制独立测试 DB，禁止清理非测试 Redis。
- 最后再做 OpenAPI TS 类型生成、大 SFC/router 拆分、未引用原型数据清理、Element Plus/Monaco 按需加载和 bundle 预算；这些不得混入 P0/P1 修复 diff。

## 四、每阶段验收

基础门禁：

```bash
python -m pytest
python -m ruff check app judge tests
python -m mypy app judge
bun run test
bun run build
```

静态检查扩展到 `scripts` 前先记录现状并单独修复，避免把大量历史告警混入功能变更。

专项验收：

1. 四类 ZIP 上传后，仅 sample 出现在题目详情；历史数据迁移有审计清单且可回滚。
2. 真实 Redis 中，消费者能处理 bytes 结果、更新提交、ack，并在崩溃后恢复；非法消息进入死信而非无限阻塞。
3. 新生产部署默认不创建任何固定账号；HTTP/IP 配置不会绕过生产安全校验。
4. isolate 真实 meta fixture 的 TLE/MLE/RE/SE、运行时间和峰值内存全部正确；一次性 VM 中验证 rootfs 视图及四语言判题。
5. 多 dispatcher、结果消费者与 sweeper 并发测试下，旧结果不能覆盖新 attempt，永久错误不会无限停留 PENDING。
6. 做题页网络瞬断可恢复；竞赛上下文加载失败绝不静默转为练习；样例结果不会冒充正式结果。
7. MySQL 迁移及多字节边界通过，题库查询数固定，竞赛增量计分与全量对账结果一致。
8. 每阶段报告实际执行的命令、通过或失败结果和未覆盖项；未运行的真实沙箱、浏览器或部署验收必须明确标注，不能声称“全部验证通过”。

## 五、可直接交给 kimi-for-coding 的首轮指令

```text
请阅读 docs/kimi-for-coding-plan.md，并只执行其中“阶段 1：先修保密性与线上可运行性”，不要提前实施阶段 2—6。

要求：
1. 先运行并记录现有 pytest、Vitest、typecheck/build 基线；已有失败原样报告。
2. 将 1.1、1.2、1.3 分成三个独立、易审查的变更集；每项先写回归测试再修实现。
3. 历史测试数据不得无依据批量更新 is_sample；只实现可审计、可回滚的处理方案。
4. Redis 修复必须用真实 Redis 集成测试验证，不只 mock brpoplpush。
5. 不修改生产安全校验来容纳 HTTP，不操作线上账户、数据库或部署，不运行破坏性沙箱测试。
6. 不提交、不推送。完成后汇报修改文件、测试结果、未验证项及需要人工处理的线上事项。
```
