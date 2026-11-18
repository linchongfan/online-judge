# 阶段 2 交付日志（供 k3.1 核验）

> 执行方：kimi-for-coding　日期：2026-11-18
> 依据：`docs/kimi-for-coding-plan.md` 阶段 2（判题沙箱与隐藏数据边界）
> 承接：阶段 1（已验收通过）。未提交、未推送；未操作线上环境。
> 前置事实核查：下载并比对仓库固定的 IOI isolate v2.0 源码
> （`deploy/judge-linux/bootstrap.sh` 固定 `v2.0` tag），以下实现均以该版本
> 的真实行为为准，不再依赖文档转述。

## 一、isolate v2.0 源码核查结论（本轮修复的事实基础）

| 核查项 | 结论 | 影响 |
| --- | --- | --- |
| meta 文件格式 | 纯 `key: value` 行（如 `time:1.234`、`cg-mem:8192`、`status:RE`），**成功运行没有 `status:` 行**，另有 `exitcode`/`exitsig`/`cg-oom-killed`/`message`/`killed` | 原 `_read_meta` 按 JSON 解析必然失败 → 内存/终止原因全部丢失；已重写 |
| 状态码 | `TO`（墙钟/CPU 超时）、`RE`（非零退出，带 `exitcode`）、`SG`（信号终止，带 `exitsig`）、`XX`（内部错误，带 `message`）；**v2.0 不产出 `ML`/`OL`**，内存超限通过 cgroup OOM 体现为 `cg-oom-killed:1` | 原实现把 `SG` 误判为 TLE、把不存在的 `cg-mem-peak-kib`/`wall-time` 当键；已按真实映射重写 |
| 内存键 | `cg-mem`（cgroup memory.peak，KiB），另有 `max-rss` | 已按 `cg-mem → max-rss` 优先级读取 |
| `--no-default-dirs` | **v2.0 支持**（`-D`）。默认规则集绑定的是**宿主** `/bin /dev /lib /lib64 /usr` + `box → /box(rw)` + `/proc` + tmp | 原实现未使用该参数，沙箱可见宿主系统目录（P0）；已启用 `-D` 并从 rootfs 显式提供系统目录 |
| `--dir` 标志 | v2.0 标志集仅 `rw noexec fs maybe dev tmp norec`，**没有 `ro`**（不写 rw 即只读）；`inside` 路径不允许 `/`（`sanitize_dir_path` 拒绝根路径） | 原实现 `--dir=/toolchains=...:ro` 会被 isolate 以 "Unknown directory option" 拒绝；rootfs 不能整体绑到 `/`，改为逐目录绑定；均已修正 |
| `--quota`、`-D`、`--cg-mem` | v2.0 均支持 | 保留原用法；部署文档中"补丁移除 --quota/--dir=:ro"的描述与 v2.0 不符，属旧构建遗留说法 |

## 二、修改日志

### 2.1 isolate 元数据解析与状态映射（`judge/linux_isolate.py`）

- 新增纯函数 `parse_isolate_meta(text)`：按 v2.0 真实 `key: value` 行解析，数字转 int/float，`message` 值可含冒号，容忍空行/坏行，重复键取最后值。
- 新增纯函数 `classify_isolate_meta(meta, *, proxy_exceeded, proxy_error)`：完整状态映射——`TO→WALL_TIME_LIMIT`、`cg-oom-killed/ML→MEMORY_LIMIT`、`OL→OUTPUT_LIMIT`、`RE/SG→NORMAL+程序退出码`（`SG` 无 `exitsig` 时强制 `exit_code=-1`，杜绝信号杀死被判 AC）、`XX→SANDBOX_ERROR`（含 message）、**未知状态 fail closed 为 SANDBOX_ERROR**；无 `status` 行视为正常完成。运行时间取 `time`（CPU 秒）优先、`time-wall` 次之；峰值内存取 `cg-mem` 优先、`max-rss` 次之。
- `_read_meta` 改为读取真实文件 + `parse_isolate_meta`；meta 文件名由误导性的 `meta.json` 改为 `meta.txt`。
- `execution_info`/`memory_usage_kb` 改为调用纯函数，不再硬编码错误键名。

### 2.2 沙箱文件系统边界（`judge/linux_isolate.py`）

