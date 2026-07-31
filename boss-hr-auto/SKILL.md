---
name: boss-hr-auto
description: |
  **这是整个 BOSS 直聘 HR Skill 包的唯一入口。** BOSS 直聘 HR 简历筛选全流程自动化编排。当用户要求"筛选简历"、走完整流程时使用。

  **触发场景**：
  - "筛选简历" / "筛一下这个岗位" / "帮我筛选候选人"
  - 需要从 BOSS 岗位提取 JD → 下载简历 → 评分 → 生成报告
  - 任何"一条龙"简历筛选需求
  - "下载推荐牛人简历" — 使用 boss-recommend-downloader 子流程

  **不触发场景**：
  - 仅问单条消息怎么回复（直接用 message 工具）
  - 非 BOSS 直聘的其他招聘平台

  **子 Skill 说明**：本包的 boss-job-detail、boss-resume-downloader、boss-recommend-downloader、resume-screener、html-report 均为此编排流程的子步骤，不应作为入口直接加载。请始终先加载本 Skill 获取完整工作流，再按 Step 顺序调用子 Skill。
type: workflow
---

> **stoken 说明**：本工具包全流程走 patchright 直连 CDP 浏览器
> （用浏览器真实的 wt2/zp_at/bst cookie），不依赖 `__zp_stoken__`。
> 不再需要 `boss_login_guard.py ensure-stoken` 之类的 stoken 同步操作。

# BOSS 直聘 HR 简历筛选全流程

> ** 入口声明**：本 Skill 是 boss-hr-agent-toolkit 项目唯一入口。下文的子 Skill 均应按本 Skill 的编排顺序调用，不得作为独立入口加载。
>
> **本 Skill 是纯文档，没有一把梭脚本。** 智能体按下文 Step 顺序逐个调用子 Skill 的 `scripts/`。

## 🚨 run_id 铁律：新任务必创建新 run，绝不沿用（2026-07-30 重构）

**铁律：**
- **新任务必须创建新 run_id** —— 无论上一个任务成功、失败、中断或未完成。
- **run_id 是本次任务的数据边界** —— 本次 run 缺什么就执行什么，绝不拿桌面 / state 累计文件 / 其他 run 的旧产物补齐。

`RunOrchestrator` 提供两个方法，语义清晰、不模糊：

| 方法 | 用途 | 行为 |
|------|------|------|
| `create_new_run()` | 新任务入口 | 无条件创建新 run（YYYY-MM-DD_HHMMSS，同秒自动加 _N 后缀） |
| `bind_existing_run(run_id)` | 继续旧任务 | 必须显式传 run_id；不传直接报错；run 不存在报错；encrypt_job_id 不匹配报错 |

**Step 1（boss_jd.py）：创建新 run**

```bash
# 新任务第一步：创建新 run
RUN_ID=$(python -X utf8 boss-job-detail/scripts/boss_jd.py "<查询>" \r
  --job-name "<岗位名>" \r
  --encrypt-job-id "<encryptJobId>" 2>&1 | grep -oP '(?<=run_id": ")[^"]+')
echo "Created RUN_ID=$RUN_ID"
```

boss_jd.py 默认会调 `create_new_run()`，把新 run 写到 `runs/<run_id>/`（每个 run 独立），状态写到 `runs/<run_id>/run.json`。

**Step 2~5：必须显式传 --run-id**

`recommend_list.py` / `recommend_download.py` / `score_resumes.py` / `generate_html_report.py` / `auto_greet.py` 的 `--run-id` **全部 required=True**，不传直接 argparse 报错退出。

```bash
python -X utf8 boss-recommend-downloader/scripts/recommend_list.py \r
  --job-name "$JOB_NAME" --encrypt-job-id "$ENCRYPT_ID" --run-id "$RUN_ID" \r
  --batch-size 25 --batch 1
```

### 新接口铁律：5 步脚本全部要传 `--encrypt-job-id`

**6 个 CLI 脚本**（`boss_jd.py` / `recommend_list.py` / `recommend_download.py` / `score_resumes.py` / `generate_html_report.py` / `auto_greet.py`）**都必须传 `--encrypt-job-id`**（或 env `BOSS_HR_ENCRYPT_JOB_ID`），缺则直接 `ValueError` 退出，**不会静默回退到中文目录名**。

