# 统一 CLI 真实 smoke 记录（2026-08-04）

> 数据来源：本会话实际执行（`refactor/unified-cli-v1` 分支，HEAD `4f4f219`）。
> 输出隔离目录：`~/Desktop/boss-hr-output-smoke`（**未污染用户真实 `boss-hr-output`**）。
>
> **本文件只记录脱敏结果**：eid 字符串 / 数量 / 状态码 / 哈希前缀。
> 不含候选人姓名 / geek_id / 简历正文 / cookie / token / 真实 contact info。

---

## 0. 环境

| 项 | 值 |
|---|---|
| 分支 | `refactor/unified-cli-v1` |
| HEAD | `4f4f219` |
| Edge 9222 | ✅ `Test-NetConnection localhost:9222` → True |
| BOSS 登录态 | ✅ zp_at / wt2 / bst 三 cookie 都在；`page_kind=recommend` |
| 真实岗位 | `9a7759badfd95d350nFz3d-_F1NX`（线控底盘制动、转向工程师） |
| 测试 run_id | `2026-08-04_090734` |
| 输出目录 | `~/Desktop/boss-hr-output-smoke`（隔离） |

---

## 1. start ✅

`boss-hr start 9a7759badfd95d350nFz3d-_F1NX --job-name ... --encrypt-job-id ...`

| 验证项 | 结果 |
|---|---|
| rc | **0** |
| status | `waiting_user_confirmation` |
| 新 run_id | `2026-08-04_090734`（新生成） |
| run.json.confirmed | **false** |
| job_detail.json | ✅ 写入 `process/job_detail.json`（formValues 4 项） |
| 三处 run_id 一致 | ✅ JSON output / run.json / job_detail._meta.run_id |
| 未越人工确认门 | ✅ confirm / fetch / score 全部未触发 |

**关键观察**：同 eid 跨 run 的 formValues 哈希一字不差（`347abfb83cc20adc`，4 项），
但**不是代码缓存** — 见 `docs/debug/boss_jd-cache-audit-2026-08-04.md`（commit `4f4f219`），
是 BOSS 后端编辑器对未修改过的岗位返回同一份表单（接口幂等性）。

---

## 2. confirm ✅

`boss-hr confirm --job-name ... --encrypt-job-id ... --run-id 2026-08-04_090734`

| 验证项 | 结果 |
|---|---|
| rc | **0** |
| status | `confirmed` |
| data.confirmed | **true** |
| user_confirmed_at | `2026-08-04 11:50:43`（已写入） |
| steps_done 变化 | 不变（confirm 不入 steps_done） |

---

## 3. fetch --count 1 ✅

`boss-hr fetch --job-name ... --encrypt-job-id ... --run-id ... --count 1`

| 验证项 | 结果 |
|---|---|
| rc | **0** |
| status | `candidates_fetched` |
| requested_count | 1 |
| listed_count | **15**（BOSS 推荐列表当前展示数） |
| downloaded_count | **1** |
| failed_count | **0** |
| next_action | `score` |
| recommend_geek_ids.json | ✅ 15 条 |
| new_resumes.json | ✅ 1 条 ok |
| failed_resumes.json | ✅ 存在且为 `[]` |
| 触发 score / report / greet | **未触发** |

---

## 4. score ✅

### 4.1 score #1

`boss-hr score ...`（第一次）

| 验证项 | 结果 |
|---|---|
| rc | **0** |
| status | `waiting_llm` |
| candidate_id | `fc79735b***` (脱敏前缀，原始长度 28) |
| remaining | **1** |
| next_action | `score_candidate_then_repeat` |

### 4.2 评分（脱敏）

| 维度 | 分 | 锚点依据 |
|---|---|---|
| exp | 45 | 3 年工龄锚点 75，但无任何底盘/制动/转向对口 → "完全跨行业"档 0.4× 接近 |
| skill | 35 | JD 硬性要求（线控制动/转向/AUTOSAR/CAN/UDS）全不会 → "硬伤"档 40-54 下限 −10 |
| proj | 30 | `project_experience: count=0`，无可验证项目 |
| major | 40 | 非车辆/机械/自动化优先专业 → "弱相关/无关"档 40 |
| edu | 60（脚本默认）| `school_tier` 查 `山西能源学院` → `tier=未知 score=None`，`score_resumes` 默认 60 标"需复核" |

`total = 60×0.25 + 45×0.25 + 35×0.25 + 30×0.15 + 40×0.10 = 43.5` ✓

### 4.3 score #2

`boss-hr score ...`（第二次，写完 output 后）

| 验证项 | 结果 |
|---|---|
| rc | **0** |
| status | `scoring_complete` |
| scored | **1** |
| next_action | `report` |
| merged | **1** |
| invalid | **0** |
| missing | **0** |

---

## 5. report ✅

`boss-hr report ...`