- spawn 命令启用 `--no-default-dirs`，显式规则： `/box={work_dir}:rw`、`/bin /lib /usr`（必选）、`/lib64 /sbin /etc`（`:maybe`）均来自 **rootfs** 而非宿主、`/toolchains={toolchain_root}`（默认只读）、`/dev=/dev:dev`、`/proc=proc:fs`、`tmp:tmp`——与 isolate 默认规则集同构但系统目录全部源自 rootfs。
- 删除 `--dir=...:ro`（v2.0 无此标志，会直接导致 isolate 退出）。
- `_sandbox_argv(argv, box_dir)`：新增把当前任务目录前缀映射为 `/box` 的逻辑，修复原生语言（C/C++）运行命令使用宿主绝对路径在沙箱内不可达的问题。
- `_build_mounts` 不再包含无法绑定的 `/`→rootfs 映射，仅保留工具链 1:1 映射。

### 2.3 程序退出码透传（`judge/sandbox.py`、`judge/process.py`）

- `SandboxExecutionInfo` 新增 `exit_code: int | None`。
- `ProcessRunner.run` 在后端给出权威程序退出码时（isolate meta 的 `exitcode`/`exitsig`）覆盖监督进程自身退出码，修复"RE/SG 程序结果被误判"的链路。

### 2.4 Worker 隐藏数据边界（`judge/worker.py`、`judge/protocol.py`、`app/tasks/dispatcher.py`、`judge/celery_worker.py`）

- `JudgeRequest` 新增请求级 `is_sample_run: bool = False`；dispatcher 在 Celery payload 中携带 `is_sample_run`；worker 入口透传。**安全边界：正式提交（`is_sample_run=False`）一律不返回用户程序运行期 stderr——即使该 case 本身是公开样例**（正式提交中样例与隐藏点同批执行，stderr 可能回显隐藏输入）。仅交互式样例运行返回脱敏 stderr。
- 每个测试点在独立 scratch 目录执行：目录在 case 运行前创建、复制编译产物（**复制而非软链**，防止篡改共享产物影响后续 case）、运行后删除；`TMP/TEMP/TMPDIR/HOME` 全部指向该 scratch 目录（原共享 work_dir 的 TMP 是把隐藏输入带给后续样例的通道）。
- 测试点按 `case_id` 数值确定化排序（保证首个失败点诊断确定；排序仅用于确定性，不当保密边界）。

### 2.5 Windows 后端 fail closed（`judge/config.py`）

- `JUDGE_SANDBOX_BACKEND=windows` 且 `JUDGE_ENV=production` 时在配置阶段直接抛 `ToolchainConfigurationError`（在后端类导入/能力声明之前），即使设置 `JUDGE_FIREWALL_ACTIVE` 也无法绕过；development 模式行为不变。

### 2.6 测试

| 文件 | 变更 |
| --- | --- |
| `tests/test_isolate_meta.py`（新增，跨平台） | 15 项：解析（空/坏行/重复键/冒号消息/数字转换）与分类（TO/RE/SG/无 status/XX/未知 fail closed/ML/OL/cg-oom-killed/代理超限合并/内存优先级）。 |
| `tests/test_linux_isolate.py`（Linux-only） | meta 测试改为**写入真实 `key:value` 文本并走真实 `_read_meta`**（不再 mock 解析本身）；新增 SG/成功无 status/OO 映射测试；spawn 测试断言 `--no-default-dirs`、rootfs 规则集、无 `:ro`、`/box` 与工具链 argv 映射。 |
| `tests/test_judge_worker.py` | 原样例 stderr 测试改为 `is_sample_run=True`；新增 4 项：正式提交样例 case 不回显 stderr、**对抗回归**（隐藏点暂存 stdin→后续样例经 stderr 带出，断言不泄露且 stash 不跨 case 存活）、每 case 独立 scratch（无串扰）、确定化排序。 |
| `tests/test_windows_sandbox.py` | 3 项旧测试（生产+Windows 允许/提示）改写为 fail-closed 契约；策略层防火墙提示行为改用桩后端保留覆盖。 |
| `tests/test_judge_config.py` | 新增：production+windows 在任何平台均被拒绝。 |
| `tests/test_linux_judge_vm.py` | fixture 显式继承 `os.environ` 并断言 `JUDGE_ENV=production` + `LinuxIsolateBackend`（不再静默退化 local）；样例请求补 `is_sample_run=True`；新增 VM 对抗回归（隐藏→样例 stderr 带出）。 |

## 三、TDD 证据（旧代码上必失败）

