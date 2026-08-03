# Report（旧实现审计）

> 参考：html-report/scripts/generate_html_report.py、html-report/SKILL.md、
> shared/output_manager.py、shared/run_orchestrator.py、tests/test_run_id_boundary.py
> 场景 3c / 场景 5

## 1. CLI 参数（generate_html_report.py argparse）

| 参数 | 必填 | 默认 | 备注 |
|------|------|------|------|
| `--input` | 否 | `out.screening_results_path`（orchestrator 推断） | screening_results.json 路径 |
| `--output` | 否 | `out.report_path`（`runs/<run_id>/<run_id>_screening_report.html`） | HTML 输出路径 |
| `--job-name` | 否（兼容模式可省） | `None` | 岗位名 |
| `--encrypt-job-id` | 否（兼容模式可省） | None；env `BOSS_HR_ENCRYPT_JOB_ID` 兜底 | BOSS encryptJobId |
| `--run-id` | **是** | — | 数据边界 |

## 2. 可复用函数（agent / 新 CLI 可 import）

| 函数 | 签名 | 作用 |
|------|------|------|
| `render(data: dict) -> str` | 全 docstring | 接收 screening_results.json 数据，返回完整 HTML 字符串 |
| `bar_color(pct)` | `int -> str` | pct → 颜色 hex（绿/黄/红） |
| `tier_badge(tier)` | `str -> str` | tier → HTML badge 字符串 |
| `render_candidate(c, labels, rank)` | `dict, list[str], int -> str` | 单候选人卡片 HTML |
| `render_action(name, score, body)` | `str, float, str -> str` | 单行动建议行 HTML |

## 3. 输入文件

- **主输入**：`runs/<run_id>/process/screening_results.json`（score_resumes.py 输出）
- 校验：必须存在；缺失 → `SystemExit(27)` + stdout JSON `{"status":"blocked", "exit_code":27, "run_id":..., "message":"当前 run=... 缺少评分结果 ..."}`

## 4. 输出路径

- 默认：`runs/<run_id>/<run_id>_screening_report.html`（由 `JobOutputManager.report_path` 计算）
- 文件名带 run_id，跨 run 不覆盖
- 同一 run 重复生成 → 覆盖

## 5. 退出码

| 情况 | exit code | 说明 |
|------|-----------|------|
| 成功 | **0** | print "✅ HTML 报告已生成: ..." 三行 |
| 缺 --run-id（argparse） | **2** | argparse 默认行为（场景 3c 测试覆盖） |
| 缺 screening_results.json | **27** | `{"status":"blocked", "exit_code":27, ...}` JSON（场景 5 测试覆盖） |
| 缺 encrypt_job_id（raise ValueError 未捕获） | **1** | `raise ValueError("缺少 encrypt_job_id...")` → Python 抛非 0 |
| argparse SystemExit（如 bind_existing_run FileNotFoundError 抛） | **1** | 当前 main() 未捕获，会抛到 Python |

注意：旧脚本**没有统一 exit_code 包装**（不像 confirm_run 那样用 JSON `exit_code` 字段），所有退出码都是真实子进程退出码。

## 6. run.json 状态修改

- 成功时调用 `orch.mark_done('report', run_id=run_id)`：
  - `steps_done` 追加 `'report'`（首次）
  - `last_step = 'report'`
  - `last_step_at = now`
- 失败时**不修改** run.json
- **不调 finish()**（与 BEHAVIOR_V1.md 第 51 行"step 5 (greet) 还在同一 run 里"一致）

## 7. import 副作用

- 顶部有 win32 `sys.stdout.reconfigure(encoding="utf-8")`（与 score_resumes 同类问题，已在第一轮 commit 1 修过 score_resumes，generate_html_report 还没修）
- 不替换 sys.stdout 对象（用 reconfigure 不破坏 pytest capture）
- `import patchright` 等大模块——但**仅在 if __name__ 里调**，不在 import 时启动

## 8. stdout / stderr 行为

- **成功 stdout**：
  - 第 1 行 `[orchestrator] --input 默认: <path>`（仅当 `--input` 没传）
  - 第 2 行 `[orchestrator] --output 默认: <path>`（仅当 `--output` 没传）
  - 第 3 行 `✅ HTML 报告已生成: <path>`
  - 第 4 行 `   文件大小: <bytes> 字节`
  - 第 5 行 `   候选人: <n> 人`
  - **不是 JSON 格式**（cli_runner 用户需要从这 5 行 print 里解析）
- **失败 stdout**：
  - 缺 screening_results：1 行 JSON `{"status":"blocked", "exit_code":27, ...}`
  - 缺 run-id：argparse usage（写到 stderr）
- **stderr**：argparse 错误信息；其他无 stderr 输出

## 9. 与新统一 CLI 的差异（实现时必须注意）

| 项 | 旧脚本 | 新 CLI 报告 |
|----|--------|------------|
| stdout 格式 | 多行 print（含中文 emoji） | **统一 JSON：`{ok, command, status, run_id, data:{report_file}, next_action}`** |
| 退出码 | 真实子进程退出码 | **保留旧退出码语义**（0/2/27/1） |
| 路径 | 业务脚本自己拼 | CLI 解析 → cli_runner 透传 |
| finish() | 不调 | **不调**（与旧一致） |
| greet 触发 | 无 | **无**（与旧一致） |

## 10. cli_runner TOOLS 注册

```python
"generate_html_report": "html-report/scripts/generate_html_report.py",
```

新 CLI 走 `cli_runner.run_python_cli("generate_html_report", [...], check=False)` 复用。
