# status 命令验证报告（2026-08-03）

> 用户要求：每条命令单独提交前先核对旧实现 → 跑 baseline → 实现新 CLI → 对比。

## 1. baseline（旧实现里最接近 status 的入口）

`shared/confirm_run.py --status` 是旧工具包里**唯一**的"只读不修改"入口。
```bash
python -X utf8 shared/confirm_run.py \
    --job-name "线控底盘制动、转向工程师" \
    --encrypt-job-id "9a7759badfd95d350nFz3d-_F1NX" \
    --run-id "2026-07-31_172431" \
    --status
```
输出：
```json
{"status": "ok", "run_id": "2026-07-31_172431", "confirmed": true, "message": "已查询，未修改状态。"}
```
退出码：`0`

## 2. 新 CLI 实现

`boss_hr/cli.py status`（不调子脚本，直接读 `runs/<run_id>/run.json` + `process/` 扫描）：
```bash
python -X utf8 boss_hr/cli.py status \
    --job-name "线控底盘制动、转向工程师" \
    --encrypt-job-id "9a7759badfd95d350nFz3d-_F1NX" \
    --run-id "2026-07-31_172431"
```

## 3. 对比结果

| 字段 | baseline (confirm_run --status) | 新 CLI status | 一致？ |
|------|-------------------------------|---------------|--------|
| status 字段 | `"ok"` | `"ok"` | ✅ |
| run_id | `2026-07-31_172431` | `2026-07-31_172431` | ✅ |
| confirmed | `true` | `true` | ✅ |
| 退出码 | 0 | 0 | ✅ |
| 是否修改状态 | 否（仅读） | 否（仅读） | ✅ |

新 CLI 额外提供（旧 baseline 没有）：
- `workflow_state`：根据 `steps_done` 推断（`ready_to_score` / `ready_to_report` / `report_ready` / `finished` / `waiting_user_confirmation`）
- `steps_done` / `last_step` / `last_step_at` / `started_at` / `user_confirmed_at` / `finished_at`
- `paths.run_dir` / `paths.process_dir` / `paths.report_html`
- `process_files`：process/ 目录的文件清单（含 `recommend_geek_ids.json` / `new_resumes.json` / `scoring/` 等是否已落盘）

## 4. 边界用例

| # | 用例 | 输出 | 退出码 |
|---|------|------|-------|
| T1 | run_id 不存在 | `{"status":"blocked", ... "在岗位目录下不存在"}` | 23 |
| T2 | 缺 --run-id | argparse 报错 | 2（argparse 内定） |
| T3 | encrypt_job_id 错（导致 runs_dir 找不到） | `{"status":"blocked", ... "在岗位目录下不存在"}` | 23 |
| T4 | 缺 --encrypt-job-id（且无 env） | `{"status":"error", ... "缺少 encrypt_job_id"}` | 1 |

## 5. 已知遗留（不在本次提交修）

| # | 问题 | 分类 | 处理 |
|---|------|------|------|
| B-后续1 | `paths.run_dir` 输出 `C:\Users\yuyu/Desktop/...`（Windows 路径里夹 `/`） | B 类（path_utils 不统一） | 单独提交修 output_manager，CLI 暂时不动 |
| B-后续2 | T2 缺 --run-id 走 argparse 退出 2，未走我们自己定义的 22 | B 类（CLI 体验） | 单独提交加 catch + exit 22 包装；非阻塞 status 主验证 |

## 6. 结论

✅ status 命令实现并验证完成。新 CLI 的 status 是**新增**命令（旧工具包无对应），
不调子脚本，直接读共享层。核心字段与 baseline（confirm_run --status）一致，
新增 workflow_state / paths / process_files 是旧工具包没有的"分析能力"，不算行为偏离。

→ 第一轮任务全部完成。停止，等待用户确认后进入 report 命令迁移。