**共享同一个 encryptJobId**：5 步必须传同一个 `--encrypt-job-id`，否则产物会落到不同工作区目录，list/download 找不到 score 文件，反之亦然。

### 当前 run 缺数据时怎么办？

| 场景 | 行为 |
|------|------|
| 跑 `score_resumes.py` 但当前 run 缺 `_llm_scores.json` | SystemExit(26) + JSON 错误：「当前 run 缺少简历评分输入，请先跑 Step 2」 |
| 跑 `generate_html_report.py` 但当前 run 缺 `screening_results.json` | SystemExit(27) + JSON 错误：「当前 run 缺少评分结果，请先跑 Step 3」 |
| 跑任何脚本但 `run_id` 在岗位目录下不存在 | FileNotFoundError 提示 run_id 不存在或属于别岗位 |

**禁止**（任一项都可能让智能体走错路）：
- ❌ 评分 / 报告脚本扫 `runs/*/` 找「最新」产物
- ❌ 评分脚本读 `state/resumes_master.json` 跨 run 补齐
- ❌ 报告脚本用桌面 HTML 报告当作输入
- ❌ 智能体凭 glob / mtime 找历史 JSON 文件
- ❌ 当前 run 缺产物时静默使用任何历史文件

### 跑完后清理

A 流程跑完后 `greet` **默认会自动 `finish()`**（只要招呼成功 ≥1 人且非 dry-run），下次跑 boss_jd.py 自动开新 run。

| 场景 | 行为 |
|------|------|
| 默认招呼成功 | 自动 finish()，下次跑 boss_jd.py 创建新 run |
| 显式 `--no-finish` | 不 finish，保留「回头补招呼同一 run」能力 |
| `--dry-run` 或招呼成功 0 人 | 不 finish，提示手动调 |

| ❌ 禁止 | ✅ 正确 |
|--------|--------|
| 调 `bind_or_create()` 让脚本自动决定 run | 调 `create_new_run()`（boss_jd.py 自动）或 `bind_existing_run(run_id)`（其他脚本） |
| Step 2~5 不传 `--run-id`（argparse 会报错） | boss_jd.py 创建新 run → 把 run_id 传给所有后续脚本 |
| 跑评分时缺 `_llm_scores.json` 用 `state/resumes_master.json` 补 | 直接报错，按错误提示执行上游 Step 2 |
| 跑报告时缺 `screening_results.json` 用桌面旧 HTML 报告 | 直接报错，按错误提示执行上游 Step 3 |
| 评分 / 报告脚本扫 `runs/*/` 找最新 | 只读 `--run-id` 指定的 `runs/<run_id>/process/` |
| 不传 `--encrypt-job-id` 跑 CLI（会 `ValueError`） | 5 步脚本统一传同一个 encryptJobId，或设 `BOSS_HR_ENCRYPT_JOB_ID` |
| 自己造 `_split_N.json` / `_llm_N.json` 等中间文件 | 直接写规范内的 `_llm_scores.json` |


> 评分环节即使有几十份简历，也**直接写一个 `_llm_scores.json`**。
> 需要分批处理时在内存里分，不要在 `process/` 里落临时分片文件。

## 🚦 用户确认门（2026-07-30 新增 · 必读）

**铁律：Step 1 完成后必须停下，等用户在 BOSS 调整完筛选条件并确认。**

```
Step 1 (boss_jd.py)
   └─ 完成后：写 runs/<run_id>/run.json (confirmed=false)，打印 JSON 提示
        └─ 智能体看到提示立刻停下，等用户回复『继续』

用户回复『继续』
   └─ 智能体调用：python shared/confirm_run.py \
                    --job-name ... --encrypt-job-id ... --run-id ...
        └─ run.json.confirmed=true，user_confirmed_at=<now>

Step 2~5 (recommend_list / recommend_download / score / report / greet)
   └─ 脚本开头 is_confirmed(run_id) 检查，未确认 → SystemExit(20)
```

