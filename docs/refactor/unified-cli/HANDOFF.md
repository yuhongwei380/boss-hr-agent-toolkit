# HANDOFF — boss-hr 统一 CLI 重构（v1 → v1.1+）

> **本文件只是交接文档，不是新的业务规范。**
> 实际代码和测试优先于本交接文档。
>
> 数据采集时间：2026-08-03。

---

## 1. 当前分支和基线

| 项 | 值 |
|----|----|
| 当前分支 | `refactor/unified-cli-v1` |
| 起始 tag | `v1.1-skill-stable`（commit `d5bc46c`） |
| 当前 HEAD | `1e62fb920bc9a8ece15a3b717d03516bbd8a5b0a` |
| `git status --short` | （空，工作树干净） |
| 最新完整 pytest | **237 passed in 32.06s**，exit code **0** |

启动方式：

```bash
# 切到本工作分支
git checkout refactor/unified-cli-v1

# 跑全测
python -m pytest -q -ra --tb=short
# 完整 log 落到 artifacts/refactor/pytest-full.log
```

> ⚠️ **必须**用 pytest 8.4+；pytest 7.4 与本仓库 `tests/conftest.py` 的 stdout reconfigure 不兼容（第一轮 commit 1 已修，但旧 pytest 仍会崩）。推荐 `pip install 'pytest>=8'`。

---

## 2. 已完成命令

| 命令 | 测试文件 | 用例数 | 状态 |
|------|---------|--------|------|
| `status` | `tests/cli/test_status.py` | 7 | ✅ |
| `report` | `tests/cli/test_report.py` | 8 | ✅ |
| `confirm` | `tests/cli/test_confirm.py` | 11 | ✅ |
| `score`（C1 协调） | `tests/cli/test_score_coordination.py` | 15 | ✅ |
| `score`（C2 finalize） | `tests/cli/test_score_finalize.py` | 12 | ✅ |
| `score`（转换 + 损坏 JSON） | `tests/cli/test_score_full_flow.py` | 4 | ✅ |
| `start` | `tests/cli/test_start.py` | 27 | ✅ |
| `fetch` | `tests/cli/test_fetch.py` | 24 | ✅ |
| `greet` | `tests/cli/test_greet.py` | 28 | ✅ |

> **已迁移完成**：status / report / confirm / score（C1+C2+full_flow）/ start / fetch / greet = **7 个命令**（全部完成）。
> 业务测试 106 + cli 测试 131（含 greet 28）= **237 passed**。

---

## 3. 各命令公开参数、状态、next_action、退出码

> 详细 schema 见 `docs/refactor/unified-cli/status-verification.md` / `report-baseline.md` / `confirm-baseline.md` / `start-baseline.md`。
> 各 `application/*_service.py` 顶部 docstring 也有完整 JSON schema。

### 3.1 `status`
- 参数：`--job-name required` `--encrypt-job-id`（env 兜底）`--run-id required`
- 成功 status：`ok`（status 命令保留第一轮 schema：`{status:"ok", command:"status", run_id, workflow_state, ...}`）
- next_action：无（status 不产生流程推进）
- 退出码：0 / 1 / 2 / 22 / 23 / 24

### 3.2 `report`
- 参数：`--job-name required` `--encrypt-job-id`（env 兜底）`--run-id required`
- 成功 status：`report_ready`
- next_action：`greet_optional`
- 退出码：0 / 1 / 2 / 23 / 24 / 27（缺 screening_results.json）

### 3.3 `confirm`
- 参数：`--job-name required` `--encrypt-job-id`（env 兜底）`--run-id required`
- 成功 status：`confirmed`
- 成功 data：`{confirmed: true, user_confirmed_at: "..."}`
- next_action：`fetch`
- 退出码：0 / 1 / 2 / 23 / 24

### 3.4 `score`
- 参数：`--job-name required` `--encrypt-job-id`（env 兜底）`--run-id required`
- 成功 status（两种）：
  - `waiting_llm`：`data.candidate_id` 有值 → LLM 写 output 后再调一次
  - `scoring_complete`：`data.scored` + `data.screening_results_file`；所有 output 都齐
- next_action：`score_candidate_then_repeat` 或 `report`
- 退出码：0 / 1 / 2 / 20（未 confirmed）/ 23 / 24 / 26（缺 new_resumes 或 collect 失败）