| 验证项 | 结果 |
|---|---|
| rc | **0** |
| status | `report_ready` |
| HTML 报告 | ✅ `<run_id>_screening_report.html`（12104 字节） |
| 分数 / tier | `43.5 / 不推荐` — 与 `screening_results.json` 一致 |
| finished | **false**（report 不 finish） |
| 触发 greet | **未触发** |

---

## 6. greet 零发送安全分支 ✅

`boss-hr greet ...`（不降阈值、不改分数、不点名）

| 验证项 | 结果 |
|---|---|
| rc | **0** |
| status | `greet_complete` |
| greeted | **0** |
| clicked_unverified | **0** |
| not_found | **0** |
| candidates_targeted | **0** |
| no_candidates | **true** |
| next_action | `done` |
| 实际发送 | **0**（候选人 43.5 < 阈值 70，auto_greet 提前 return） |
| CDP 连接 | **未连接**（5 秒内进程退出，run_log 显示"没有高分候选人，结束"） |
| BOSS 按钮点击 | **未发生** |
| run 目录 | ✅ 完整保留 |
| screening_results.json 哈希 | `b9e3049fc98bca8b`（未变） |
| HTML 报告哈希 | `770e01f8b55b6384`（未变） |
| finished | **false**（0 招呼不 finish） |
| 其他 run | 未受影响（`2026-08-04_114431` 保留） |

**修复双保险验证：**

| 修复 commit | 触发条件 | 本次表现 |
|---|---|---|
| `edc6959` (prune 防护) | atexit 时 `_SAVED=False` 调 `prune_if_empty()` | ✅ 触发 — `note_skip_if_unsaved` 只写日志 + `.greet_skip_noted` sentry，run_dir 完整保留 |
| `ad243ad` (maybe_finish) | `greeted_count>=1 && !dry_run` | ✅ 未触发 — `greeted=0`，`maybe_finish` 返回 False，`run.json.finished` 保持 false |

**run_log.txt 业务可观测：**

```
[13:24:15] === boss-hr-greet 启动 run_id=2026-08-04_090734 ===
[13:24:15] 岗位：线控底盘制动、转向工程师 | 阈值：70.0 | 上限：10 | dry_run=False
[13:24:15] 模式：scan_only=False skip_scan=False
[13:24:15] 没有高分候选人，结束
[13:24:15] ⚠️  本次 greet 未产生 greet_log.json；run_dir 完整保留: .../2026-08-04_090734
```

---

## 7. 唯一尚未真实验证的真实业务路径

> **必须如实记录为未完成**。本轮不许通过降低阈值 / 篡改评分 / 强制点名
> 把这位 43.5 分的候选人推过 70 分门槛来"完成" greet。

**未验证路径**：

```
存在 ≥70 分的真实候选人
    ↓
greet 进入浏览器实际点击 BOSS 打招呼按钮
    ↓
greeted >= 1
    ↓
maybe_finish → orch.finish(run_id=...)
    ↓
当前显式 run 的 run.json.finished = true
```

**待验证子点：**

| 子点 | 当前状态 |
|---|---|
| `maybe_finish(greeted=1)` 真的调 `orch.finish(run_id=...)` | 单元测过（`tests/test_auto_greet_maybe_finish.py`，12 例含真实 RunOrchestrator） |
| `edc6959` 在 0 候选人路径不删 run | 实测过（本次 smoke 触发） |
| 浏览器 patchright CDP 真实点击 "打招呼" 按钮 | **未测过** |
| 按钮 class 从 `btn-greet` → `btn-continue` 的验证选择器 | **未测过** |
| "已向牛人发送招呼" dialog 自动关闭 | **未测过** |
| BOSS 频率限制处理（10+ 后的 `clicked_unverified`） | **未测过** |
| 自动 finish 后 run.json.finished = true 在 BOSS 真实侧生效 | **未测过** |

完成 greet 真实验证需要：

- 真实账号存在 ≥1 位 ≥70 分候选人（本次 smoke 没有这样的人选）
- Edge 9222 + BOSS 登录态持续可用
- 用户明确批准发送招呼

**本会话**未做该路径验证，**未发送任何招呼**。

---

## 8. 概念澄清（防止误读）

### `.greet_skip_noted` 文件

- **是什么**：`edc6959` 修复引入的 atexit 哨兵文件，标记"本次 greet 未写出 greet_log"
- **不是什么**：**不是**成功招呼记录，**不**表示有人被打过招呼
- **触发条件**：脚本提前 return（无候选 / 异常退出），`_SAVED=False`
- **不存在的语义**：`run.json.finished=true` / `greeted>=1` / run 已 finish

### `next_action="done"`

- **是什么**：统一 CLI 当前工作流的"无下一项自动动作"
- **不是什么**：**不等于** `run.json.finished=true`
- **真实 finish 路径**：由 `auto_greet.maybe_finish()` 在 `greeted>=1` 时调
  `RunOrchestrator.finish(run_id=...)` 显式设置 `finished=true`
- **何时 `finished=true`**：仅当 `maybe_finish` 真正被触发且成功调完 `finish`；
  本次 smoke **未触发**（greeted=0）