**禁止清单：**
- ❌ Step 1 完成后直接调 `recommend_list.py` / `recommend_download.py`（会 SystemExit 20）
- ❌ 跳过 `confirm_run.py` 直接修改 run.json 的 `confirmed` 字段（属于污染审计日志）
- ❌ 调 `bind_or_create()`（已废弃，调用即抛 RuntimeError）

**run.json 结构：**
```json
{
  "run_id": "2026-07-30_103000",
  "encrypt_job_id": "9a7759badfd95d350nFz3d-_F1NX",
  "started_at": "2026-07-30 10:30:00",
  "confirmed": false,
  "user_confirmed_at": null,
  "steps_done": ["jd"],
  "last_step": "jd",
  "last_step_at": "2026-07-30 10:30:05",
  "finished": false,
  "finished_at": null
}
```

**旧 `state/current_run.json` 已彻底废弃**——每个 run 的状态独立写到 `runs/<run_id>/run.json`。

---

## 流程总览

本工具包提供**简历获取路径**：

### 路径：推荐牛人简历下载（适合从推荐列表获取）

```
用户提供岗位名 + 招聘者身份登录
     │
     ▼
[Step 1] 提取 JD ──── 使用 skill: boss-job-detail
     │
     ▼
[Step 2] 先暂停等待用户调整推荐牛人页面，用户示意继续后进行下载 ─ 使用 skill: boss-recommend-downloader
     │                  （从推荐牛人页面获取完整简历）
     ▼
[Step 3] 评分 ────── 使用 skill: resume-screener
     │
     ▼
[Step 4] 生成报告 ── 使用 skill: html-report
     │
     ▼
[Step 5] 自动打招呼 ── 使用 skill: boss-hr-greet
```


---

## 用到的 Skill 列表

| # | Skill | 在流程中的作用 |
|:-:|:------|:-------------|
| 1 | **boss-job-detail** | Step 1：CDP+iframe 提取完整岗位 JD |
| 2 | **boss-recommend-downloader** | Step 2：先暂停等待用户调整推荐牛人页面，用户示意继续后进行下载，从推荐牛人页面获取完整简历 |
| 3 | **resume-screener** | Step 3：岗位类型判断→硬门槛过滤→加权评分→排名输出 |
| 4 | **html-report** | Step 4：生成 HTML 可视化报告 |
| 5 | **boss-hr-greet** | Step 5：自动打招呼 |
| lib | **shared/recruiter_job_catalog** | 基础：BOSS 后端 API 拿岗位列表（浏览器内 fetch，自带 cookie） |
| lib | **shared/cdp_preflight** | 基础：CDP 连接 + 登录态探测（zp_at/wt2/bst cookie 检查） |

> **`shared/` 模块不是入口 Skill**，不被 AI 智能体直接加载；业务脚本 `import` 后调用。
> 完整接口与设计见 [`shared/SKILL.md`](../shared/SKILL.md)。

### 基础模块速览（2026-07-31 替代 boss_agent_cli）

| 模块 | 关键函数 | 用途 |
|---|---|---|
| `shared/cdp_preflight` | `connect_cdp()` / `check_login()` / `get_cookies()` | 连 Edge 9222；检查 zp_at/wt2/bst cookie；识别当前页面（recommend/chat/job_edit/login） |
| `shared/recruiter_job_catalog` | `list_jobs()` / `resolve_recruiter_job(query)` / `fetch_job_detail(eid)` | BOSS 后端 API 拿岗位列表；按 encryptJobId/jobId/岗位名（精确+模糊）定位 |
| `shared/output_manager` | `JobOutputManager(...)` | 文件路径（`jd_path` / `new_resumes_path` / `screening_results_path` 等） |
| `shared/run_orchestrator` | `create_new_run()` / `bind_existing_run(id)` / `finish(id)` | run_id 生命周期（run_id 是数据边界） |
| `shared/job_resume_store` | `is_scored()` / `mark_scored()` | 跨 run 累计简历 + 评分去重 |
| `shared/cli_runner` | `run_python_cli(tool, args)` | Windows PowerShell 安全的 CLI 执行层（白名单 9 个 tool） |

**调用约定**：

