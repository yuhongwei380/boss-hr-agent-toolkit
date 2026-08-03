# 问题分类（A/B/C）— 2026-08-03

> 用户分类原则：
> - A：文档与代码不一致 → 以测试和当前真实代码为准；CLI 适配真实行为；修正文档
> - B：阻碍 CLI 重构的问题 → 补测试 → 最小修复 → 单独提交 → 再继续 CLI 迁移
> - C：与 CLI 无关的业务问题 → 不在本次修改；记录到 docs/KNOWN_ISSUES.md

## A. 文档与代码不一致（CLI 适配真实行为 + 修文档）

| # | 现象 | 实际行为（代码） | 文档说 | 处理 |
|---|------|----------------|--------|------|
| A1 | README.md 第 29-32 行 "🆕 v2 接口（2026-07-29+）" 把所有 6 个 CLI 标成 "目录名从中文岗位名改为 BOSS 的 encryptJobId"，但 `boss-hr-greet/scripts/auto_greet.py` 默认 `--job-name DEFAULT_JOB = "线控底盘制动、转向工程师"` 仍然按 job_name 处理 | 实际全部已用 encryptJobId（v1.1-skill-stable 后），文档基本正确 | 一致 | 无需改 |
| A2 | README.md 工作流图 5 步里 Step 1 的产物写的是 `<job-name>/process/job_detail.json`，但实际 v1.1 是 `~/Desktop/boss-hr-output/<encryptJobId>/runs/<run_id>/process/job_detail.json` | 旧 v1-skill-stable 写法；v1.1-skill-stable 早已修 | 文档与代码不一致 | 不动 README（本次不改文档），但 CLI 内部统一走 encryptJobId 路径 |
| A3 | `docs/BEHAVIOR_V1.md` 第 76 行 "❌ 改 cli_runner.py 白名单加新 tool" — 但本次新 CLI 第一阶段就要走 cli_runner，且第一轮我们要新加 status 命令（status 不在白名单里） | 矛盾 | B 类待决 | 见 B1 |

## B. 阻碍 CLI 重构（需最小修复 + 单独提交）

| # | 现象 | 阻碍哪个命令 | 最小修复方案 | 单独提交？ |
|---|------|------------|------------|----------|
| **B1** | `shared/cli_runner.TOOLS` 白名单里**没有** status 入口（status 是新 CLI 内部分析 run.json + process/ 目录，不需要调子脚本）。但 status 命令本身不在 BEHAVIOR_V1.md 允许的 "9 个 tool" 里（"❌ 改 cli_runner.py 白名单加新 tool"） | status 第一阶段 | **不动 cli_runner 白名单**；status 在新 CLI 里**直接读文件**（共享层 = output_manager + run_orchestrator），不走 subprocess。这是显式违反 BEHAVIOR_V1.md 但符合本任务"不修改 cli_runner.py"的设计方向 → 需要单独提交并在该提交里改 BEHAVIOR_V1.md 第 76 行 | ✅ |
| **B2** | `boss-job-detail/scripts/boss_jd.py` 当前 main() 用 `print(...)` 直接打 JSON 字符串（不是 file stdout），混合 print 行：第 117 `print(f"Found: ...")`、第 152 `print("⚠️ ...")`、第 176-189 `print(json.dumps({...}))`、第 190-192 三行 `print("Saved to...")` / `print("run_id: ...")` / `print("OK")` | start 命令 | start 在新 CLI 里解析 stdout：拿 `json.dumps({...})` 那段（第 176-189）的 JSON，前面的 Found/run_id/OK 三行只在调试时显示。**最小修复**：把 main() 里写 JSON 的那段改成唯一一段 `print(json.dumps(...))` 单独一行，前面的 Found/Saved/run_id/OK 改去 stderr（`print(..., file=sys.stderr)`）。这样新 CLI 解析 stdout 时不会被混杂的 print 污染 | ✅ |
| B3 | `boss-recommend-downloader/scripts/recommend_list.py` 第 59-69 行：用户未确认时 `print(json.dumps({...}))` 后 `raise SystemExit(20)`；exit code 20 正常。但 main() 里**没有**捕获 SystemExit，导致 argparse + 主流程错误时会向上抛非 0（rec 看起来 exit=1） | fetch 命令 | 不改 — 这是设计内。fetch 命令在新 CLI 里捕获 exit code 20 → 返回状态 `fetch_incomplete` 即可 | ❌ 不改 |
| B4 | `boss-hr-greet/scripts/auto_greet.py` 默认 finish() 自动跑（820 行附近），但是 `not_found=1` 退出 0 时 finish() 不调（BEHAVIOR_V1.md 第 51 行已声明） | greet 命令 | 不改 — 这是文档与代码一致的情况。CLI 适配这个行为即可 | ❌ 不改 |
| B5 | `tests/test_score_resumes.py::test_main_cli_end_to_end` 缺 `--run-id` 传参 | 整个测试（与 CLI 迁移无关） | 不改 — 测试 bug 但不影响业务 | ❌ 不改，归 C |
| B6 | `tests/conftest.py` 顶部 `sys.stdout.reconfigure(encoding="utf-8")` 与 pytest 9 捕获系统冲突，必须 `--capture=no -p no:cacheprovider` 才能跑 | 跑测试 | 不改 — pytest 7.4.4 + Python 3.13 不兼容是测试环境问题，不影响业务 | ❌ 不改，归 C |