### 3.5 `fetch`
- 参数：`--job-name required` `--encrypt-job-id`（env 兜底）`--run-id required` `--count default=10`
- 成功 status：`candidates_fetched`
- 成功 data：`{requested_count, listed_count, downloaded_count, failed_count, candidate_list_file, new_resumes_file, failed_resumes_file}`
- next_action：`score`
- 退出码：0 / 1 / 2 / 20（未 confirmed）/ 23 / 24 / 26（缺 new_resumes）

### 3.7 `greet`
- 参数：`--job-name required` `--encrypt-job-id`（env 兜底）`--run-id required`
  `--only-names`（逗号分隔，可选）`--threshold default=70.0` `--max default=10` `--dry-run`
- **不暴露**：`--scan-only` / `--skip-scan` / `--scroll-max` / `--no-finish`（内部调试参数）
- 成功 status：`greet_complete`
- 成功 data：`{greeted, clicked_unverified, not_found, total, candidates_targeted,
  dry_run, greet_log_file, no_candidates}`
- next_action：`done`
- 退出码：0（含无候选人）/ 1（缺 eid 业务层）/ 2 / 23 / 24 / 子进程真实 rc 透传（int）
- **不校验 confirmed**（旧 greet 脚本本就无 `is_confirmed()` 守卫，保持一致，不返回 20）
- 详见 `docs/refactor/unified-cli/greet-baseline.md`（含旧脚本 3 个既有缺陷的记录）

### 3.6 `start`
- 参数：位置参数 `<query>`（encryptJobId | jobId | 岗位名，必填）；`--job-name` required；`--encrypt-job-id`（env `BOSS_HR_ENCRYPT_JOB_ID` 兜底）
- **不接受 `--run-id`**（argparse unknown → rc=2；start 必须创建新 run）
- 成功 status：`waiting_user_confirmation`
- 成功 data：`{job_detail_file: "<绝对路径>", confirmed: false}`
- next_action：`confirm`
- 退出码：0 / 1（query 找不到 / 缺 encrypt_job_id 业务层）/ 2（argparse 缺 query / --job-name / 加密后无法 fallback）/ 子进程真实 rc 透传（int，不用 `ExitCode` enum 避免 rc 不在 enum 里抛 `ValueError`）

---

## 4. 当前 boss_hr 架构

5 层，职责分明。**不破坏 v1.1-skill-stable 旧结构**，作为子包挂在工具包根。

```
boss_hr/
├── __init__.py
├── cli.py                          # argparse + COMMANDS 注册表 + emit JSON + 顶层 exit code
├── commands/                       # 薄壳：CLI 参数 → application 调用
│   ├── __init__.py
│   ├── _argparse_helpers.py        # add_required_arguments + require_encrypt_job_id
│   ├── status.py
│   ├── report.py
│   ├── confirm.py
│   ├── score.py
│   ├── start.py                    # ✅ 已实现（commit 1e62fb9）
│   └── fetch.py
├── application/                    # 业务编排；状态校验；返回 CommandResult
│   ├── __init__.py
│   ├── status_service.py
│   ├── report_service.py
│   ├── confirm_service.py
│   ├── scoring_service.py
│   ├── fetch_service.py
│   └── start_service.py            # ✅ 已实现（commit 1e62fb9）
├── adapters/                       # 旧脚本 / 子进程调用的薄包装
│   ├── __init__.py
│   └── legacy_runner.py            # cli_runner.run_python_cli + stdout 解析 + rc 映射
└── contracts/                      # 统一 CommandResult / ExitCode / ErrorCode
    ├── __init__.py
    ├── results.py
    └── errors.py
```

### 4.1 职责（无行为变化约束）

| 层 | 职责 | **不**做 |
|----|------|------|
| `cli.py` | argparse + 调用 command handler + emit JSON + 顶层 exit code | 不含 run 状态判断；不含正则解析；不直接调 `cli_runner` |
| `commands/` | CLI 参数 → application 调用 | 不操作浏览器、文件路径、subprocess |
| `application/` | 状态校验 + 业务编排；返回结构化结果 | 不解析旧脚本 stdout（adapter 的活） |
| `adapters/` | 包装 `shared.cli_runner.run_python_cli()`；处理子进程 stdout/stderr；统一 rc 映射 | 不创建 spec 文件 |
| `contracts/` | 统一 `CommandResult` / `ExitCode` / `ErrorCode` / `UnifiedError` | 不含业务逻辑 |