临时 `git stash` 还原旧 `judge/worker.py` + `judge/protocol.py` 后运行新测试，5 项按预期失败：

```text
FAILED test_sample_run_keeps_sanitized_stderr                  （旧协议无 is_sample_run）
FAILED test_official_submission_sample_case_does_not_echo_stderr
FAILED test_official_submission_cannot_smuggle_hidden_input_to_later_sample
FAILED test_each_case_runs_in_fresh_scratch_directory          （旧共享目录 → CONTAMINATED）
FAILED test_cases_execute_in_deterministic_case_id_order       （旧调用方顺序）
```

恢复后全部通过。meta 解析修复的对应证据见 `test_isolate_meta.py` 全部 15 项（旧 JSON 解析对这些输入全部返回 None）。

## 四、最终验证

```text
pytest 全量（TEST_REDIS_URL=redis://127.0.0.1:6379/15）:
  159 passed, 19 skipped, 1 warning        # 阶段1验收时 139 passed / 14 skipped
ruff app judge tests scripts:  All checks passed!
mypy app judge scripts:         Success: no issues found in 78 source files
bash -n 三个部署脚本:            通过（本轮未改动部署脚本）
bun run test:                   19 passed
bun run build:                  ✓ built in 16.80s
git diff --check:               通过
```

## 五、未覆盖项（必须明示）

1. **`tests/test_linux_isolate.py`（11 项）与 `tests/test_linux_judge_vm.py` 未在本机执行**——模块级 `skipif(os.name == "nt")` 且 backend 构造在 Windows 拒绝。已做语法编译检查与逐条人工核对，**需在 Linux CI 或一次性判题 VM 上运行**（VM 套件还须 `JUDGE_VM=1` + production isolate 环境）。
2. **真实 isolate 运行时行为未验证**：命令构造按 v2.0 源码逐项核对，但 rootfs 视图（"宿主目录不可见、运行库可用"）只能在 VM 上实证。
3. Windows 后端 development 模式能力声明仍为原样（未宣称修复其隔离能力，仅阻断生产使用）。
4. 本轮未触碰 `deploy/DOCKER_DEPLOYMENT.md` 中"isolate 补丁"清单与 `patch-judge-image.sh`——rootfs/`--no-default-dirs` 变更上线后，旧镜像补丁可能与新实现冲突，需在部署阶段对照移除（建议列入阶段 5 的部署资产纳管）。

## 五之二、k3.1 核验后的修正（第二轮）

k3.1 核验发现 2 个 P0 + 2 个 P1，已全部修正：

| 问题 | 修正 |
| --- | --- |
| [P0] stdin/stdout/stderr 路径在 chroot 内不可达：isolate 在 `setup_root()` chroot 之后才由 `setup_fds()` 打开这三个路径，原实现传入宿主 `meta_dir`/`work_dir` 绝对路径，真实运行必然失败 | 三个文件改为放入任务目录（宿主侧由 proxy 读写）；命令行参数改为 `--stdin=/box/.judge-sandbox-stdin` 等 `/box` 路径；新增 spawn 测试断言；`cleanup()` 补充 stdin 文件清理 |
| [P0] `cleanup()` 删除后端状态后才调用 `execution_info()`：Linux cleanup 删除 `_states` 与 meta 目录，`execution_info` 必然抛 `Unknown Linux sandbox process`（已用桩后端最小复现） | `ProcessRunner.run` 重构：在 try 内、finally 的 `cleanup()` 之前采集 `execution_info()`；新增 `tests/test_process_runner.py` 用调用顺序断言锁定（`["execution_info", "cleanup"]`） |
| [P1] 输出代理：文件尚未创建直接报错、普通文件 EOF 即退出漏读后续输出、`stop_event` 无人消费导致硬输出上限不能及时停止程序 | `_OutputProxy` 重写：创建前有限等待（10s 超时报错）、EOF 后继续轮询直至 `finish()`/停止事件、`finish()` 置完成信号使泵线程可 join；`SandboxBackend` 新增 `output_stop_event()`，`ProcessRunner` 轮询循环消费该事件立即终止；新增 `tests/test_output_proxy.py` 3 项 + Runner 终止及时性测试 |
| [P1] meta 缺失/空文件被当作正常完成（`_read_meta(...) or {}`） | `execution_info` 区分：isolate 被监督杀进程（returncode<0，超时/输出/内存路径）时无 meta 属预期 → 中性 accounting；isolate 自行结束却无 meta → 构造 `status:XX` fail closed。空文件同样落入 XX 分支 |