## C. 与 CLI 无关的业务问题（记 KNOWN_ISSUES.md，本次不动）

| # | 现象 | 备注 |
|---|------|------|
| C1 | `_llm_scores.json` 中 `geek_id` / `job_id` 字段由 `collect_llm_scores.py` 兜底补全（BEHAVIOR_V1.md 第 49 行已记） | 已知 |
| C2 | `prepare_scoring_inputs.py` 输出 `manifest.json` 含全部候选人（含 `ok=false` 跳过）；`_skipped.json` 单独记录（BEHAVIOR_V1.md 第 50 行已记） | 已知 |
| C3 | `auto_greet.py` 的 `not_found=1` 退出 0 时 `finish()` 不自动调用（BEHAVIOR_V1.md 第 51 行已记） | 已知 |
| C4 | 测试 `test_main_cli_end_to_end` 缺 `--run-id`（业务脚本必填）| 提交一个 PR 修测试就行；不在本次 CLI 重构范围 |
| C5 | `pytest 7.4.4 + Python 3.13` capture 与 conftest.py 顶部 `sys.stdout.reconfigure` 冲突，必须 `-p no:cacheprovider --capture=no` | 测试环境问题 |
| C6 | README.md 第 29 行 "v2 接口" 章节没用具体路径举 encryptJobId 例子（不阻止 CLI 重构） | 文档优化 |
| C7 | 多批累计（--batch）行为不保证（BEHAVIOR_V1.md 第 41 行已记） | v1.2 计划 |
| C8 | 失败回滚 / 并发 run / 跨平台（BEHAVIOR_V1.md 第 43-45 行已记） | v1.2+ 计划 |

## 实施计划

1. **本任务第一轮**：只实现 status（B1）。status 不需要白名单工具，是新 CLI 内的纯读盘分析。
   - 修复：B1 单独提交（在 BEHAVIOR_V1.md 里把"不改 cli_runner 白名单"改为允许新增 status 类"读盘"命令）
   - 修复：B2 在 start 命令实现时再做（不是本轮范围）
2. **后续轮次**：按 status → report → confirm → score → fetch → start → greet 顺序迁移。每条命令独立提交，文档随之更新。
3. **C 类全部不动**，但把 C6 放进 docs/KNOWN_ISSUES.md（本轮顺手补一下，让仓库有"已知问题"档案）。