- 业务脚本（`boss_jd.py` / `recommend_list.py` 等）`import` 即可；不要 subprocess 调 `boss.exe`
- 登录态自检：`state = check_login(session)`；`not state['logged_in']` → 提示用户扫码
- 岗位查询：`job = resolve_recruiter_job(query)`；3 种 query 都接受；无匹配返回 `None`
- HTTP 调用全走浏览器内 `fetch`（`page.evaluate`），复用浏览器真实 TLS 指纹 + cookie，**不需要管 `__zp_stoken__`**

---

## 环境准备

### 必需安装

1. **Python 3.10+** — 从 python.org 安装，勾选 "Add Python to PATH"
2. **patchright** — `pip install patchright`（抗检测浏览器自动化，仅做 CDP 客户端用，不下载 Chromium）

### 环境变量（每次运行前必做）

**Bash / macOS / Linux：**
```bash
export PYTHONHOME=""
export PATH="$PATH:$HOME/.local/bin"
export PYTHONIOENCODING=utf-8
```

**PowerShell（Windows）：**
```powershell
$env:PYTHONHOME = ""
$env:PYTHONIOENCODING = "utf-8"
# PATH 通常已包含 uv 装工具的目录，无需追加
```

**cmd（Windows）：**
```cmd
set PYTHONHOME=
set PYTHONIOENCODING=utf-8
```

> 💡 **为什么不用 `-X utf8`？** 因为它只能强制 stdout 编码为 UTF-8；
> 但 Windows 中文 cmd 还会把 stdout 当 GBK 输出（除非设环境变量）。
> 推荐**同时**用两种方式以最大化兼容：
>
> - `python -X utf8 script.py ...`（强制 UTF-8 mode）
> - 或在环境里设 `PYTHONIOENCODING=utf-8`（推荐，影响所有子进程）

### 跨平台命令对照

| 操作 | Bash | PowerShell |
|------|------|-----------|
| Step 1 跑 JD | `python -X utf8 boss-job-detail/scripts/boss_jd.py ...` | `python -X utf8 boss-job-detail/scripts/boss_jd.py ...` |
| Step 2 收集名单 | `python -X utf8 boss-recommend-downloader/scripts/recommend_list.py ...` | `python -X utf8 boss-recommend-downloader/scripts/recommend_list.py ...` |
| 用户确认 | `python -X utf8 shared/confirm_run.py ...` | `python -X utf8 shared/confirm_run.py ...` |

> `-X utf8` 在 Windows / macOS / Linux 都可用。`PYTHONIOENCODING=utf-8` 适合需要后台 / 调度器场景。

### CDP 登录验证

```bash
# Edge 以调试模式启动（必须用 --user-data-dir 保留登录态）
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" ^
  --remote-debugging-port=9222 ^
  --user-data-dir="%USERPROFILE%\.workbuddy\chrome-profiles\boss-cdp"
```

在打开的 Edge 窗口里人工扫码登录 BOSS 招聘者。登录态由浏览器 cookie 自动持有，
下一步 `boss_jd.py` / `recruiter_job_catalog.list_jobs()` 会用 `shared/cdp_preflight.check_login()`
自检 `zp_at` / `wt2` / `bst` 三 cookie 是否齐全。无需手敲 CLI 命令。

---

## 🛡️ 安全执行层：cli_runner.py（2026-07-30 新增 · 推荐）

**问题**：Windows PowerShell / CMD 对中文、空格、JSON、特殊字符的参数解析不稳定。

**解决**：`shared/cli_runner.py` 用 `subprocess.run([...], shell=False)` + 参数数组启动白名单内的项目 CLI，中文 / JSON / 空格作为**单个完整参数**传递。

### 职责（只是执行器，不是流程编排器）

| ✅ 负责 | ❌ 不负责 |
|--------|---------|
| 用 `sys.executable` 启动项目 CLI | 创建 / 选择 / 确认 run_id |
| 用参数数组传参（不拼命令字符串） | 读 current_run.json / run.json 自动推断 |
| `subprocess.run(..., shell=False)` | 自动补 --run-id |
| 设置 UTF-8 环境 | 自动调 confirm_run / recommend_list / download |
| 固定 cwd 到工具包根目录 | 跑完整 pipeline |
| 捕获 stdout / stderr / 真实退出码 | 搜索桌面 / 历史文件 |
| 保留子进程退出码（含 20/26/27） | 替代 RunOrchestrator |
| 统一 JSON 输出 | 替代业务脚本的 argparse + 状态校验 |