**修正后验证**：全量 `164 passed, 19 skipped`（净增 5 项生命周期/代理测试）；此前复现 `RuntimeError: sandbox state already deleted by cleanup` 的最小脚本现输出 `exit_code=0 cleaned=True`；ruff/mypy/Vitest/build 全绿。

## 五之三、修正后的剩余未覆盖项

1. `tests/test_linux_isolate.py` 与 VM 套件仍需 Linux 环境执行（本机 Windows 跳过）；`--no-default-dirs` 挂载视图与四语言判题仍需一次性 VM 实证。
2. `execution_info` 的 meta 缺失分支中"被监督杀进程"的判定依赖 `isolate.returncode < 0`，该路径只能在真实 isolate 上验证。

## 五之四、k3.1 第二轮复验后的修正（第三轮）

k3.1 复验发现 2 个剩余 P1，已全部修正：

| 问题 | 修正 |
| --- | --- |
| [P1] 代理最终状态仍在采集之后完成：`execution_info()` 读取 `proxy.snapshot()` 时泵线程尚未 `finish()`，最后检测到的超限/错误会丢；Runner 的最终输出大小复查也发生在代理排空前 | `LinuxIsolateBackend.execution_info` 先调用 `proxy.finish()` 再 `snapshot()`（幂等，cleanup 重复调用无害）；`ProcessRunner` 的最终合计大小复查移到 `execution_info()` 之后。新增 3 项测试：`finish→snapshot` 调用顺序、"进程退出后代理才检测到超限"必须被采集、"backend 记账期间迟到大输出"必须被最终复查捕获 |
| [P1] 无 meta 的负数退出码不能证明是 Runner 主动终止：外部 SIGKILL 被误判为中性 normal | `_SpawnState` 新增 `termination_requested` 标志，仅 `terminate()` 设置；`execution_info` 仅在 `returncode<0` 且该标志为真时返回中性 accounting，其余无 meta（外部杀、监督进程崩溃、isolate 自行退出无产出）一律 `status:XX` fail closed。双向行为已用复现脚本验证：外部 SIGKILL→sandbox_error，Runner 请求杀→normal |

**修正后验证**：全量 `169 passed, 19 skipped`（净增 4 项）；ruff/mypy/Vitest/build 全绿。

## 五之五、k3.1 第三轮复验后的修正（第四轮）

| 问题 | 修正 |
| --- | --- |
| [P1] `isolate --cleanup` 未携带 `--cg`：v2.0 的 `cg_remove()` 在 `cg_enable` 为假时直接返回，每次执行后的 cgroup 残留累积（可致 `Device or resource busy`）；且 cleanup 用 `check=False` 并吞掉 `OSError`，失败完全不可观测 | `_isolate_cleanup` 命令加入 `--cleanup --cg`；`_SpawnState` 新增 `cleanup_error` 字段，非零退出码（含 stderr/stdout 详情）、启动 `OSError`、`TimeoutExpired` 均记录到 `cleanup_error` 并以 `logger.error` 输出，不再静默。新增 3 项测试：cleanup argv 精确断言（含 `--cg`）、非零退出记录、启动失败记录 |

**修正后验证**：全量 `172 passed, 19 skipped`（净增 3 项）；ruff/mypy/Vitest/build 全绿。

## 五之六、当前剩余未覆盖项

1. `tests/test_linux_isolate.py`（12 项）与 VM 套件仍需 Linux 环境执行；`--no-default-dirs` 挂载视图与四语言判题仍需一次性 VM 实证。
2. `execution_info` 中性分支与 `cleanup_error` 日志路径只能在真实 isolate 上端到端验证。
3. 与部署文档中旧 isolate 补丁清单的冲突对照，列入阶段 5 部署资产纳管。

## 六、变更集（在阶段 1 之上新增）

```text
M  judge/linux_isolate.py   M  judge/worker.py      M  judge/protocol.py
M  judge/sandbox.py         M  judge/process.py     M  judge/config.py
M  judge/celery_worker.py   M  app/tasks/dispatcher.py
M  tests/test_linux_isolate.py   M  tests/test_linux_judge_vm.py
M  tests/test_judge_worker.py    M  tests/test_judge_config.py
M  tests/test_windows_sandbox.py
?? tests/test_isolate_meta.py   ?? tests/test_output_proxy.py   ?? tests/test_process_runner.py
```
