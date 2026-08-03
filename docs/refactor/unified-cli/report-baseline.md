# Report 基线（2026-08-03）

> 工具：`_baseline_report.py`（tools/ 下也存一份；artifacts/refactor/ 存 JSON）。
> 输入：tmp_path 下造两个 run（target + other）+ 完整 screening_results.json。

## 1. happy path（target run，正常生成）

| 项 | 实测值 |
|----|--------|
| returncode | **0** |
| stdout | `[orchestrator] --input 默认: ...` + `[orchestrator] --output 默认: ...` + `✅ HTML 报告已生成: ...` + `   文件大小: 17911 字节` + `   候选人: 3 人`（5 行 print，**非 JSON**） |
| stderr | 空 |
| 报告路径 | `runs/<run_id>/<run_id>_screening_report.html` |
| 报告大小 | 17911 字节 |
| 候选人顺序（rank in HTML） | [1, 2, 3] |
| stat-card 数字 | ['1', '1', '1', '3']（recommend/pending/reject/total） |
| tier 徽章数 | 推荐 1 / 待定 1 / 不推荐 1（GBK 解码 → 乱码，但 count 对） |

### run.json diff（副作用）

| 字段 | before | after |
|------|--------|-------|
| steps_done | ['jd', 'download', 'score'] | ['jd', 'download', 'score', 'report'] |
| last_step | 'score' | 'report' |
| finished | False | False（**不调 finish()**） |

## 2. 边界用例

| 用例 | rc | 行为 |
|------|----|------|
| 缺 screening_results.json | **27** | stdout 含 `{"status":"blocked", "exit_code":27, ...}` JSON |
| encrypt_job_id 错（run 不存在） | **1** | stderr 抛 Python traceback（FileNotFoundError 未被 main 捕获） |
| run_id 不存在 | **1** | stderr 抛 Python traceback（同上） |
| 缺 --run-id（argparse） | **2** | stderr argparse usage |
| 重复跑（同一 target） | **0** | 覆盖原 HTML，run.json mark_done 幂等（steps_done 不重复） |

## 3. 设计内偏差（旧脚本 = 业务参考）

- **stdout 不是 JSON**：成功时是 5 行 print。新 CLI 必须把它包成统一 JSON `{ok:true, command:"report", status:"report_ready", run_id, data:{report_file}, next_action:"greet_optional"}`
- **exit code 1 不是脚本内部编码**：旧脚本 main() 里 FileNotFoundError / ValueError 没人捕获，Python 默认抛非 0。新 CLI 必须**保留这个退出码语义**（不归一化），通过 cli_runner 透传
- **exit 27（缺 screening）+ exit 2（缺 run-id）+ exit 0（成功）** 都是约定的，必须保留

## 4. 已确认：不会触发的事

- ❌ 不调 `finish()`（与旧一致；BEHAVIOR_V1.md 第 51 行）
- ❌ 不调 greet（与旧一致；report 永远不触发 greet）
- ❌ 不读 current_run.json（从没用过）
- ❌ 不从其他 run 借 screening_results（场景 5 测试覆盖）

## 5. fixtures

- `_baseline_report.py` 脚本可重跑：`python _baseline_report.py` → 重写 `artifacts/refactor/report-baseline.json`
- 真实历史 run 仅作为补充验证；自动测试用 tmp_path
