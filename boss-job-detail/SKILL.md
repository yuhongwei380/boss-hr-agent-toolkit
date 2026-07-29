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
python scripts/boss_jd.py <查询条件> [--job-name <name>] [--run-id <id>]
```

参数：
- `<查询条件>` — 三选一：
  - `加密岗位ID`：`a2bb7b1e7a76f0440nZ-39S0E1NS`
  - `数字 jobId`：`524499312`
  - `岗位名称`：`管培生`（精确匹配优先，否则模糊匹配）
- `--job-name`（可选）：自定义工作区目录名。**不传**则用 BOSS 返回的 `jobName` 清洗为合法目录名。
- `--run-id`（可选）：本次 run 的 ID，**默认自动生成** `YYYY-MM-DD_HHMMSS`。同一 run 内的所有脚本（list → download → score → HTML）必须传同一个 `--run-id`，产物才落在同一个 `runs/<run_id>/` 下。

## 工作流程

1. 通过 boss CLI 获取岗位列表，匹配查询条件
2. 用 patchright 连接 CDP 浏览器
3. 导航到岗位编辑页（`/web/chat/job/edit?encryptId=...`）
4. 等待 iframe 加载完成后提取表单内容
5. 输出到 `~/Desktop/boss-hr-output/<job_name>/runs/<run_id>/process/job_detail.json`

## 输出目录规范

```
~/Desktop/boss-hr-output/<岗位名>/
├── state/                                  # 跨 run 保留（不覆盖）
│   ├── candidate_pool.json                 # 累计候选人
│   ├── download_state.json                 # 下载状态
│   ├── resumes_master.json                 # 累计简历
│   └── collection_state.json
└── runs/
    └── 2026-07-27_083015/                  # 一次筛选任务
        ├── 2026-07-27_083015_<岗位名>_简历筛选报告.html
        └── process/
            ├── job_detail.json             ← 本脚本输出
            ├── recommend_geek_ids.json
            ├── new_resumes.json
            ├── failed_resumes.json
            ├── screening_results.json
            ├── run_summary.json
            └── run_log.txt
```

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

> **工作区约定**：所有数据统一存放在 `~/Desktop/boss-hr-output/<job_name>/` 下，由 `shared/output_manager.JobOutputManager` 管理（`boss-recommend-downloader` / `resume-screener` / `html-report` 共用同一规范）。

## 技术要点

- BOSS 管理后台为 iframe 架构：主页面是导航壳，表单内容在 `src="/web/frame/job/edit?..."` 的子框架中
- 使用 `domcontentloaded` 而非 `networkidle` 以提速（5-8s）
- boss CLI 输出为 GBK 编码，需 `decode('gbk')`
- `encryptJobId` 是后续推荐/下载/评分所有步骤的**岗位标识**，会作为 `candidate_key` 的前半段被使用