### Python API

```python
from shared.cli_runner import run_python_cli

result = run_python_cli(
    "score_resumes",
    [
        "--job-name", "线控底盘制动、转向工程师",
        "--encrypt-job-id", "9a7759badfd95d350nFz3d-_F1NX",
        "--run-id", "2026-07-30_132000",
    ],
    timeout=600,
    # check=True 时 rc != 0 → 抛 CliRunnerError
)
print(result.returncode)
print(result.stdout)
```

### CLI 调用（智能体内部用 `--spec-file` 避免命令行参数解析问题）

> **2026-07-31 注**：项目**不再附带** spec_*.json 模板文件。spec 是 cli_runner
> 的内部调用方式——智能体在跨进程/跨平台调用业务脚本时构造临时 spec
> 文件（任意文件名），避免 Windows PowerShell/CMD 对中文、空格、JSON
> 字符串参数解析不稳定。
>
> 用户跑命令时**直接**用 `python -X utf8 ... <script> <args>` 即可，不需要 spec。

智能体构造 UTF-8 spec 文件（任意文件名，如 `/tmp/spec_xxx.json`）：

```json
{
  "tool": "score_resumes",
  "args": [
    "--job-name",
    "线控底盘制动、转向工程师",
    "--encrypt-job-id",
    "9a7759badfd95d350nFz3d-_F1NX",
    "--run-id",
    "2026-07-30_132000"
  ],
  "timeout": 600,
  "check": false
}
```

执行：

```bash
# Bash / macOS / Linux / PowerShell / cmd（命令相同）
python -X utf8 shared/cli_runner.py --spec-file /tmp/spec_xxx.json
```

统一 JSON 输出（stdout）：

```json
{
  "status": "success",
  "tool": "score_resumes",
  "returncode": 0,
  "stdout": "...",
  "stderr": ""
}
```

**失败示例**（子脚本 rc=20 → runner 原样返回 rc=20）：

```json
{
  "status": "failed",
  "tool": "recommend_list",
  "returncode": 20,
  "stdout": "...",
  "stderr": "用户尚未确认，禁止执行 Step 2"
}
```

### 工具白名单（cli_runner 仅接受以下 9 个 tool）

| tool 名 | 对应脚本 |
|---------|---------|
| `boss_jd` | `boss-job-detail/scripts/boss_jd.py` |
| `confirm_run` | `shared/confirm_run.py` |
| `recommend_list` | `boss-recommend-downloader/scripts/recommend_list.py` |
| `recommend_download` | `boss-recommend-downloader/scripts/recommend_download.py` |
| `prepare_scoring_inputs` | `resume-screener/scripts/prepare_scoring_inputs.py` |
| `collect_llm_scores` | `resume-screener/scripts/collect_llm_scores.py` |
| `score_resumes` | `resume-screener/scripts/score_resumes.py` |
| `generate_html_report` | `html-report/scripts/generate_html_report.py` |
| `auto_greet` | `boss-hr-greet/scripts/auto_greet.py` |

白名单外的 tool 立即拒绝（ValueError）。脚本路径逃逸（`../`）也拒绝。

### 如何执行 Step 1 并停在确认门

```bash
# 直接调业务脚本（推荐：用户/简单调试场景）
python -X utf8 boss-job-detail/scripts/boss_jd.py "线控底盘制动、转向工程师" \
  --job-name "线控底盘制动、转向工程师" \
  --encrypt-job-id "9a7759badfd95d350nFz3d-_F1NX"
# → 创建新 run，run.json.confirmed=false，输出 run_id，**当前智能体轮次结束**
```

智能体必须**停下**，等用户在 BOSS 调整完筛选条件后回复『继续』。

### 用户确认后执行 Step 2

