# greet 命令基线（旧实现审计 · 2026-08-03）

> 数据来源：`boss-hr-greet/scripts/auto_greet.py`（841 行）实测 + AST 静态分析。
> 审计工作区：`BOSS_HR_OUTPUT_DIR=<tmp>/greet-audit-ws`（不碰用户真实桌面目录）。

---

## 1. 旧入口

| 项 | 值 |
|----|----|
| 脚本 | `boss-hr-greet/scripts/auto_greet.py` |
| cli_runner 白名单 tool 名 | `auto_greet` |
| 业务函数 | `auto_greet(job_name, score_threshold, max_count, run_id, only_names, dry_run, scroll_max, scan_only, skip_scan, encrypt_job_id)` |
| 依赖 | patchright CDP（`http://localhost:9222`）真实点击 BOSS 打招呼按钮 |

## 2. 旧 CLI 参数

| 参数 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `--job-name` | 否 | `线控底盘制动、转向工程师` | 岗位名（旧脚本有硬编码默认值） |
| `--encrypt-job-id` | 否（严格模式必需） | None（env `BOSS_HR_ENCRYPT_JOB_ID` 兜底） | 缺则 `ValueError` → rc=1 |
| `--run-id` | **是** | — | argparse `required=True` |
| `--threshold` | 否 | 70.0 | score 阈值 |
| `--max` | 否 | 10 | 最多招呼人数 |
| `--only-names` | 否 | None | 逗号分隔精准点名；生效时 threshold=0、max=名单长度 |
| `--dry-run` | 否 | False | 只定位不 click |
| `--scan-only` | 否 | False | 只扫位置表 |
| `--skip-scan` | 否 | False | 跳过扫描 |
| `--scroll-max` | 否 | 60 | 扫描滚屏上限 |
| `--no-finish` | 否 | False | 跑完不自动 finish() |

> `--scan-only` 与 `--skip-scan` 互斥（`parser.error` → rc=2）。

## 3. 实测退出码

| 场景 | 实测 rc | 说明 |
|------|--------|------|
| 缺 `--run-id` | **2** | argparse required |
| `--scan-only` + `--skip-scan` 同时给 | **2** | `parser.error` |
| 缺 `--encrypt-job-id` 且无 env | **1** | `ValueError` 未捕获 |
| `run_id` 不存在 | **1** | `bind_existing_run` 抛 `FileNotFoundError` 未捕获（**注意：不是 23**） |
| run 与岗位不匹配 | **1** | `RuntimeError` 未捕获（**注意：不是 24**） |
| 无高分候选人 | **0** | 提前 return，不连浏览器，**不写 greet_log.json** |
| 正常招呼 | 0 | — |

> ⚠️ 旧脚本**没有** `is_confirmed()` 守卫（全仓库只有 `recommend_list.py:58`
> 和 `recommend_download.py:104` 有）。greet 不校验 confirmed，**不返回 20**。

## 4. 输出产物

```
runs/<run_id>/process/greet_log.json     # 主产物
runs/<run_id>/process/run_log.txt        # 文本日志（log() 追加）
<eid>/state/geek_positions.json          # 跨 run 位置表（扫描阶段刷新）
```

`greet_log.json` 结构：

```json
{
  "job": "...", "run_id": "...", "score_threshold": 70,
  "started_at": "...", "updated_at": "...",
  "mode": "scan_and_greet_reverse", "positions_count": 12,
  "summary": {"greeted": 2, "clicked_unverified": 0, "not_found": 1,
              "dry_run": 0, "scanned": 0, "total": 3},
  "results": [{"name": "...", "status": "greeted", "verified": true, ...}]
}
```

`status` 取值：`greeted` / `clicked_unverified` / `not_found` / `scanned` / `dry_run`。

## 5. 状态修改（run.json）

| 时机 | 动作 |
|------|------|
| greet_log 落盘后 | `orch.mark_done('greet', run_id=run_id)` → `steps_done += ["greet"]` |
| `greeted > 0` 且非 dry-run 且非 `--no-finish` | 尝试 `orch.finish()` → 期望 `finished=true` |
| `greeted == 0` / dry-run / `--no-finish` | **不** finish（保留回头补招呼能力） |

---

## 6. 🐞 旧实现的 3 个既有缺陷（本轮**不修**，仅记录）

> 本轮任务边界是「迁移 greet 命令」，遵守「无行为变化」约束。
> 以下缺陷属于旧脚本自身问题，修它们会改变既有行为，应作为独立轮次处理。

### 6.1 `orch.finish()` 调用缺 `run_id` → 自动 finish 从未生效

`auto_greet.py:756` 写的是 `orch.finish()`，但签名是
`RunOrchestrator.finish(self, run_id: str)`（`shared/run_orchestrator.py:253`，
run_id **必填**）。

实测：`TypeError: RunOrchestrator.finish() missing 1 required positional argument: 'run_id'`。

该调用被 `except Exception` 吞掉（`auto_greet.py:763`），只打印
`⚠️ 自动 finish() 失败`。**后果**：SKILL.md 与 HANDOFF 声称的
「招呼成功 ≥1 自动 finish()」实际**从未生效**，`run.json.finished` 恒为 false。

