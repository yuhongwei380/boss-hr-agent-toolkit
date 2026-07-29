---
name: boss-job-detail
description: |
  通过 CDP 浏览器提取 BOSS 直聘岗位完整 JD（职责、要求等）。

  **本 Skill 是 boss-hr-auto 编排流程的子步骤（Step 1），通常在 boss-hr-auto 工作流中调用，不应作为入口 Skill 直接加载。**
---

# BOSS 直聘岗位 JD 提取

通过 CDP 连接到已登录的浏览器，自动导航到岗位编辑页提取完整 JD。

## 前提条件

- Edge/Chrome 以 `--remote-debugging-port=9222` 启动
- Boss 招聘者 session 已登录

## 用法

```bash
python scripts/boss_jd.py <查询条件> [--job-name <name>] [--encrypt-job-id <encryptJobId>] [--run-id <id>]
```

参数：
- `<查询条件>` — 三选一：
  - `加密岗位ID`：`a2bb7b1e7a76f0440nZ-39S0E1NS`
  - `数字 jobId`：`524499312`
  - `岗位名称`：`管培生`（精确匹配优先，否则模糊匹配）
- `--job-name`（**必填**，元数据用，目录名不再用它）：岗位中文名，会写入 `jobs.json` 作可读标识。
- `--encrypt-job-id`（**必填**，新设计）：BOSS 返回的 `encryptJobId`，**直接作为工作区目录名**。例如 `9a7759badfd95d350nFz3d-_F1NX`。5 步脚本（list → download → score → HTML → greet）必须传同一个值，产物才落在同一个工作区目录。
- 也可设环境变量 `BOSS_HR_ENCRYPT_JOB_ID=<encryptJobId>` 作为 fallback（CLI 参数优先）。
- `--run-id`（可选）：本次 run 的 ID，**默认自动生成** `YYYY-MM-DD_HHMMSS`。同一 run 内的所有脚本必须传同一个 `--run-id`，产物才落在同一个 `runs/<run_id>/` 下。

> 🚨 **严格模式**：缺 `--encrypt-job-id`（且未设 `BOSS_HR_ENCRYPT_JOB_ID`）时脚本**直接报错退出**，不会静默回退到中文目录名——避免你以为跑了新路径、实际又落到中文路径的事故。

## 工作流程

1. 通过 boss CLI 获取岗位列表，匹配查询条件
2. 用 patchright 连接 CDP 浏览器
3. 导航到岗位编辑页（`/web/chat/job/edit?encryptId=...`）
4. 等待 iframe 加载完成后提取表单内容
5. 输出到 `~/Desktop/boss-hr-output/<encryptJobId>/runs/<run_id>/process/job_detail.json`

## 输出目录规范（新设计 · 2026-07-29+）

**目录名 = `encryptJobId`**（不再用中文岗位名），`job_name` 仅作为 `jobs.json` 里的可读元数据。

```
~/Desktop/boss-hr-output/
├── jobs.json                               # JobRegistry：encryptJobId → {name, company}
└── <encryptJobId>/                         # 目录名 = BOSS 返回的 encryptJobId（如 9a7759badfd95d350nFz3d-_F1NX）
    ├── state/                              # 跨 run 保留（不覆盖）
    │   ├── candidate_pool.json
    │   ├── download_state.json
    │   ├── resumes_master.json
    │   ├── collection_state.json
    │   ├── scored_state.json
    │   └── current_run.json
    └── runs/
        └── <run_id>/                       # 一次筛选任务
            ├── <run_id>_screening_report.html
            └── process/
                ├── job_detail.json         ← 本脚本输出
                ├── batch_1_ids.json
                ├── new_resumes.json
                ├── failed_resumes.json
                ├── _llm_scores.json
                ├── screening_results.json
                ├── greet_log.json
                └── run_log.txt
```

> **路径选择集中在 `shared/output_manager.JobOutputManager`**——CLI 脚本只接收并透传 `--encrypt-job-id`，不参与路径拼接，避免中文路径在 URL/文件 IO 里翻车。
>
> **多机器可移植**：通过环境变量 `BOSS_HR_OUTPUT_DIR` 改工作区根（默认 `~/Desktop/boss-hr-output`）。

## 输出格式

```json
{
  "jobName": "管培生",
  "encryptJobId": "a2bb7b1e...",
  "bodyText": "完整页面文本",
  "formValues": ["岗位职责：...", "职位名称", "..."],
  "parsed": {
    "title": "",
    "positionType": "",
    "location": "",
    "description": "岗位职责 + 任职要求 原文"
  },
  "_meta": {
    "run_id": "2026-07-27_083015",
    "fetched_at": "2026-07-27 08:30:30"
  }
}
```

> **工作区约定**：所有数据统一存放在 `~/Desktop/boss-hr-output/<encryptJobId>/` 下，**目录名直接用 BOSS 的 `encryptJobId`**（避免中文 URL 编码 / 文件名编码问题）。`job_name`（中文岗位名）只作为 `jobs.json` 里的可读元数据。
> 由 `shared/output_manager.JobOutputManager` 统一管理（`boss-recommend-downloader` / `resume-screener` / `html-report` / `boss-hr-greet` 共用同一规范）。
> **6 个 CLI 脚本都必须显式传 `--encrypt-job-id`**（或设 env `BOSS_HR_ENCRYPT_JOB_ID`），缺则直接报错——不会静默回退到中文目录名。

## 技术要点

- BOSS 管理后台为 iframe 架构：主页面是导航壳，表单内容在 `src="/web/frame/job/edit?..."` 的子框架中
- 使用 `domcontentloaded` 而非 `networkidle` 以提速（5-8s）
- boss CLI 输出为 GBK 编码，需 `decode('gbk')`
- `encryptJobId` 是后续推荐/下载/评分所有步骤的**岗位标识**，会作为 `candidate_key` 的前半段被使用