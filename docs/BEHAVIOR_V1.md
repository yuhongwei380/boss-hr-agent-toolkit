# BEHAVIOR_V1 — v1-skill-stable 行为规范

> 本文档锁定 **`v1-skill-stable`** 这个 Git 标签对应的工具包行为边界。
> 之后的所有修改必须升级版本号（如 v1.1、v2），不再直接修改此冻结版本。

## 1. 已支持

工具包可以**端到端跑完一次新的筛选任务**，流程如下：

```
Step 1   boss_jd.py                  → 写 runs/<run_id>/process/job_detail.json
   ↓    智能体停下，等用户回复『继续』
Step 2a  confirm_run.py              → run.json.confirmed = true
Step 2b  recommend_list.py           → batch 1 候选人 ID（30 人）
Step 2c  recommend_download.py      → 下载 N 份完整简历到 new_resumes.json
Step 3a  prepare_scoring_inputs.py   → 拆 scoring/{inputs/, outputs/, manifest.json}
   ↓    LLM 逐份评，每评一份立即落盘 scoring/outputs/candidate_<geek_id>.json
Step 3b  collect_llm_scores.py       → outputs/ 合并成 _llm_scores.json
Step 3c  score_resumes.py            → edu 校准 + 加权 + tier 判定 → screening_results.json
Step 4   generate_html_report.py     → HTML 可视化报告
Step 5   auto_greet.py               → 给推荐 tier 候选人自动打招呼
```

**实测参数**（2026-07-31 run `2026-07-31_134548`）：
- 岗位：线控底盘制动、转向工程师（encryptJobId `9a7759badfd95d350nFz3d-_F1NX`）
- 候选人：5 份，全部评分，1 推荐 + 4 不推荐
- HTML 报告：~/Desktop/boss-hr-output/9a7759badfd95d350nFz3d-_F1NX/runs/2026-07-31_134548/2026-07-31_134548_screening_report.html

## 2. 不支持

以下场景在 v1-skill-stable **未实现或不保证行为正确**，需要升级到后续版本：

| 场景 | 当前行为 |
|---|---|
| **`continue` 续跑** | 没有 `continue` 子命令。run 失败后必须新建 run 重来；旧 run 保留作为审计日志 |
| **多批累计** | `--batch N` 只接受单一数字；同一 run 内跑多个 batch 不会自动合并为一份 `new_resumes.json` |
| **多批累计创建** | 没有「先把 5 个 batch 全部下完，再统一评分」的合并模式；每批结束后跑 `score_resumes` 会跨 batch 评分 |
| **断点续评** | `collect_llm_scores.py` 支持幂等合并（manifest.status 字段），但**没有自动扫描 missing → 重跑命令的循环** |
| **失败回滚** | Step 2b/c 下载失败时 `failed_resumes.json` 记录，但**不会自动重试**；用户/智能体需手工判断 |
| **并发 run** | 同一 encryptJobId 同时多个 run 会冲突（state/scored_state 共享）；不支持 |
| **跨平台** | 当前在 Windows + Git Bash 验证；macOS / Linux 需自测 |

## 3. 已知的次要问题（不阻断 v1）

- `_llm_scores.json` 中 `geek_id` / `job_id` 字段由 `collect_llm_scores.py` 兜底补全，LLM 漏写也不会失败
- `prepare_scoring_inputs.py` 输出 `manifest.json` 包含所有候选人（含 `ok=false` 跳过）；`_skipped.json` 单独记录被跳过的
- `auto_greet.py` 的 `not_found=1` 退出码 0 时 `finish()` 不自动调用，下次跑 `boss_jd.py` 会再创建一个新 run（这是预期行为）

## 4. 完成标准（v1-skill-stable 冻结条件）

| 检查项 | 状态 |
|---|---|
| `boss-agent-cli/` 目录已删除 | ✅ |
| `requirements.txt` 只剩 `patchright` | ✅ |
| `subprocess boss` 调用 0 处 | ✅ |
| `boss_jd.py` 不再 import subprocess | ✅ |
| 业务脚本全部用 `shared/recruiter_job_catalog` + `shared/cdp_preflight` | ✅ |
| `cli_runner` 白名单 9 个 tool 全通过 `--help` 烟测 | ✅ |
| 端到端冒烟（Step 1→2→3→4）全跑通 | ✅ |
| 17/17 cli_runner 测试 + 6/6 job_registry 测试通过 | ✅ |

**冻结**：本版本已打 Git 标签 `v1-skill-stable`，不再直接修改。

## 5. 版本演进路径

后续版本的预期方向（**不在 v1 范围内**）：

- **v1.1**：`continue` 子命令 + 多批合并评分
- **v1.2**：自动 missing → 重跑评分循环
- **v2.0**：彻底移除所有 BOSS 兼容代码（`boss.exe` 注释、schema 兼容 `data=[]` 等），只保留新模块路径

---

> **本版本的所有修改请开新分支**：基于 `v1-skill-stable` 拉分支，PR 合入 main 后打新标签。
> 不要直接在 main 上改完再回头打 `v1-skill-stable` 覆盖。