```bash
# 1) confirm_run 把 run.json.confirmed 翻 true
python -X utf8 shared/confirm_run.py \
  --job-name "线控底盘制动、转向工程师" \
  --encrypt-job-id "9a7759badfd95d350nFz3d-_F1NX" \
  --run-id "<Step 1 拿到的 run_id>"

# 2) recommend_list 拉候选人 ID（注意：在 BOSS 推荐牛人页面手动调整筛选条件后再跑）
python -X utf8 boss-recommend-downloader/scripts/recommend_list.py \
  --job-name "线控底盘制动、转向工程师" \
  --encrypt-job-id "9a7759badfd95d350nFz3d-_F1NX" \
  --run-id "<run_id>" \
  --batch-size 25 --batch 1
```

### 直接 CLI（人工调试方式）

各业务脚本**仍保留独立 CLI 能力**，便于测试和人工排错：

```bash
# 直接调用（绕过 cli_runner）
python -X utf8 resume-screener/scripts/score_resumes.py \
  --job-name "<岗位名>" --encrypt-job-id "<id>" --run-id "<run_id>"
```

---

## Step 1: 提取 JD

**执行 skill：** `boss-job-detail`

**前置条件：**
- 招聘者身份已登录
- Edge 以 `--remote-debugging-port=9222 --remote-allow-origins=*` 运行

**核心操作：**
```bash
PYTHONHOME="" python -X utf8 boss-job-detail/scripts/boss_jd.py <查询条件> \
  --job-name "<岗位中文名>" \
  --encrypt-job-id "<boss_jd.py 返回的 encryptJobId>"
```

**输出：** 结构化 JD 数据（岗位名、学历、专业、经验、职责、技能栈），保存到 `process/job_detail.json`。

## Step 2: 从推荐牛人页面下载简历

**执行 skill：** `boss-recommend-downloader`

**适用场景：** 需要从推荐牛人页面获取候选人

**核心操作：**
```bash
# 公共参数（与 Step 1 同一个 encryptJobId + 同一个 run_id）
export ENCRYPT_ID="<Step 1 拿到的 encryptJobId>"
export JOB_NAME="<岗位中文名>"
export RUN_ID="<Step 1 拿到的 run_id>"

# 分批运行（推荐，不刷新页面，顺序固定）
python -X utf8 boss-recommend-downloader/scripts/recommend_list.py \
  --job-name "$JOB_NAME" --encrypt-job-id "$ENCRYPT_ID" --run-id "$RUN_ID" \
  --batch-size 25 --batch 1
python -X utf8 boss-recommend-downloader/scripts/recommend_download.py \
  --job-name "$JOB_NAME" --encrypt-job-id "$ENCRYPT_ID" --run-id "$RUN_ID" \
  --batch 1
# 评分后继续下一批
python -X utf8 boss-recommend-downloader/scripts/recommend_list.py \
  --job-name "$JOB_NAME" --encrypt-job-id "$ENCRYPT_ID" --run-id "$RUN_ID" \
  --batch-size 25 --batch 2
python -X utf8 boss-recommend-downloader/scripts/recommend_download.py \
  --job-name "$JOB_NAME" --encrypt-job-id "$ENCRYPT_ID" --run-id "$RUN_ID" \
  --batch 2

# 或一次性运行
python -X utf8 boss-recommend-downloader/scripts/recommend_list.py \
  --job-name "$JOB_NAME" --encrypt-job-id "$ENCRYPT_ID" --run-id "$RUN_ID"
python -X utf8 boss-recommend-downloader/scripts/recommend_download.py \
  --job-name "$JOB_NAME" --encrypt-job-id "$ENCRYPT_ID" --run-id "$RUN_ID"
```

> **注意**：先暂停等待用户调整推荐牛人页面，用户示意继续后进行下载。`recommend_download.py` 使用 patchright + 浏览器 fetch 方案（真实 Edge TLS 指纹），

**安全策略：**
- TLS 指纹：真实 Edge 浏览器（服务器无法区分）
- 滚动延迟：3-6 秒随机（模拟真人浏览）
- 简历获取：60-120 秒随机（每 5 份触发一次长延迟，模拟真人阅读 + 风控）
- 运行时间：建议工作时间（9:00-18:00）