`status` 命令特殊：保留第一轮 JSON schema（`{status, command, run_id, ...}`），用 `(int, dict)` tuple 返回而不是 `CommandResult`。`report / confirm / score / fetch / start` 都用通用 schema。

---

## 5. score 状态机

`boss-hr score` 在 `application/scoring_service.py:run_score` 入口分派：

```
run_score(args)
├── 校验：run 存在 / confirmed=true / new_resumes.json 存在
├── _common_pre_check(): 拿 scoring_dir / manifest / candidates
├── count_remaining(candidates)
│   ├── remaining > 0  →  find_next_candidate → waiting_llm
│   └── remaining == 0 →  finalize_when_ready → 调 collect / score_resumes
└── finalize_when_ready(args)
    ├── screening_results.json 已存在 → 幂等返回 scoring_complete
    ├── 调 collect_llm_scores（cli_runner）
    │   ├── collect 失败 → 透传 exit_code（默认 26 → MISSING_SCREENING）
    │   ├── collect 标记 invalid → 返回该候选人 waiting_llm + validation_error
    │   ├── collect 标记 missing → 返回该候选人 waiting_llm（允许 LLM 重写）
    │   └── 全部 scored → 调 score_resumes（cli_runner）
    │       ├── score_resumes 失败 → 透传 exit_code
    │       └── 成功 → 返回 scoring_complete + screening_results_file
```

**关键设计**：
- **唯一合法性来源是 `collect_llm_scores.py`**。`scoring_service` 只判断 `output 文件存在 + size > 0`，不读 JSON，不调 schema 校验。
- `_validate_score` 函数已在 `ea6db31 fix(cli): use collector as sole score validator` 删除。
- 每次 `score` 命令 dispatcher 自动选 C1（协调）或 C2（finalize）。
- manifest 在 collect 前可能 `status: "pending"`，即使 output 已存在。判断基于 `outputs/<file>` 文件存在性。

---

## 6. 当前冻结业务边界

v1.1-skill-stable 的业务约束在新 CLI 全部保留（`docs/BEHAVIOR_V1.md` 锁定）：

| 约束 | 实现 |
|------|------|
| 只支持一次新筛选任务 | ✅ start 每次 `create_new_run()` |
| **不**支持 `continue` | ✅ 所有命令不接受 `--continue` / `--resume` |
| **不**支持 `batch` / `--batch-size` / `--batch` | ✅ fetch 只暴露 `--count`；list/download 内部 batch 参数不暴露 |
| **不**支持多批累计 | ✅ |
| **不**扫描最新 run | ✅ 所有命令要求显式 `--run-id` |
| **不**读 `current_run.json` | ✅（BEHAVIOR_V1.md 已删除该文件） |
| **不**创建 spec | ✅ cli_runner 走 Python API |
| **不**复制旧业务逻辑 | ✅ 全部走 cli_runner + adapter |
| Step 1 后必须停在人工确认门 | ✅ start 返回 `next_action: "confirm"`；report / greet 不自动调 |

`run_id` 是数据边界（`docs/BEHAVIOR_V1.md` 铁律），所有业务脚本 `--run-id required=True`。

---

## 7. 已完成 commit 列表

> 按时间顺序（最近 commit 在最上）。
> 所有 commit 在 `refactor/unified-cli-v1` 分支，**未 push**（看 git status 决定是否 push）。

