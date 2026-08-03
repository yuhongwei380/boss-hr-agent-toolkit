# Fetch 基线（2026-08-03）

工具：`tools/baseline_fetch.py` → `artifacts/refactor/fetch-baseline.json`（静态分析）

## 1. fetch 链路真实参数（从源文件读出，不猜）

### recommend_list.py
| 参数 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `--job-name` | 否 | "车架工程师" | 旧默认值；新 CLI 必须显式传 |
| `--encrypt-job-id` | 否 | None | env 兜底 |
| `--max` | **否** | None | **最大拉取数**（普通模式） |
| `--batch-size` | 否 | None | 分批模式（**新 CLI 不暴露**） |
| `--batch` | 否 | None | 分批模式（**新 CLI 不暴露**） |
| `--run-id` | **是** | — | argparse required |

业务函数：`get_recommend_candidates(job_name, max_candidates, batch_size, batch_number, run_id, encrypt_job_id)`

### recommend_download.py
| 参数 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `--job-name` | 否 | "线控底盘制动、转向工程师" | 旧默认值；新 CLI 必须显式传 |
| `--encrypt-job-id` | 否 | None | env 兜底 |
| `--batch` | 否 | None | 分批模式（**不暴露**） |
| `--max` | **否** | None | **最大下载数** |
| `--pause-every` | 否 | **5** | 每下载 N 份后长延迟 |
| `--pause-min` | 否 | **60** | 长延迟最小秒 |
| `--pause-max` | 否 | **120** | 长延迟最大秒 |
| `--run-id` | **是** | — | argparse required |
| `--from-pool` | 否 | False | 从 candidate_pool 跨 run 通杀（**不暴露**） |

业务函数：`download_resumes(job_name, batch, max, pause_every, pause_min, pause_max, run_id, from_pool, encrypt_job_id)`

**关键发现**：
- 两个脚本都用 `--max N`（不是 `--max-count` / `--count`）
- 下载节流参数（pause_every/min/max）已硬编码默认值；**新 CLI 不改写它们**

## 2. 守卫（前置校验）

| 守卫 | 来源 | 退出码 |
|------|------|-------|
| run 不存在（bind_existing_run FileNotFoundError） | RunOrchestrator | 1（未捕获 Python 抛非 0） |
| run 与岗位不匹配（RuntimeError） | RunOrchestrator | 1 |
| **未 confirmed**（is_confirmed=False） | RunOrchestrator | **20** + JSON blocked |
| 缺 run_id | argparse | 2 |

## 3. 真实文件副作用（读 JobOutputManager / JobResumeStore API）

| 文件 | 写入者 | 触发 |
|------|--------|------|
| `runs/<run_id>/process/recommend_geek_ids.json` | list | list 成功（普通模式） |
| `runs/<run_id>/process/batch_N_ids.json` | list | list 成功（分批模式） |
| `runs/<run_id>/process/batch_state.json` | list | 分批模式 |
| `runs/<run_id>/process/new_resumes.json` | download | download 成功（覆盖） |
| `runs/<run_id>/process/failed_resumes.json` | download | download 跑过（覆盖） |
| `state/resumes_master.json` | JobResumeStore | download 成功调 `save_resume()` |
| `state/download_state.json` | JobResumeStore | download 调 mark_*（success / limit_hit / failed） |
| `state/candidate_pool.json` | list 或 download | list 写 pool（隐式）；download `--from-pool` 读 |

## 4. stdout / stderr 格式

两个脚本都直接 `print()` 中文消息，**非 JSON**：
- list: "总共获取：N 位候选人"、"已保存到：<path>"、"本批目标：..."
- download: "开始时间：..."、"✓ 处理 N 份评分" 之类
- 失败时：print("错误：未找到 iframe...")、print("已找到 N 份")

**没有统一 JSON 输出**。新 CLI 必须从 print 行中解析（不可靠）或从文件副作用计算（推荐）。

## 5. 退出码（所有路径）

| 情况 | rc | 来源 |
|------|----|------|
| 成功 | 0 | Python 隐式 |
| 缺 run_id | 2 | argparse |
| 未 confirmed | 20 | list/download 内部 SystemExit |
| run 不存在 | 1 | FileNotFoundError 未捕获 |
| run 与岗位不匹配 | 1 | RuntimeError 未捕获 |
| 缺 encrypt_job_id | 1 | raise ValueError 未捕获 |
| 找不到 iframe | 1 | print + return（list） |

## 6. 去重逻辑

- list 内部：见 seen_ids 集合（`state/batch_state.json`），跨 batch 累计
- list 普通模式：不维护 seen_ids（直接覆盖 `recommend_geek_ids.json`）
- download：**由 `JobResumeStore.get_status(job_id, geek_id)` 控制**——跳过 status=success / limit_hit 的候选人（`state/download_state.json`）

## 7. 重复运行行为

- list 普通模式跑 2 次：第二次完全覆盖 `recommend_geek_ids.json`
- download 跑 2 次：跳过已 success/limit_hit 的；只下载 new / failed 的

## 8. CDP / 浏览器前置

- list / download 都要 `connect_over_cdp('http://localhost:9222')`
- list 还要 iframe 等待 + human_scroll（节流 3-6 秒/次）
- download 还要 wait + fetch JS + 节流 pause_every/min/max

**没有 BOSS 登录或浏览器就立即报错**（找不到 iframe / 找不到 page）。

## 9. 真实 smoke（仅人工）

工具：Edge 9222 已启动 + 登录 + 当前在 recommend 页 → 跑：

```bash
python -m boss_hr.cli fetch \
    --job-name "<test_job>" --encrypt-job-id "<eid>" --run-id "<rid>" --count 2
```

预期：exit 0、生成 3 个文件（recommend_geek_ids.json / new_resumes.json / failed_resumes.json）。

本次**未执行真实 smoke**（未在登录环境 + 用户未授权）。本轮只靠静态分析 + 单元测试。

## 10. 自动化测试边界

- 单元测试 mock `boss_hr.adapters.legacy_runner.run_legacy_cli` 返回 fake LegacyRunResult
- **不**尝试跑真实 list/download 子进程（需 CDP + 浏览器 + BOSS 登录）
- 真实文件副作用通过 mock 的 returncode + 准备 fake 文件验证
