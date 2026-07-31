---
name: boss-hr-auto
description: |
  **BOSS 直聘 HR 简历筛选全流程编排。** 当用户要求"筛选简历"、跑完整 5 步流程时使用。

  **触发场景**：
  - "筛选简历" / "筛一下这个岗位" / "帮我筛选候选人"
  - 需要从 BOSS 岗位提取 JD → 下载简历 → 评分 → 生成报告 → 打招呼 的一条龙需求

  **不触发场景**：
  - 仅问单条消息怎么回复（直接用 message 工具）
  - 非 BOSS 直聘的其他招聘平台

  **行为边界**：详见 [docs/BEHAVIOR_V1.md](../docs/BEHAVIOR_V1.md)。
  v1.1-skill-stable 只支持「一次完整的新筛选任务」；continue / batch / 多批累计均不支持。
type: workflow
---

# BOSS 直聘 HR 简历筛选全流程（v1.1-skill-stable）

> **入口声明**：本 Skill 是 boss-hr-agent-toolkit 唯一入口。下文按 Step 顺序调用子 Skill 的脚本。
>
> **本 Skill 是纯文档**。智能体按 Step 顺序逐个调用业务脚本。

## 前置条件（一次性）

| 项 | 要求 |
|---|---|
| Python | 3.10+ |
| Edge | 以 `--remote-debugging-port=9222` 启动（用户自行启动） |
| BOSS 招聘者 | 在上述 Edge 窗口内扫码登录 |
| 工具依赖 | `pip install -r requirements.txt`（唯一第三方：`patchright`） |

登录态自检由 `shared/cdp_preflight.check_login()` 提供（检查 `zp_at` + `wt2` + `bst` 三 cookie 都在）。**不要**用第三方 CLI 检测。

---

## 🚦 总流程（5 步 + 1 个确认门）

```
Step 1   boss_jd.py
   └─ 完成后停下，等用户回复『继续』
确认门  confirm_run.py
Step 2a  recommend_list.py
Step 2b  recommend_download.py
Step 3a  prepare_scoring_inputs.py
Step 3b  collect_llm_scores.py
Step 3c  score_resumes.py
Step 4   generate_html_report.py
Step 5   auto_greet.py
```

**数据流**：

```
BOSS 网页 (Edge 9222)
  ↓ patchright + CDP
业务脚本
  ↓ 写 runs/<run_id>/process/*.json
LLM 智能体（逐份读 scoring/inputs/，立即落盘 scoring/outputs/）
  ↓ 跑 collect_llm_scores.py
LLM 评分汇总 → _llm_scores.json
  ↓ score_resumes.py (edu 校准 + 加权 + tier)
screening_results.json
  ↓ generate_html_report.py
HTML 报告
```

---

## 🚨 run_id 铁律

| 规则 | 说明 |
|---|---|
| **新任务必创建新 run** | `boss_jd.py` 不传 `--run-id` 会自动调 `create_new_run()` 生成新 run_id |
| **禁止沿用旧 run_id** | run_id 是本次任务的数据边界，绝不沿用桌面 / state 累计文件 / 其他 run 的旧产物 |
| **继续旧任务** | 必须显式传 `--run-id <run_id>`；run 不存在或 encryptJobId 不匹配会报错 |

---

## 🚦 用户确认门

**铁律**：Step 1 完成后**必须停下**，等用户回复『继续』。

```
Step 1 (boss_jd.py)
   └─ 完成后：写 runs/<run_id>/run.json (confirmed=false)，打印 JSON 提示
        └─ 智能体看到提示立刻停下，等用户回复『继续』

用户回复『继续』
   └─ 智能体调用：python shared/confirm_run.py --job-name ... --encrypt-job-id ... --run-id ...
        └─ runs/<run_id>/run.json.confirmed=true，user_confirmed_at=<now>

Step 2~5
   └─ 脚本开头 is_confirmed(run_id) 检查，未确认 → SystemExit(20)
```

**禁止**：

- ❌ Step 1 完成后直接调 Step 2（会 SystemExit 20）
- ❌ 跳过 `confirm_run.py` 直接改 `runs/<run_id>/run.json.confirmed`
- ❌ 用任何历史 run 的产物补齐当前 run 缺的数据

---

## Step 1: 提取 JD

**执行**：`boss-job-detail/scripts/boss_jd.py`

**输入参数**：

| 参数 | 必填 | 说明 |
|---|---|---|
| `<query>` | 是 | encryptJobId / jobId / 岗位名（三选一） |
| `--job-name` | 是 | 岗位中文名（写入 jobs.json） |
| `--encrypt-job-id` | 是 | BOSS 的 encryptJobId（设工作区目录名） |
| `--run-id` | 否 | 不传则自动 `create_new_run()` |

**输出**：`runs/<run_id>/process/job_detail.json`

