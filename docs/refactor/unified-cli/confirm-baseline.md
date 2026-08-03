# Confirm 基线（2026-08-03）

工具：`tools/baseline_confirm.py` → `artifacts/refactor/confirm-baseline.json`

## happy path（confirmed=false → true）

| 项 | 值 |
|----|----|
| returncode | **0** |
| stdout | JSON `{"status":"confirmed", "run_id":"...", "confirmed":true, "message":"确认成功。run.json.confirmed=true。..."}` |
| 副作用 | run.json.confirmed: false→true; user_confirmed_at: None→"2026-08-03 14:15:04" |
| | steps_done 不变；finished 不变；不调 finish() |

## repeat confirm（幂等）

- returncode 0
- stdout 同 happy
- run.json 仍 confirmed=true，user_confirmed_at 不变（RunOrchestrator 不刷新时间戳）

## --status only（仅查询，不修改）

- returncode 0
- stdout JSON `{"status":"ok", "run_id":"...", "confirmed":true, "message":"已查询，未修改状态。"}`

## 边界

| 用例 | rc | 行为 |
|------|----|------|
| encrypt_job_id 错（导致 runs_dir 找不到） | **23** | JSON `{status:"blocked", exit_code:23, run_id, message}` |
| run_id 不存在 | **23** | 同上 |
| 缺 --run-id（argparse） | **2** | argparse usage |
| 缺 encrypt_job_id（无 env） | **1** | JSON `{status:"error", message:"缺少 encrypt_job_id..."}` |

## run.json 副作用（关键不变量）

- 写当前 run.json 的 `confirmed` / `user_confirmed_at`
- 不改 `steps_done` / `finished` / `finished_at`
- **不修改其他 run 的 run.json**（其他 run_id 即使 confirmed=true 也保持不变）
- **不修改除当前 run 目录外的任何文件**

## 新旧实现状态变化等价（待 verify）

新 CLI 必须：
- 调 `shared/confirm_run.confirm_run()` 或 `RunOrchestrator.confirm_run()`；
- 不直接编辑 run.json（用业务函数走原路径）
- run.json 副作用与基线完全一致
- exit code 语义保留（0/2/23/1）

## encrypt_job_id 不匹配但 run_id 存在（未基线覆盖）

旧脚本逻辑：如果 run_id 存在但 job_detail.json.encryptJobId != 当前 eid，
bind_existing_run 抛 RuntimeError → exit code 24。
这个分支在 `tests/test_run_id_boundary.py::test_scenario_9_*` 类的相邻测试
里覆盖（encrypt_job_id 写错时 bind_existing_run 抛 RuntimeError，run_orchestrator
main() 不捕获 → Python 抛非 0 → rc=1）。需要在新 CLI 用预校验拦截为 rc=24。

## 不调任何下游脚本（重点）

confirm_run.py **不调** recommend_list / recommend_download / fetch / score /
report / greet；只改 run.json。新 CLI 必须保持。
