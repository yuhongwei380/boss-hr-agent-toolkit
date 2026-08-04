---
name: boss-hr-auto
description: |
  BOSS 直聘 HR 简历筛选全流程编排。当用户要求"筛选简历"、"跑 5 步流程"、
  "从岗位到报告"时使用。

  **触发场景**：
  - "筛选简历" / "筛一下这个岗位" / "帮我筛选候选人"
  - BOSS 直聘 HR 工具包全流程一次跑完

  **不触发场景**：
  - 仅问单条消息怎么回复（直接用 message 工具）
  - 非 BOSS 直聘的其他招聘平台

  **行为边界**：详见 [docs/BEHAVIOR_V1.md](../docs/BEHAVIOR_V1.md)。
  v1.1+ 只支持「一次完整的新筛选任务」；continue / batch / 多批累计均不支持。

  **编排入口**：统一 CLI `boss-hr`。**禁止直接调用旧业务脚本**。
type: workflow
---

# BOSS HR 统一筛选流程（v1.1+）

> 入口：`boss-hr` 统一 CLI。下文按步骤顺序调用 7 个公开命令。
>
> **本 Skill 是纯文档**。智能体按步骤顺序逐个调用统一命令。

## 行为边界

**支持**：

- 一次完整的新筛选任务；
- start → confirm → fetch → score → report；
- 用户明确要求时执行 greet。

**不支持**：

- continue / batch / 多批累计；
- 自动查找最新 run；
- 从其他 run 补数据；
- 自动跳过人工确认门。

## 公开命令（只此 7 个）

| 命令 | 作用 |
|---|---|
| `boss-hr start` | 创建新 run，停在人工确认门 |
| `boss-hr confirm` | 把 `confirmed` 翻 true |
| `boss-hr fetch --count N` | 拉候选人列表 + 下载 N 份简历 |
| `boss-hr score` | 评分协调（一次返回 1 位候选人） |
| `boss-hr report` | 生成 HTML 报告 |
| `boss-hr greet` | 给 ≥70 分候选人自动打招呼（需用户明确批准） |
| `boss-hr status` | 读 `runs/<run_id>/run.json` + process 目录 |

**禁止调用旧脚本**：`boss_jd.py` / `confirm_run.py` / `recommend_list.py` /
`recommend_download.py` / `prepare_scoring_inputs.py` / `collect_llm_scores.py` /
`score_resumes.py` / `generate_html_report.py` / `auto_greet.py` /
`cli_runner.py` / spec JSON。

## 标准流程

### 1. 开始任务：`boss-hr start`

```bash
boss-hr start "<encryptJobId|jobId|岗位名>" \
  --job-name "<岗位中文名>" \
  --encrypt-job-id "<id>"
```

**start 不接受 `--run-id`**（argparse 拦截，rc=2）。每次 start 必须创建新 run。

**期望返回**：

```json
{"ok": true, "command": "start", "status": "waiting_user_confirmation",
 "run_id": "<新 run_id>", "encrypt_job_id": "...", "job_name": "...",
 "next_action": "confirm"}
```

**拿到 run_id 后立即停下**。向用户说明：

> 请在 BOSS 推荐牛人页面调整筛选条件（关键词、年龄、薪资、经验等），调整完成后回复"继续"。

**禁止**：

- ❌ 同一轮继续执行 `confirm` 或 `fetch`
- ❌ 把 start 输出的 run_id 之外的值传给后续命令

### 2. 用户回复继续：`boss-hr confirm` + `boss-hr fetch`

```bash
boss-hr confirm --job-name "<>" --encrypt-job-id "<>" --run-id "<step1 输出的 run_id>"
boss-hr fetch   --job-name "<>" --encrypt-job-id "<>" --run-id "<>" --count N
```

- `confirm` 翻 `confirmed=true`、写 `user_confirmed_at`；**不入** `steps_done`。
- `fetch --count N` 先 list 再 download；返回 `candidates_fetched`。
- `fetch` 内部**不**触发 score / report / greet。

**run_id 必须来自 step 1**，禁止扫描 `runs/` 找最新、禁止读 `current_run.json`。