| # | Hash | 标题 | 作用 |
|---|------|------|------|
| 1 | `1e62fb920bc9a8ece15a3b717d03516bbd8a5b0a` | `refactor(cli): add unified start command` | start 命令 |
| 2 | `b3f8c4b` | `refactor(cli): add unified fetch command` | fetch 命令 |
| 3 | `ea6db31` | `fix(cli): use collector as sole score validator` | 删 _validate_score + 加 4 个 full_flow 用例 |
| 4 | `4b49235` | `fix(score): guard console encoding setup under main` | 修 3 个脚本 stdout reconfigure import 副作用 |
| 5 | `d27cc05` | `refactor(cli): add score collection and finalization` | score C2：collect + finalize |
| 6 | `27f138f` | `refactor(cli): add score candidate coordination` | score C1：候选协调 |
| 7 | `4a66574` | `fix(cli): normalize missing required argument exit codes` | 必填参数统一 rc=2 |
| 8 | `6b6cb90` | `refactor(cli): add unified confirm command` | confirm 命令 |
| 9 | `e5f9dce` | `refactor(cli): split command application and adapter layers` | 架构收口：5 层拆分 |
| 10 | `f4a1abe` | `refactor(cli): add unified CLI report command` | report 命令 |
| 11 | `6233364` | `refactor(cli): add unified CLI status command` | status 命令（第一轮） |
| 12 | `d7ef86a` | `test: align score CLI tests with explicit run-id contract` | 第一轮：修 pytest 崩溃 + 加 import-safe 测试 |

> **说明**：用户实际开始本会话时 `start` 还未提交（commit #1 在本会话期间完成）。新会话接手时 HEAD 是 `1e62fb9`（含 start commit）。**`start` 实际已经存在**——下一轮"实现 start"是"再确认 start 已经完成"而非"首次实现"。
---

## 8. 已知但尚未解决的问题

### 8.1 fetch 真实 BOSS/CDP smoke
- **状态**：未执行
- **原因**：当前会话环境没有安全 BOSS 登录
- **必做项**（统一 CLI 交付前必须）：
  1. Edge 9222 启动 + 登录
  2. `boss-hr start <query> --job-name ... --encrypt-job-id ...`
  3. 调 `boss-hr confirm`
  4. 调 `boss-hr fetch --count 1`
  5. 验证产物文件（`recommend_geek_ids.json` / `new_resumes.json` / `failed_resumes.json`）

### 8.2 其他未完成项（按重要性）
- 真实全链路 smoke（start → confirm → fetch → score → report → greet，6 步真实 BOSS）
- `boss-hr-auto/SKILL.md` 精简（去重；现在文档 + SKILL + 新 CLI 文档并存）
- 安装/发布验证（setup / wheels / 版本号）
- `auto_greet.py` 的 3 个既有缺陷（见 §9.1）
- 真实 BOSS 环境 + login 自动化（不是本仓库职责；最终用户做）

### 8.3 已完成无遗留
- ✅ fix(score): guard console encoding setup under main（`4b49235`）
- ✅ fix(cli): use collector as sole score validator（`ea6db31`）
- ✅ fix(cli): normalize missing required argument exit codes（`4a66574`）
- ✅ fix(cli): align score CLI tests with explicit run-id contract（`d7ef86a`）
- ✅ 阶段 A 架构收口（`e5f9dce`）

不要把上述 5 条已修问题继续列为"未完成"。

---

## 9. 剩余任务（严格按顺序）

> 用户指令："本轮只完成 boss-hr start 的审计、实现、测试和提交。"
> 即**当前会话**只做 `start`（实际已完成，见 §7 注）。剩余任务**给下一会话**：
> start 在 commit `1e62fb9` 中已完整实现、测试、commit、纳入 209 passed。

| 顺序 | 任务 | 状态 |
|------|------|------|
| 1 | `boss-hr greet` | ✅ 已完成（`bcd6e94`，28 个测试） |
| 2 | 真实 `start → confirm → fetch --count 1` smoke（最小链路） | ✅ 已通过（2026-08-04，见 `real-smoke-2026-08-04.md`） |
| 3 | 完整端到端回归（start → confirm → fetch → score → report → greet） | ⚠️ 部分通过 — score / report / 0-candidates greet 真实路径已通过；**真实 ≥1 个 ≥70 分候选人的 greet 点击发送尚未验证**（详见 `real-smoke-2026-08-04.md` §7） |
| 4 | 精简 `boss-hr-auto/SKILL.md`（与新 CLI 文档去重） | ✅ 已完成 |
| 5 | 安装和发布验证（setup.py / wheels / 版本号） | ✅ 已完成（editable install + 项目外 cwd + 7 命令边界） |

**7 个命令全部迁移完成 + 真实 smoke 通过（含 0 候选人安全路径）**。
剩余唯一未验证的真实业务路径：存在 ≥70 分候选人时浏览器实际点击发送
→ `greeted >= 1` → `run.json.finished = true`。