**输出：** 候选人列表 + 完整简历数据，保存到 `process/` 文件夹。

---

## Step 3: 评分

**执行 skill：** `resume-screener`

**4 步执行：**
1. **岗位类型判断** — 技术岗 / 管培&非技术岗
2. **硬门槛过滤** — 学历不符 / 毕业年份不匹配 / 专业不相关 → 淘汰
3. **加权评分** — 按岗位类型选择 Mode A 或 Mode B 权重
   - ⚠️ **学历评分必须严格执行学校分档表**，禁止给所有人相同分数
   - ⚠️ **行动建议必须个性化**，禁止模板化
4. **总分排名** — 结构化输出每个候选人的评分明细 + 排名表

**输出：** 评分结果，保存到 `process/screening_results.json`。

---

## Step 4: 生成报告

**执行 skill：** `html-report`

**核心操作：**
```bash
python -X utf8 html-report/scripts/generate_html_report.py \
  --job-name "$JOB_NAME" \
  --encrypt-job-id "$ENCRYPT_ID" \
  --run-id "$RUN_ID"
```

**输出位置：** `~/Desktop/boss-hr-output/<encryptJobId>/runs/<run_id>/<run_id>_screening_report.html`

**输出内容：**
- 岗位基本信息 + JD 摘要（渐变色头部卡片）
- 筛选总览（三色汇总卡片）
- 候选人排名表（完整 5 维度列）
- 候选人详情（5 维度进度条 + 评分依据）
- 个性化行动建议（推荐/待定/不推荐）

**️ 行动建议必须个性化：**
- 推荐面试：每人必须写「候选人背景」+「沟通方向」
- 待沟通确认：每人必须写「优势」+「需确认问题」
- 禁止所有人一样的沟通方向

---

## Step 5: 自动打招呼

**执行 skill：** `boss-hr-greet`

**核心操作：**
```bash
# 默认按 score≥70 推荐 tier 招呼，最多 10 人
python -X utf8 boss-hr-greet/scripts/auto_greet.py \
  --job-name "$JOB_NAME" \
  --encrypt-job-id "$ENCRYPT_ID" \
  --run-id "$RUN_ID"

# 或精准点名（比如只给最高分那个人打招呼）
python -X utf8 boss-hr-greet/scripts/auto_greet.py \
  --job-name "$JOB_NAME" \
  --encrypt-job-id "$ENCRYPT_ID" \
  --run-id "$RUN_ID" \
  --only-names "邹亮"
```

**输出：** `runs/<run_id>/process/greet_log.json`（招呼成功 / 失败详情）

A 流程默认招呼成功 ≥1 时**自动 `finish(run_id)`**，下次跑 boss_jd.py 自动创建新 run。

---

## 文件结构

### 工具包内部结构（只读）

```
boss-hr-agent-toolkit/
├── boss-hr-auto/                    # 主入口 skill
├── boss-job-detail/                 # Step 1: JD 提取
├── boss-resume-downloader/          # Step 2A: 沟通列表简历下载
├── boss-recommend-downloader/       # Step 2B: 推荐牛人简历下载（新增）
├── resume-screener/                 # Step 3: 简历评分
├── html-report/                     # Step 4: 报告生成
└── shared/                          # 共享工具
    └── output_manager.py            # 统一文件路径管理
```

### 输出文件结构（所有 skill 必须遵守 · 新设计）

```
~/Desktop/boss-hr-output/                         # 工作区根（可用 BOSS_HR_OUTPUT_DIR 改）
├── jobs.json                                      # JobRegistry：encryptJobId → {name, company}
└── <encryptJobId>/                                # 目录名 = BOSS 的 encryptJobId
    ├── state/                                     # 跨 run 保留（不覆盖）
    │   ├── candidate_pool.json
    │   ├── download_state.json
    │   ├── resumes_master.json                    # 累计简历（含 _meta）
    │   ├── collection_state.json
    │   ├── scored_state.json
    │   └── geek_positions.json
    └── runs/                                       # 每次筛选任务一个 run_id 子目录
        └── <run_id>/
            ├── <run_id>_screening_report.html     # 最终 HTML 报告
            └── process/                            # 过程文件（留痕查阅）
                ├── run.json                        # 该 run 独立状态（confirmed / steps_done / finished）
                ├── job_detail.json                 # Step 1: boss_jd.py 输出
                ├── batch_1_ids.json / recommend_geek_ids.json  # Step 2B: list 输出
                ├── new_resumes.json                # Step 2B: recommend_download.py 输出
                ├── _llm_scores.json                # Step 3: LLM agent 评分
                ├── screening_results.json          # Step 3: score_resumes.py 输出
                ├── failed_resumes.json             # Step 2: 失败列表
                ├── greet_log.json                  # Step 5: auto_greet.py 输出
                └── run_log.txt                     # run_all.py 自动生成
```