### 3. 评分：`boss-hr score` 循环

LLM 循环：

1. 调 `boss-hr score ...`。
2. 若返回 `status=waiting_llm`：**只读**返回的 `data.input_file`；
   按 [resume-screener/SKILL.md §5](../resume-screener/SKILL.md) 评 4 维度
   `exp / skill / proj / major`（0-100 最终分，**不评 edu**）；
   把单个评分 object 写入返回的 `data.output_file`；
   **再调一次完全相同的** `boss-hr score ...`。
3. 若返回 `status=scoring_complete`：进 step 4。

**单候选人约束**：每次 `score` 只处理一位候选人。LLM 不循环写多位。

**评分不改**：`total` 由 5 维度 weighted（edu 25% / exp 25% / skill 25% /
proj 15% / major 10%）算；tier ≥70 推荐 / 60-69 待定 / <60 不推荐。
edu 由 `score_resumes` 用 `school_tier` 强制覆盖，不接受 LLM 赋值。

### 4. 报告：`boss-hr report`

```bash
boss-hr report --job-name "<>" --encrypt-job-id "<>" --run-id "<>"
```

期望返回：

```json
{"ok": true, "command": "report", "status": "report_ready",
 "data": {"report_file": "<绝对路径>"}, "next_action": "greet_optional"}
```

把 `report_file` 路径告诉用户。**report 不自动调 greet**。

### 5. 打招呼：`boss-hr greet`（需用户明确批准）

**只有用户明确要求"打招呼"或"招呼这几个人"时**才执行：

```bash
boss-hr greet --job-name "<>" --encrypt-job-id "<>" --run-id "<>" \
  [--only-names "张三,李四"] [--threshold 70] [--max 10] [--dry-run]
```

**安全约束**：

- 不得降低阈值、不得改分数、不得强制点名不推荐候选人发送；
- score `< 70` 的候选人**不会**被打招呼（`no_candidates=true` 路径）；
- 单 run `finished=true` 仅在 `greeted >= 1` 且 `maybe_finish` 成功时被设置
  （`run.json.finished` ≠ `next_action="done"`）。

### 6. 状态查询：`boss-hr status`

```bash
boss-hr status --job-name "<>" --encrypt-job-id "<>" --run-id "<>"
```

只对**用户明确提供**的 `encrypt_job_id` + `run_id` 执行。**禁止扫描**最新 run。

## 铁律

| # | 规则 |
|---|---|
| 1 | 新任务必须调 `start`；start 不接受旧 run_id |
| 2 | start 后必须停下，等用户回复"继续" |
| 3 | 所有下游命令必须显式使用同一个 `run_id` |
| 4 | 禁止扫描 `runs/` 猜 run_id |
| 5 | 禁止读 `current_run.json`（已废弃） |
| 6 | 禁止借用其他 run 的产物 |
| 7 | 禁止创建 `spec_*.json` 模板 |
| 8 | 禁止直接调旧业务脚本（boss_jd / confirm_run / recommend_* / score_* / generate_html_report / auto_greet） |
| 9 | 禁止调 `cli_runner` 或 `shared.cli_runner.run_python_cli` |
| 10 | 禁止自动 greet（必须用户明确批准） |
| 11 | 禁止 continue / batch / 多批累计 |
| 12 | 禁止为测试而降低阈值、篡改评分 |

## 错误处理速查

| 命令 | rc | 含义 |
|---|---|---|
| 0 | 0 | 成功 |
| 1 | 1 | 缺 `encrypt_job_id`（业务层） |
| 2 | 2 | argparse 缺必填（`--job-name` / `--encrypt-job-id` / `--run-id`） |
| 23 | 23 | run 不存在 |
| 24 | 24 | run 与岗位不匹配 |
| 26 | 26 | 缺输入文件（`new_resumes.json` / `_llm_scores.json`） |
| 27 | 27 | 缺输出文件（`screening_results.json`） |

统一 CLI stdout 始终是单行 JSON。退出码语义保留旧脚本契约（不归一化）。