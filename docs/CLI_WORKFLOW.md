# boss-hr CLI 工作流（GitHub 用户 / 开发者文档）

> 面向 GitHub 用户和开发者，**不是** Agent Skill。
> Agent Skill 看 [`boss-hr-auto/SKILL.md`](../boss-hr-auto/SKILL.md)。

---

## 1. 七个公开命令

| 命令 | 作用 | 何时调 |
|---|---|---|
| `boss-hr start` | 创建新 run，停在人工确认门 | 用户说"开始一个筛选任务" |
| `boss-hr confirm` | `confirmed` 翻 true；**不**入 `steps_done` | 用户回复"继续"后第一件事 |
| `boss-hr fetch --count N` | 拉推荐列表 + 下载 N 份简历 | confirm 后 |
| `boss-hr score` | 评分协调（一次返回 1 位候选人） | fetch 后循环到 `scoring_complete` |
| `boss-hr report` | 生成 HTML 报告 | `scoring_complete` 后 |
| `boss-hr greet` | 给 ≥70 分候选人打招呼（需用户明确批准） | 用户明确要求时 |
| `boss-hr status` | 读 `runs/<run_id>/run.json` + process 目录 | 任何时候想看当前 run 状态 |

## 2. 完整流程图

```
   ┌─────────────────────────────────────────────────────────────┐
   │ 1. boss-hr start <query> --job-name ... --encrypt-job-id ... │
   │    status: waiting_user_confirmation                        │
   │    → 返回 run_id                                            │
   └─────────────────────────────────────────────────────────────┘
                              ↓
                  ━━━━━━━━ 人工确认门 ━━━━━━━━
                  用户在 BOSS 推荐牛人页面调整筛选
                              ↓
                            用户回复 "继续"
                              ↓
   ┌─────────────────────────────────────────────────────────────┐
   │ 2. boss-hr confirm  --run-id <RID>                          │
   │    boss-hr fetch    --run-id <RID> --count N                │
   │    status: candidates_fetched                               │
   └─────────────────────────────────────────────────────────────┘
                              ↓
   ┌─────────────────────────────────────────────────────────────┐
   │ 3. boss-hr score    --run-id <RID>  (LLM 循环)              │
   │    第一次: status=waiting_llm                                │
   │      → 智能体读 input_file，按 resume-screener/SKILL.md 评 │
   │        4 维度（exp/skill/proj/major），写 output_file         │
   │      → 再调一次完全相同的 score                              │
   │    第二次: status=scoring_complete                          │
   └─────────────────────────────────────────────────────────────┘
                              ↓
   ┌─────────────────────────────────────────────────────────────┐
   │ 4. boss-hr report   --run-id <RID>                          │
   │    status: report_ready, data.report_file = <path>          │
   └─────────────────────────────────────────────────────────────┘
                              ↓
                              ╲╱
              ┌───────────────────────────────────┐
              │ 5. boss-hr greet  （可选 + 危险） │
              │    仅在用户明确批准时执行          │
              │    ≥70 分候选人 ≥1 时会真实点击    │
              │    0 候选人时安全跳过（no_candidates）│
              └───────────────────────────────────┘
```

## 3. start 后为何必须停止

`boss-hr start` 的语义是：**只**创建新 run，**只**返回 `run_id`。
然后智能体必须停下，等用户在 BOSS 网页调整筛选条件后回复"继续"。

这是 BEHAVIOR_V1 的强制约束 —— Step 1 完成后**必须**经人工确认门。
原因：BOSS 推荐结果对筛选条件极敏感（关键词、年龄、薪资、经验），自动跳过
会让 agent 用一个错的推荐池做后续下载/评分。

## 4. run_id 是数据边界

- `run_id` 决定本次任务的所有产物路径
- 同一 `encrypt_job_id` 下可以有多个历史 run；下游命令**必须**显式传
  同一个 `run_id`（来自 start 的返回），禁止扫描 `runs/`、禁止读
  `current_run.json`（已废弃）
- start 不接受 `--run-id`（argparse 拦截，rc=2）