### 9.1 ⚠️ 迁移中发现的旧脚本既有缺陷

| # | 缺陷 | 状态 |
|---|------|------|
| 1 | `orch.finish()` 缺 `run_id` 实参（`auto_greet.py:756`） | ✅ **已修复** `ad243ad` — `maybe_finish()` 显式传 run_id，异常不静默 |
| 2 | `auto_greet()` 函数体引用只在 `__main__` 定义的全局 `args`（:744/753/766） | ⚠️ **保留**（不动 boss_jd 主体），新 CLI 走 `cli_runner` 子进程规避 |
| 3 | 无高分候选人时 atexit `prune_if_empty()` 删掉**整个 run 目录** | ✅ **已修复** `edc6959` — `note_skip_if_unsaved()` 只写日志 + sentry，永不删文件；`tests/test_auto_greet_skip_hook.py` 11 例 |

### 9.2 已修复的 `auto_greet` 缺陷的回归覆盖

| 修复 | 测试文件 | 例数 |
|---|---|---|
| `edc6959` prune 防护 | `tests/test_auto_greet_skip_hook.py` | 11 |
| `ad243ad` finish 显式 run_id | `tests/test_auto_greet_maybe_finish.py` | 12 |
| **合计** | | **23** |

---

## 10. start 验收目标（已完成回看）

> **start 已完成**（commit `1e62fb9`，27 个测试通过）。本节供新会话"回看"核对。

### 10.1 行为约束（每条都要验证）
- ✅ start **不接受** `--run-id`（argparse unknown argument → rc=2）
- ✅ 每次 start 产生**新** run_id（`create_new_run()`，YYYY-MM-DD_HHMMSS[_suffix]）
- ✅ 连续两次 start 得到的 run_id **不同**（`test_start_two_runs_different_ids`）
- ✅ `run.json.confirmed = false`（`test_start_confirmed_false`）
- ✅ 返回 `status: "waiting_user_confirmation"`（`test_start_creates_new_run`）
- ✅ `next_action: "confirm"`
- ✅ **不**自动调 `confirm_run`（`test_start_does_not_call_confirm`）
- ✅ **不**调 `recommend_list` / `recommend_download`（同类测试）
- ✅ **不**调 `score_resumes` / `collect_llm_scores` / `generate_html_report` / `auto_greet`
- ✅ `run_id` 来自 boss_jd 真实业务输出（adapter 解析末尾 JSON 或严格 regex），**不**扫描 runs 目录
- ✅ 复用 `boss_jd.py` 真实业务逻辑（`cli_runner.run_python_cli("boss_jd", ...)`，不复制 CDP / patchright / 岗位解析 / run 创建）
- ✅ `job_detail.json` 路径正确（`data.job_detail_file` 指向 `<workspace>/<eid>/runs/<rid>/process/job_detail.json`）
- ✅ 三处 run_id 一致（JSON output / run.json / job_detail._meta.run_id）

### 10.2 退出码语义（保留旧 boss_jd.py）
- 0 成功
- 1 query 找不到 / 缺 encrypt_job_id（业务层）/ ValueError
- 2 argparse 缺必填（query / --job-name）
- 子进程真实 rc 透传（用 `int` 而非 `ExitCode` enum，避免 rc 不在 enum 里抛 `ValueError`）

### 10.3 公开参数
- 位置参数 `<query>` — encryptJobId | jobId | 岗位名（必填）
- `--job-name` — required
- `--encrypt-job-id` — 默认 None（env `BOSS_HR_ENCRYPT_JOB_ID` 兜底）

### 10.4 fixture 与 mock 策略
- autouse fixture `mock_boss_jd` 替换 `boss_hr.adapters.legacy_runner.run_legacy_cli`
- fake 写真实 run 目录 + job_detail.json + jobs.json（模拟 boss_jd 行为）
- **不**连真实 BOSS / **不**写真实桌面业务目录
- 写真实 `boss_jd.py` 的 stdout 多段混合输出（含中文括号 "（orchestrator 创建）"）

### 10.5 adapter 解析要点
- 末尾 JSON 优先（`try_extract_blocked_message`）
- 严格 regex 兜底：`r"run_id:\s*([0-9]{4}-\d{2}-\d{2}_\d{6,8}(?:_[0-9A-Za-z]+)?)"`（**不**用 `\S+` 贪婪匹配，会被中文括号污染）