**完成后行为**：
- 写 `runs/<run_id>/run.json`（`confirmed=false`）
- 打印「waiting_user_confirmation」JSON
- **智能体必须停下**，等用户回复『继续』

---

## 确认门

**执行**：`shared/confirm_run.py`

**输入参数**：

| 参数 | 必填 | 说明 |
|---|---|---|
| `--job-name` | 是 | 同 Step 1 |
| `--encrypt-job-id` | 是 | 同 Step 1 |
| `--run-id` | 是 | Step 1 输出的 run_id |

**行为**：把 `runs/<run_id>/run.json.confirmed` 翻 `true`。

---

## Step 2: 下载候选人简历

**⚠️ 智能体在 Step 2 之前必须停下，等用户在 BOSS 推荐牛人页面手动调整筛选条件**（关键词、年龄、薪资、经验等），调整完后再继续。

### Step 2a: 拉候选人列表

**执行**：`boss-recommend-downloader/scripts/recommend_list.py`

| 参数 | 必填 | 说明 |
|---|---|---|
| `--job-name` | 是 | |
| `--encrypt-job-id` | 是 | |
| `--run-id` | 是 | |
| `--batch-size` | 否 | 默认 25 |

**输出**：`runs/<run_id>/process/recommend_geek_ids.json`

### Step 2b: 下载简历

**执行**：`boss-recommend-downloader/scripts/recommend_download.py`

| 参数 | 必填 | 说明 |
|---|---|---|
| `--job-name` | 是 | |
| `--encrypt-job-id` | 是 | |
| `--run-id` | 是 | |
| `--max` | 否 | 默认不限；建议 5~10 起步 |

**输出**：`runs/<run_id>/process/new_resumes.json`（成功简历）+ `failed_resumes.json`（失败列表）

---

## Step 3: 评分

### Step 3a: 净化层（拆 new_resumes.json）

**执行**：`resume-screener/scripts/prepare_scoring_inputs.py`

| 参数 | 必填 | 说明 |
|---|---|---|
| `--job-name` | 是 | |
| `--encrypt-job-id` | 是 | |
| `--run-id` | 是 | |

**输出**：
```
runs/<run_id>/process/scoring/
├── manifest.json                        # 候选人清单 + status（pending/scored/missing）
├── inputs/candidate_<geek_id>.json     # 净化输入（LLM 读这里）
├── outputs/candidate_<geek_id>.json    # LLM 落盘点（每评一份立即写一份）
└── _skipped.json                        # 被跳过的简历（ok=false / 缺 name）
```

### Step 3b: LLM 评分（智能体循环）

**姿势**：

1. 读 `scoring/manifest.json`，对每个 `status="pending"` 的候选人：
   - 读 `scoring/inputs/candidate_<geek_id>.json`（一份精简简历）
   - 调 LLM API 评 4 维度（`exp` / `skill` / `proj` / `major`），产出评分 object
   - **立即落盘**到 `scoring/outputs/candidate_<geek_id>.json`（单个评分 object）
2. 中途崩了下次重跑只补 `pending` 的那批

**评分输入 schema**（每个 outputs 文件里就是这一个 object）：

```json
{
  "name": "刘长琪",
  "school": "南京理工大学/机械电子工程/本科",
  "school_name": "南京理工大学",
  "work_years": "7 年",
  "match_type": "整车 CAE 建模 + 车身设计",
  "geek_id": "3c3c7a6ce2baa4f60Hx52t27E1o~",
  "job_id": "9a7759badfd95d350nFz3d-_F1NX",
  "dims": {"exp": 70, "skill": 72, "proj": 70, "major": 95},
  "highlights": ["..."],
  "concerns": ["..."],
  "advice": "..."
}
```

`edu` 维度**不要评**，由 `score_resumes.py` 用 school_tier 查表自动填。

**评分标准**：参见 [resume-screener/SKILL.md § 5 维度评分方法](../resume-screener/SKILL.md)。

### Step 3c: 合并 + 收尾

**执行**：`resume-screener/scripts/collect_llm_scores.py` → `resume-screener/scripts/score_resumes.py`

| 参数（两脚本相同） | 必填 | 说明 |
|---|---|---|
| `--job-name` | 是 | |
| `--encrypt-job-id` | 是 | |
| `--run-id` | 是 | |

**collect_llm_scores.py** 行为：
- 读 `scoring/manifest.json` + `scoring/outputs/candidate_*.json`
- 合并成 `runs/<run_id>/process/_llm_scores.json`
- 回写 `manifest.status` 为 `scored` / `missing` / `invalid`
- **幂等**：可重跑（覆盖式写，不重复拼接）

**score_resumes.py** 行为：
- 读 `_llm_scores.json`
- 用 `school_tier` 校准 edu
- 加权（25/25/25/15/10）+ total + tier 判定（≥70 推荐 / 60-69 待定 / <60 不推荐）
- 跨 run 去重（`state/scored_state.json`）
- 输出 `runs/<run_id>/process/screening_results.json`