### 6.2 `auto_greet()` 函数体内引用 `__main__` 才定义的全局 `args`

`auto_greet.py:744 / 753 / 766` 用了 `args.no_finish` / `args.dry_run`，
但 `args` 只在 `if __name__ == '__main__':` 块里 `parser.parse_args()` 赋值
（AST 确认 `auto_greet` 形参和局部变量里都没有 `args`）。

**后果**：以 `python auto_greet.py ...` 子进程方式跑没问题（模块全局有 `args`）；
但任何 `from auto_greet import auto_greet` 的**直接函数调用**会在收尾阶段
`NameError`。→ 新 CLI **必须走 subprocess**（`cli_runner`），不能直接 import 该函数。

### 6.3 ☠️ 无高分候选人时 `prune_if_empty()` 删掉整个 run 目录

`auto_greet.py:568` 注册 `atexit` 钩子 `_auto_prune()`：没写 greet_log.json
就调 `output.prune_if_empty()`。而 `prune_if_empty`
（`shared/output_manager.py:335`）的逻辑是「run_dir 里没有 `.html` 文件就
`shutil.rmtree(run_dir)`」。

无高分候选人时脚本在 `auto_greet.py:584` 提前 return（未写 greet_log），
atexit 触发 → **整个 `runs/<run_id>/` 被删除**，含 `job_detail.json`、
`screening_results.json`、`run.json`。

实测复现（rc 仍为 **0**，且 `_auto_prune` 自身还因 run_log.txt 已随目录删除
而抛 `FileNotFoundError` 到 stderr）：

```
run 目录 <ws>/audit_eid_001/runs/2026-08-03_120000  →  已被删除
```

**缓解条件**：正常 5 步流程里 Step 4（report）先生成了
`<run_id>_screening_report.html`，`prune_if_empty` 见到 `.html` 会 return False
→ 不删。所以只在「greet 跑在 report 之前」或「报告生成失败」时才触发。

**对新 CLI 的影响**：`greet` 在无候选人时 rc=0 但 run 目录可能已消失，
新 CLI 读 greet_log.json 会落空——必须容忍该文件缺失，不能断言其存在。

---

## 7. 新 CLI `boss-hr greet` 契约（本轮实现目标）

### 7.1 公开参数

| 参数 | 必填 | 默认 |
|------|------|------|
| `--job-name` | 是 | — |
| `--encrypt-job-id` | 否（env 兜底，两者都缺 → rc=2） | None |
| `--run-id` | 是 | — |
| `--only-names` | 否 | None |
| `--threshold` | 否 | 70.0 |
| `--max` | 否 | 10 |
| `--dry-run` | 否 | False |

**不暴露**：`--scan-only` / `--skip-scan` / `--scroll-max` / `--no-finish`
（内部调试参数，比照 fetch 不暴露 list/download 的 batch 参数）。
`--no-finish` 不暴露的额外理由见 §6.1：自动 finish 本来就没生效。

### 7.2 成功 schema

```json
{"ok": true, "command": "greet", "status": "greet_complete",
 "run_id": "...", "encrypt_job_id": "...", "job_name": "...",
 "data": {"greeted": 2, "clicked_unverified": 0, "not_found": 1, "total": 3,
          "dry_run": false, "greet_log_file": "<abs path>",
          "candidates_targeted": 3},
 "next_action": "done"}
```

无高分候选人（rc=0 且无 greet_log.json）时：`data.no_candidates = true`，
计数全 0，`greet_log_file` 为 null，`next_action` 仍为 `done`。

### 7.3 退出码（新 CLI 统一化，向 report/fetch 对齐）

| rc | 场景 |
|----|------|
| 0 | 成功（含无候选人） |
| 1 | 缺 encrypt_job_id（业务层） |
| 2 | argparse 缺 `--job-name` / `--run-id` / `--encrypt-job-id`（env 也无） |
| 23 | run 不存在（**预校验提前拦截**，旧脚本此处是 1） |
| 24 | run 与岗位不匹配（**预校验提前拦截**，旧脚本此处是 1） |
| 其他 | 子进程真实 rc 透传 |

> 23/24 由新 CLI 的 `bind_existing_run` 预校验产生，与 `report` / `fetch`
> 完全一致（那两条命令同样把旧脚本的裸异常收敛成 23/24）。这是**统一 CLI 层**
> 的既定契约，不算改旧脚本行为——旧脚本本身仍返回 1。

### 7.4 行为约束（必须验证）

- ✅ 走 `cli_runner` 子进程调 `auto_greet`，**不**直接 import（见 §6.2）
- ✅ **不**复制 CDP / patchright / DOM 扫描 / 倒序招呼逻辑
- ✅ **不**调 `boss_jd` / `confirm_run` / `recommend_*` / `score_*` / `generate_html_report`
- ✅ **不**自动 confirm、**不**创建新 run、**不**扫描最新 run
- ✅ `--only-names` 透传为逗号分隔字符串
- ✅ 容忍 greet_log.json 缺失（见 §6.3）