### 🚨 重要规则（所有智能体必须恪守）

1. **禁止在桌面散落文件** — 所有输出必须放到 `boss-hr-output/<encryptJobId>/` 下
2. **目录名 = encryptJobId**（不再是中文岗位名）— 避免中文 URL 编码 / 文件 IO 翻车；`job_name` 仅作 `jobs.json` 元数据
3. **6 个 CLI 脚本必传 `--encrypt-job-id`**（或 env `BOSS_HR_ENCRYPT_JOB_ID`）—— 缺则 `ValueError` 退出，不静默回退
4. **HTML 报告放 run 目录** — 文件名含 run_id，永不覆盖历史报告
5. **中间数据放 `process/` 子文件夹** — 留痕查阅，不影响最终交付
6. **临时 Python 脚本任务结束后删除** — `generate_report.py` 等工具文件不要留在桌面
7. **复用 skill 内已有的 Python 脚本** — 禁止重复造轮子
8. **岗位文件夹不存在时自动创建** — 不要询问用户，直接创建

### 文件路径获取方式

```python
import sys
import os

# 添加 shared 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from output_manager import JobOutputManager

# 初始化输出管理器（新接口：必传 encrypt_job_id）
output = JobOutputManager(
    job_name='线控底盘制动、转向工程师',
    encrypt_job_id='9a7759badfd95d350nFz3d-_F1NX',
)

# 获取文件路径
print(output.report_path)               # HTML 报告路径
print(output.jd_path)                   # JD 数据路径
print(output.resumes_path)              # 简历数据路径
print(output.recommend_geek_ids_path)   # 候选人 ID 路径

# 任务结束后清理临时脚本
output.cleanup_temp_scripts()
```

---

## ⚠️ 重要规则

### 登录
- 必须两段式登录：CDP 扫码 → `boss login` 拾取 session
- 验证：`boss me` 返回真实用户信息
- `boss status` 不可靠（可能假阳性）

### 登录态自检（重要）

本工具包完全走 patchright + CDP，所有 BOSS HTTP 调用都在**浏览器内部**完成（`page.evaluate(fetch(...))`），
自动复用浏览器的 cookie + TLS 指纹，不需要单独同步 `__zp_stoken__`。

每个 Step 脚本入口都会用 `shared/cdp_preflight.check_login()` 自检：
- `zp_at` / `wt2` / `bst` 三个 cookie 是否齐全
- 当前页面是否在 BOSS 域（`page_kind` 字段：recommend / chat / job_edit / login / unknown）

如果自检失败：
- `logged_in=False` → 在 9222 那个 Edge 窗口里重新扫码
- `page_kind='login'` → 同上（被踢回登录页）
- `page_kind='unknown'` → 可能是 cookie 没同步，关掉 Edge 重启一次再扫

### 编码
- 所有脚本都强制 `PYTHONIOENCODING=utf-8` + `python -X utf8`，输出已是 UTF-8
- Windows PowerShell / cmd 直接跑会变 GBK；务必用 `python -X utf8 ...` 或设环境变量
- 看到乱码直接如实报告，不要猜测中文内容

### 防封
- 简历下载每次只下一份，脚本自带随机延迟
- 不要连续快速操作同一接口
- 推荐牛人下载：滚动 3-6 秒随机，简历获取 60-120 秒随机
- BOSS 后端 API 调用（如 `recruiter_job_catalog.list_jobs`）走浏览器内 fetch，
  复用浏览器真实 TLS 指纹，无须额外模拟