---

## Step 4: 生成 HTML 报告

**执行**：`html-report/scripts/generate_html_report.py`

| 参数 | 必填 | 说明 |
|---|---|---|
| `--job-name` | 是 | |
| `--encrypt-job-id` | 是 | |
| `--run-id` | 是 | |

**输出**：`runs/<run_id>/<run_id>_screening_report.html`

---

## Step 5: 自动打招呼（可选）

**执行**：`boss-hr-greet/scripts/auto_greet.py`

| 参数 | 必填 | 说明 |
|---|---|---|
| `--job-name` | 是 | |
| `--encrypt-job-id` | 是 | |
| `--run-id` | 是 | |
| `--only-names` | 否 | 精准点名（多个用英文逗号） |

**默认行为**：CDP 真实点击 BOSS 打招呼按钮，按 `score≥70` 推荐 tier 招呼，最多 10 人。
**默认招呼成功 ≥1 时自动 `finish(run_id)`**，下次跑 `boss_jd.py` 自动开新 run。

---

## 数据边界与产物结构

所有 run 的产物统一在：

```
~/Desktop/boss-hr-output/<encryptJobId>/           # 工作区根（可用 BOSS_HR_OUTPUT_DIR 改）
├── jobs.json                                      # JobRegistry：encryptJobId → {name, company}
├── state/                                         # 跨 run 保留（不覆盖）
│   ├── candidate_pool.json
│   ├── download_state.json
│   ├── resumes_master.json
│   ├── scored_state.json
│   └── geek_positions.json
└── runs/                                          # 每次筛选任务一个 run_id 子目录
    └── <run_id>/
        ├── run.json                               # 该 run 独立状态（confirmed / steps_done / finished）
        ├── <run_id>_screening_report.html         # 最终 HTML 报告
        └── process/
            ├── job_detail.json                    # Step 1
            ├── recommend_geek_ids.json            # Step 2a
            ├── new_resumes.json                   # Step 2b
            ├── scoring/                           # Step 3a
            │   ├── manifest.json
            │   ├── inputs/candidate_<geek_id>.json
            │   ├── outputs/candidate_<geek_id>.json
            │   └── _skipped.json
            ├── _llm_scores.json                   # Step 3c（collect 合并产物）
            ├── screening_results.json             # Step 3c（score 收尾产物）
            └── greet_log.json                     # Step 5
```

**目录名 = encryptJobId**（不变 ID，避免中文 URL 编码问题）。`job_name` 仅作 `jobs.json` 元数据。

**6 个 CLI 脚本必传 `--encrypt-job-id`**（或 env `BOSS_HR_ENCRYPT_JOB_ID`），缺则直接报错退出，不静默回退。

---

## Windows 环境注意

所有脚本入口都 `import fix_encoding`，强制 stdout UTF-8。推荐显式用 `python -X utf8 ...` 或设 `PYTHONIOENCODING=utf-8`。

PowerShell / cmd 中文参数解析不稳定：智能体跨进程调用业务脚本时，建议通过 `shared/cli_runner.py` 用参数数组（不用 shell 字符串）。

---

## 基础模块

| 模块 | 关键导出 | 用途 |
|---|---|---|
| `shared/cdp_preflight` | `connect_cdp()` / `check_login()` / `get_cookies()` | 连 Edge 9222；检查 zp_at/wt2/bst cookie；识别当前页面 |
| `shared/recruiter_job_catalog` | `list_jobs()` / `resolve_recruiter_job(query)` / `fetch_job_detail(eid)` | BOSS 后端 API 拿岗位列表；按 encryptJobId/jobId/岗位名定位 |
| `shared/output_manager` | `JobOutputManager(...)` | 文件路径（`jd_path` / `new_resumes_path` / `screening_results_path` 等） |
| `shared/run_orchestrator` | `create_new_run()` / `bind_existing_run(id)` / `finish(id)` | run_id 生命周期 |
| `shared/job_resume_store` | `is_scored()` / `mark_scored()` | 跨 run 累计简历 + 评分去重 |
| `shared/cli_runner` | `run_python_cli(tool, args)` | Windows PowerShell 安全的 CLI 执行层（白名单 9 个 tool） |

完整接口详见 [shared/SKILL.md](../shared/SKILL.md)。

---

## 版本说明

| 版本 | 状态 |
|---|---|
| `v1-skill-stable` | 历史冻结版（已被 v1.1 取代） |
| `v1.1-skill-stable` | **当前冻结版**：清理文档矛盾；删除 spec 模板；明确实行为边界 |

不在 v1.1 范围内：continue / batch 合并 / 断点续评循环 / 并发 run / 跨平台（详见 [docs/BEHAVIOR_V1.md](../docs/BEHAVIOR_V1.md)）。