# 旧脚本 → 新统一 CLI 命令映射（2026-08-03）

## 1. 总览

新统一 CLI 计划提供 7 个命令（按官方要求冻结）：
`boss-hr start | confirm | fetch | score | report | greet | status`

V1.1-skill-stable 旧项目里的 18 个 .py 脚本/库 + 9 个 cli_runner 白名单 tool，
按职责一对一映射如下（不重复业务逻辑、不复制到 boss_hr 包）。

## 2. 一对一映射表

| 新命令 | 旧入口（cli_runner 白名单） | 旧脚本里负责实现的函数 | 输入 | 输出文件 | 退出码（业务侧） | 备注 |
|--------|---------------------------|----------------------|------|---------|----------------|------|
| `start`     | `boss_jd`           | `boss_jd.py:extract_jd`（新建，调用现有 main 的逻辑） | `--query`（encryptJobId/jobId/岗位名）、`--job-name`、`--encrypt-job-id` | `runs/<run_id>/process/job_detail.json`、`runs/<run_id>/run.json` (confirmed=false) | 0 / 1（找不到岗位） | 当前 `extract_jd` 函数在 v2 项目已存在；本仓库要新建同样的包装函数，main() 保持不变 |
| `confirm`   | `confirm_run`       | `shared/confirm_run.py:confirm_run(job_name, encrypt_job_id, run_id, status_only)` | `--job-name`、`--encrypt-job-id`、`--run-id`、（可选）`--status` | `runs/<run_id>/run.json` (confirmed=true) | 0 / 1（缺参数）/ 22（缺 --run-id）/ 23（run 不存在）/ 24（run 与岗位不匹配） | 直接 import 函数；不走 subprocess |
| `fetch`     | `recommend_list` + `recommend_download` | `recommend_list.get_recommend_candidates(...)` + `recommend_download.download_resumes(...)` | `--job-name`、`--encrypt-job-id`、`--run-id`、`--count N` | `runs/<run_id>/process/recommend_geek_ids.json`、`new_resumes.json`、`failed_resumes.json` | 0 / 20（用户未确认） | 新 CLI 在 `boss_hr/application/` 里直接 import 这两个函数；旧 main() 保留兼容 |
| `score`     | `prepare_scoring_inputs` + `collect_llm_scores` + `score_resumes` | `prepare.main()` / `collect.main()` / `score.main()` | `--job-name`、`--encrypt-job-id`、`--run-id` | `runs/<run_id>/process/scoring/{manifest.json, inputs/, outputs/, _skipped.json}` → `_llm_scores.json` → `screening_results.json` | 0 / 26（缺 _llm_scores.json）/ 1（缺 new_resumes.json） | 状态机：`score` 第一遍返回 `waiting_llm` 给 LLM 写入 `outputs/`；LLM 写完后再 `score` 一次自动 finalize → `ready_to_report` |
| `report`    | `generate_html_report` | `generate_html_report.main()` | `--job-name`、`--encrypt-job-id`、`--run-id` | `runs/<run_id>/<run_id>_screening_report.html` | 0 / 27（缺 screening_results.json） | 直接 import main() |
| `greet`     | `auto_greet`        | `auto_greet.auto_greet(job_name, run_id, encrypt_job_id, only_names, ...)` | `--job-name`、`--encrypt-job-id`、`--run-id`、（可选）`--only-names` | `runs/<run_id>/process/greet_log.json`、`run_log.txt` | 0（默认 success） / 1（高分候选人未匹配） | v1.1 默认自动 finish()；v2 用 `--no-finish` 保留续招呼能力 |
| `status`    | **无对应旧脚本**    | 由新 CLI 内部构造：读 `runs/<run_id>/run.json` + `process/` 目录扫描 | `--job-name`、`--encrypt-job-id`、`--run-id`（必须显式传；不传报错） | stdout JSON：`{run_id, status, confirmed, last_step, finished, paths: {...}}` | 0 / 41（run 不存在） | 第一轮任务唯一新写的命令 |

## 3. 跨命令共享层（不直接映射到单一命令）

| 新 CLI 内部层 | 旧库 | 用途 |
|--------------|------|------|
| `boss_hr.application.screening_workflow` | `shared/run_orchestrator.py:RunOrchestrator` | run_id 数据边界；create_new_run / bind_existing_run / confirm_run / mark_done / finish |
| `boss_hr.application.screening_workflow` | `shared/output_manager.py:JobOutputManager` | 路径定位（runs/<run_id>/process/...） |
| `boss_hr.application.scoring_workflow` | `resume-screener/scripts/score_resumes.py:calc_tier / calc_weighted / calc_total / validate_score / candidate_to_report / build_actions / build_meta` | 评分核心算法；可被新 CLI 直接 import |
| `boss_hr.application.scoring_workflow` | `resume-screener/scripts/school_tier.py:lookup` | 学历分档查表 |
| 所有命令 | `shared/cdp_preflight.check_login` | 登录态自检（start/fetch/greet 这类需要浏览器连 BOSS 的命令前置） |
| 所有命令 | `shared/cli_runner.run_python_cli` | **第一阶段**走 subprocess 的统一执行通道；后续逐步替换为直接 import |

## 4. 实施顺序（用户已指定）

按 "status → report → confirm → score → fetch → start → greet" 顺序，每条命令独立提交。

每条命令执行步骤：
1. 读对应旧脚本及测试
2. 记录入参/输入文件/输出文件/退出码/状态修改
3. 用 fixture 建基线（旧脚本的行为）
4. 在新 CLI 中实现对应命令
5. 用同一份输入分别跑旧脚本和新 CLI
6. 对比：returncode、JSON 关键字段、run_id、输出路径、生成文件、状态变化
7. 对比通过 → 进入下一条

## 5. 不映射到命令的旧脚本

- `shared/fix_encoding.py`：仅 23 行工具（Windows UTF-8 stdout reconfigure），保持库
- `shared/job_resume_store.py`：跨 run 简历池（state/resumes_master.json），保持库
- `shared/job_registry.py`：jobs.json 注册表，保持库
- `shared/human_interaction.py`：拟人化鼠标/滚动工具，保持库
- `shared/recruiter_job_catalog.py`：BOSS 后端 list_jobs / resolve_recruiter_job 封装，保持库
- `shared/cdp_preflight.py`：CDP 登录态自检，保持库
- `boss-recommend-downloader/scripts/run_all.py`：已被 boss-hr-auto 主流程替代，本次不迁移

## 6. 第一阶段实现策略（用户指定）

> 统一 CLI → shared.cli_runner.run_python_cli() → 现有脚本

第一阶段新 CLI 内部全部走 `cli_runner.run_python_cli(tool, args, timeout, check=True)`，
读 stdout 的 JSON 行，统一 exit code + 统一外层包装。

禁止创建 spec 文件（已对齐 BEHAVIOR_V1.md "❌ 新增 spec_*.json 模板到项目根"）。

后续逐步把旧脚本改为：
- 业务函数（import_legacy_module 调用）
- 旧 main() 兼容入口（保留 subprocess 调用方式）

新 CLI 和旧脚本必须调用同一份业务函数。