## 5. score 为什么需要多次调用

`boss-hr score` 是个**两阶段状态机**：

| 阶段 | status | 智能体动作 |
|---|---|---|
| 协调 | `waiting_llm` | LLM 评**唯一一位**候选人并写 output_file |
| 收尾 | `scoring_complete` | 已完成，可调 `boss-hr report` |

LLM 不能一次写完所有候选人（违反"run_id 是数据边界" + 难以追溯每位评分）。
所以 LLM 必须按"读一位 → 评一位 → 写一位 → 重调 score"的循环工作。
每次 score 只处理一位候选人。

## 6. greet 为什么必须显式批准

`boss-hr greet` 是**真实写操作**：通过 BOSS 浏览器真实点击"打招呼"按钮，
候选人会收到消息。这件事不可逆。

- 默认按 score≥70 推荐 tier 招呼，最多 10 人
- 不得自动调（`report` 不自动 greet）
- 用户没明确说"打招呼"时**禁止**执行
- 不得为测试降低阈值（70 分是 hard-coded）
- 不得给不推荐候选人强制点名发送（`--only-names` 是合法但需用户确认）

## 7. 当前不支持

- `continue` — 旧 run 续跑
- `batch` / `--batch-size` / `--batch` 多批累计合并
- 自动查找最新 run
- 从其他 run 补数据
- 自动跳过人工确认门
- 自动 greet

未来扩展请新建 v1.2+ 版本；不要在当前 CLI 加 `continue` / `batch` 子命令。

## 8. 统一 CLI 与旧脚本的关系

```
通用智能体
  → boss-hr-auto/SKILL.md  （唯一工作流入口）
    → boss-hr CLI           （统一入口）
      → boss_hr/commands/   （7 个薄壳）
        → boss_hr/application/  （业务编排）
          → boss_hr/adapters/legacy_runner.py
            → shared/cli_runner.run_python_cli()
              → 旧业务脚本（boss_jd.py / auto_greet.py / 等）
                → patchright / CDP / BOSS 后端
```

**旧业务脚本保留且活跃**：它们是 `boss-hr` 通过 `cli_runner` 子进程调用的
真实实现。**没有**被复制进 `boss_hr` 包。

## 9. 命令示例（脱敏）

```bash
# 1. 开始任务
boss-hr start "<encryptJobId|jobId|岗位名>" \
  --job-name "<岗位中文名>" \
  --encrypt-job-id "<id>"

# → status=waiting_user_confirmation，run_id=2026-08-04_090734
# → 智能体停下，等用户在 BOSS 推荐牛人页面调整筛选条件

# 用户回复"继续"后：

# 2. 确认 + 拉候选人 + 下载 1 份
boss-hr confirm --job-name "<>" --encrypt-job-id "<>" --run-id "2026-08-04_090734"
boss-hr fetch   --job-name "<>" --encrypt-job-id "<>" --run-id "2026-08-04_090734" --count 1

# 3. 评分循环
boss-hr score --job-name "<>" --encrypt-job-id "<>" --run-id "2026-08-04_090734"
# → status=waiting_llm, candidate_id, input_file, output_file, remaining
# LLM 读 input_file、评 4 维度、写 output_file、再次调：
boss-hr score --job-name "<>" --encrypt-job-id "<>" --run-id "2026-08-04_090734"
# → status=scoring_complete

# 4. 报告
boss-hr report --job-name "<>" --encrypt-job-id "<>" --run-id "2026-08-04_090734"
# → status=report_ready, data.report_file

# 5.（可选 + 用户明确批准时）打招呼
boss-hr greet --job-name "<>" --encrypt-job-id "<>" --run-id "2026-08-04_090734"
```

## 10. 安装与运行

```bash
git clone https://github.com/<owner>/boss-hr-agent-toolkit
cd boss-hr-agent-toolkit
python -m pip install -e .

boss-hr --help                # 验证安装
```

**必须**保留完整源码目录；移动源码后重新 `pip install -e .`。
这是 GitHub 源码工具包版本，不是独立 wheel 分发版本。