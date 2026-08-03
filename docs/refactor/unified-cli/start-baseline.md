# Start 基线（2026-08-03）

工具：`tools/baseline_start.py` → `artifacts/refactor/start-baseline.json`（静态分析）

## 1. 真实 CLI 参数（从源文件读出）

| 参数 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `query`（位置参数） | 否* | None | encryptJobId / jobId / 岗位名（三选一） |
| `--job-name` | 否 | None | 岗位中文名（写入 jobs.json metadata） |
| `--encrypt-job-id` | 否 | None | BOSS encryptJobId（env `BOSS_HR_ENCRYPT_JOB_ID` 兜底） |
| `--run-id` | 否 | None | 不传 → `create_new_run()` 自动生成；传 → `bind_existing_run()` 校验 |
| `--force` | 否 | False | 同 run 内补写（flag） |

* `query` 在 argparse 实际**没有 required=True**（看 dest=query required=False），但 main() 内 `resolve_encrypt_id(query)` 返回 `(None, None)` → `print(f"Job not found")` → `sys.exit(1)`。

## 2. query 解析优先级

```
1) CLI --encrypt-job-id
2) env BOSS_HR_ENCRYPT_JOB_ID
3) query 本身就是 encryptJobId（看 resolve_recruiter_job 返回的 encryptJobId）
```

`resolve_encrypt_id(query)` 调 `recruiter_job_catalog.resolve_recruiter_job(query)`，支持：
- encryptJobId 精确
- jobId 数字精确
- jobName 精确 / 模糊

## 3. run 创建位置

```python
orch = RunOrchestrator(job_name, encrypt_job_id=encrypt_job_id)
if args.run_id:
    run_id = orch.bind_existing_run(args.run_id)
else:
    run_id = orch.create_new_run()  # YYYYMMDD_HHMMSS（不依赖外部状态）
```

→ **每次不传 --run-id 都生成新 run_id**（同秒冲突自动加 `_N` 后缀）。

## 4. job_detail.json schema

位置：`runs/<run_id>/process/job_detail.json`

```json
{
  "jobName": "<来自 recruiter_job_catalog>",
  "encryptJobId": "<来自 recruiter_job_catalog>",
  "bodyText": "<页面 body innerText>",
  "formValues": ["岗位职责：...", "..."],
  "_meta": {
    "run_id": "2026-08-03_120000",
    "saved_at": "2026-08-03 12:00:00"
  }
}
```

## 5. run.json 副作用

- `output.ensure_run_dir()`：建 runs/<run_id>/ + process/
- `orch.init_run_state(run_id)`：写 `run.json`（confirmed=false, steps_done=[], finished=false）
- `orch.mark_done('jd', run_id)`：steps_done 追加 'jd'，last_step='jd'
- **不调 finish()**（保留 waiting_user_confirmation 状态）

## 6. jobs.json 副作用

- `JobOutputManager(job_name, encrypt_job_id=encrypt_job_id, run_id=run_id)` 构造时：
  - `JobRegistry().register(encrypt_job_id, name=job_name)`
  - 写 `state/...jobs.json` 不在此处写；register() 内部写 `<OUTPUT_ROOT>/jobs.json`

## 7. stdout 格式（多段混合）

```
Found: <jobName> (<eid>)
run_id: <id>（orchestrator 创建）
{
  "status": "waiting_user_confirmation",
  "run_id": "<id>",
  "stage": "awaiting_user_confirmation",
  "message": "Step 1（提取 JD）已完成。..."
}
Saved to <path>
run_id: <id>
OK
```

**run_id 出现 3 处**：
1. 第 144 行 `print(f"run_id: {run_id}（orchestrator 创建）")`
2. 第 176 行 JSON 块 `{"status": "waiting_user_confirmation", "run_id": "<id>", ...}`
3. 第 191 行 `print(f"run_id: {output.run_id}")`

**adapter 解析策略**：
- 优先从 stdout 中取**最后 1 个合法 JSON**（通常在第 3 段）
- JSON 的 `run_id` 字段
- 兜底：regex `run_id:\s*(\S+)` 抓第一个匹配

**三个位置的 run_id 应一致**（adapter 校验）。

## 8. 退出码

| 情况 | rc | 来源 |
|------|----|------|
| 成功 | 0 | Python 隐式 |
| query 找不到 | 1 | `print(f"Job not found")` → `sys.exit(1)` |
| 缺 encrypt_job_id（resolve_encrypt_job_id 抛 ValueError） | 1 | raise ValueError（未捕获，Python 抛非 0） |
| iframe wait 超时 | 0 | print warning + 继续（不抛错） |
| 登录态失效（CDP 拉空） | 0 | fetch_jd 返回空 body，job_detail.json 仍写入 |

**关键**：旧 boss_jd **不在 main() 显式 check_login()**。登录态失效表现是 JD 内容空 / bodyText 为空字符串。

## 9. 失败文件副作用

- **有 atexit 自动清理**：
  ```python
  def _auto_prune():
      if not _SAVED and output.prune_if_empty():
          print(f'⚠️  本次 run 未产生 job_detail.json，已清理: {output.run_dir}')
  atexit.register(_auto_prune)
  ```
- 脚本异常退出（未写 job_detail.json）→ 自动删整个 run_dir
- 正常成功（`_SAVED = True`）→ 保留 run_dir

**新 CLI 必须保持这个行为**——失败时不要新增回滚或清理机制（用户规则）。

## 10. 连续两次运行

- 第一次 start A → 拿到 run_id_1
- 第二次 start A（不传 --run-id）→ `create_new_run()` 内部生成新 run_id_2
- 满足 `run_id_1 != run_id_2`（同秒概率小；如果同秒会自动加 `_2` 后缀）

## 11. import 副作用

- 顶部 `from patchright.sync_api import sync_playwright`（不执行；import 时仅加载）
- `import fix_encoding`（不执行；仅加载）
- main() 内 `import atexit`（不执行）
- main() 内 `from run_orchestrator import RunOrchestrator`（不执行）

**没有 import 副作用**（与 score 脚本不同）。

## 12. 真实 smoke

**未执行真实 smoke**。当前没有安全的 BOSS 登录环境。最终统一 CLI 交付前必须执行：
1. Edge 9222 启动 + 登录
2. `boss-hr start <query> --job-name ... --encrypt-job-id ...`
3. 验证新 run + job_detail.json
4. 调 `boss-hr confirm`
5. 调 `boss-hr fetch --count 1`

测试用岗位 + 1 份候选人。