### 10.6 已修复但容易复发的 bug（避免重犯）
- `str(_TOOLKIT_ROOT, "shared")` 是 `str(bytes, encoding)` 形式，不是路径拼接。应写 `str(_TOOLKIT_ROOT / "shared")`。
- `ExitCode(result.returncode)` 当 rc 不在 enum 里抛 `ValueError`。start_service 已用 `int` 透传。
- 单元测试 mock 返回的 `stdout` 必须是 `str`（不是 `bytes`），否则 `legacy_runner.try_extract_blocked_message` 内 `startswith("{")` 抛 `TypeError`。
- 旧 `tests/cli/test_start.py.bak` 残留在 `git status` 里时记得删。

---

## 11. 下一会话首次应运行的检查命令

```bash
# 1. 分支与状态
git branch --show-current
# 期望输出: refactor/unified-cli-v1
git status --short
# 期望输出: （空）

# 2. 历史与基线
git log -15 --oneline
# 期望第一行: 1d32a97 docs(cli): add unified CLI refactor handoff
# 期望第二行: 1e62fb9 refactor(cli): add unified start command
git diff --stat v1.1-skill-stable HEAD | tail -5
# 应看到 50+ files changed, 7000+ insertions

# 3. 完整测试
python -m pytest -q -ra --tb=short
# 期望: 209 passed, exit 0
# start 已在 1e62fb9 commit，27 个测试纳入 209。
# greet 实现后会变成 209 + 25 = 234 左右（暂定）。

# 4. 关键文件存在性
ls boss_hr/cli.py boss_hr/commands/start.py boss_hr/application/start_service.py tests/cli/test_start.py
# 期望: 4 个文件都存在
```

如果 `git status` 不空 / 测试不是 209 / 关键文件缺失 → 上一会话可能没正常结束，**先回退**（`git reset --hard 1e62fb9`）再开始新工作。

---

## 12. 重要提醒

> **HANDOFF.md 只是交接文档，不是新的业务规范。**
> 实际代码和测试优先于本交接文档。

如果本文件与实际仓库矛盾（commit hash、测试数字、文件结构），以**实际仓库**为准。
各 command 的 JSON schema、退出码、参数默认值请以 `application/*_service.py` 顶部 docstring + 对应 `docs/refactor/unified-cli/*-baseline.md` 为准。

---

## 附录 A：关键基线文件

| 文件 | 内容 |
|------|------|
| `docs/BEHAVIOR_V1.md` | v1.1-skill-stable 业务边界（数据 / 状态 / 退出码） |
| `docs/refactor/unified-cli/script-command-mapping.md` | 旧脚本 → 新命令的完整映射 |
| `docs/refactor/unified-cli/issues-classified.md` | A/B/C 问题分类 |
| `docs/refactor/unified-cli/status-verification.md` | status 命令基线 + 6 条自检 |
| `docs/refactor/unified-cli/report-baseline.md` | report 命令基线 + schema |
| `docs/refactor/unified-cli/confirm-baseline.md` | confirm 命令基线 + 退出码 |
| `docs/refactor/unified-cli/score-old-audit.md` | score 旧实现审计（早期轮次） |
| `docs/refactor/unified-cli/fetch-baseline.md` | fetch 命令基线 + 子进程调子脚本的副作用 |
| `docs/refactor/unified-cli/start-baseline.md` | start 命令基线（boss_jd stdout 多段输出 + run_id 三处） |
| `artifacts/refactor/pytest-full.log` | 完整 pytest log（每次跑覆盖） |

## 附录 B：pytest 必须的 flag

```bash
python -m pytest -q -ra --tb=short
```

- `-q`：quiet（只显示 summary）
- `-ra`：显示 all summary line（不省略）
- `--tb=short`：traceback 短格式

**不**用 `--tb=long`（会拖长 log）；**不**用 `-v`（每个用例都列）。

`score` 脚本内部 `print()` 会把 pytest summary 行抢到 stdout（已知问题，第一轮 commit 1 已部分缓解）。如要看真实 summary，用：

```bash
python -m pytest -q -ra --tb=short 2>&1 | tee artifacts/refactor/pytest-full.log | tail -3
```
