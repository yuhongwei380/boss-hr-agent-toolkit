---
name: boss-agent-cli
description: |
  BOSS 直聘 CLI 命令参考手册 — 34 个顶层命令，招聘者/求职者双模式。
  本 Skill 是 boss-hr-auto 编排流程的参考引用，不应作为入口直接加载。
type: reference
---

# boss-agent-cli

> AI Agent 专用的 BOSS 直聘本地辅助 CLI 工具 — 34 个顶层命令，默认低风险模式聚焦本地辅助、只读优先、用户主动触发，不做自动触达、批量操作或平台数据抓取。

## Install

```bash
uv tool install boss-agent-cli
# 或 pipx install boss-agent-cli
```

## 登录流程（守卫脚本状态机）

**唯一入口：`scripts/boss_login_guard.py`（位于本 SKILL.md 同级 scripts/ 目录）。**

> ⚠️ 禁止凭单一弱信号宣布登录成功。`boss status` 返回 `logged_in: true` 只代表本地有凭证文件，**不代表凭证完整或可用**（可能假阳性，也可能缺 `__zp_stoken__` 的半登录）。

### 登录验收标准（三条强信号，全部满足才算 ready）

| # | 验收项 | 判定 |
|:-:|:------|:-----|
| 1 | 登录态存活 | `boss status --live` → `logged_in: true` 且 `live: true` |
| 2 | 凭证完整 | `auth_state == "full"`（`wt2` 与 `__zp_stoken__` 均存在） |
| 3 | 凭证可用 | `hr jobs list` 返回 `ok: true`（真实数据探针） |

**`auth_state == "partial"`（缺 `__zp_stoken__`）一律视为未完整登录**，不得带病继续后续步骤。

### 状态机（check → open-login / extract）

```bash
GUARD="<本skill目录>/scripts/boss_login_guard.py"

# 第1步：检查（exit: 0=ready / 2=degraded / 3=not_logged_in / 4=cdp_unreachable）
python "$GUARD" check

# ready → 继续后续任务
# degraded（浏览器在线但缺 stoken）→ 重提取，无需用户操作：
python "$GUARD" extract

# not_logged_in / cdp_unreachable / extract 后仍 degraded：
python "$GUARD" open-login      # 自动拉起 CDP 浏览器并打开登录页
# → 明确告知用户「登录页面已打开，请扫码登录」
# → 用户确认已扫码后：
python "$GUARD" extract          # 提取凭证并复检
```

### 硬性规则

1. `extract` 返回非 ready → **停止流程**，向用户报告缺失项（如 `__zp_stoken__`），禁止"先跑跑看"
2. `boss login --cdp` 返回成功 ≠ 凭证完整（stoken 可能不在浏览器 cookie 中），必须以 `extract` 的复检 verdict 为准
3. 守卫脚本已处理：`PYTHONHOME` 冲突清理、GBK 编码、`boss` 不在 PATH 时回退 `%USERPROFILE%\bin\boss.cmd`、CDP 未启动时自动拉起 Edge/Chrome

### 参考：Cookie 字段（仅背景知识，验收以上述三条为准）

关键 Cookie：`zp_at`（认证令牌）、`wt2`（一级登录态）、`__zp_stoken__`（二级令牌，候选人搜索/详情等只读流必需）、`__zp_seo_uuid__`、`bst`。

## Recruiter Workflow

| Command | Description |
|---------|-------------|
| `boss hr candidates <keyword>` | 搜索候选人 |
| `boss hr resume` | 查看/请求候选人简历 |
| `boss hr reply <friend_id> <message>` | 回复候选人消息 |
| `boss hr request-resume <friend_id> --job-id <id>` | 请求候选人附件简历 |
| `boss hr jobs list/online/offline` | 职位列表与上下线管理 |

## Key Commands

| Command | Description |
|---------|-------------|
| `boss schema` | 返回全部命令 JSON（Agent 首先调用） |
| `boss search <query>` | 搜索职位（8 维筛选） |
| `boss detail <security_id>` | 职位详情 |
| `boss hr resume <encryptGeekId> --job-id <encryptJobId> --security-id <securityId>` | 查看候选人简历 |
| `boss login` | 四级降级登录 |
| `boss status` | 检查登录态 |
| `boss doctor` | 诊断环境 |

## Output Conventions

- **stdout**: JSON only (structured envelope)
- **stderr**: Logs and progress (controlled by `--log-level`)
- **exit 0**: Success (`ok: true`)
- **exit 1**: Failure (`ok: false`)

## Platform & Role

```bash
# 招聘者模式
boss --role recruiter --platform zhipin --cdp-url http://localhost:9222 <command>

# 求职者模式（默认）
boss ... (no flags)
```

## Safety

- 不自动发消息（CLI 权限不足）
- 默认低风险模式阻断批量操作
- 候选人数据链路默认阻断敏感操作

## 端到端编排流程入口

> 本 SKILL 是底层 CLI 参考。boss-hr-agent-toolkit 的**端到端编排流程**（推荐牛人列表 → 下载 → LLM 评分 → HTML 报告 → 自动打招呼）见 `boss-hr-auto/SKILL.md`：
>
> - **新设计（2026-07-29+）**：工作区目录名 = `encryptJobId`（不再是中文岗位名）。`job_name`（中文岗位名）只作为 `jobs.json` 里的可读元数据。
> - 候选人累计池 + 简历去重落在 `~/Desktop/boss-hr-output/<encryptJobId>/state/`（跨 run 不覆盖）
> - 每次筛选任务一个 `runs/<run_id>/` 目录，过程文件落 `runs/<run_id>/process/`
> - 唯一键 `candidate_key = "{encrypt_job_id}:{encrypt_geek_id}"`，禁止用姓名
> - 6 个 CLI 脚本（`boss_jd.py` / `recommend_list.py` / `recommend_download.py` / `score_resumes.py` / `generate_html_report.py` / `auto_greet.py`）**必传 `--encrypt-job-id`**（或 env `BOSS_HR_ENCRYPT_JOB_ID`），缺则 `ValueError` 退出，**不静默回退到中文目录名**
>
> 完整工作流见 `boss-recommend-downloader/SKILL.md` 和 `boss-hr-auto/SKILL.md`。
