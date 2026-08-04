# boss_jd 缓存复用调查（2026-08-04）

> 起点：真实 smoke `boss-hr start` 阶段发现 `9a7759badfd95d350nFz3d-_F1NX`
> 跨 run 的 formValues 哈希一字不差（`347abfb83cc20adc`，4 项，bodyText 551 字节）。
>
> 结论：**不是代码缓存**，是 BOSS 后端编辑器的行为。下面是完整证据链。

---

## 1. 审计：代码中是否有跨 run formValues 缓存？

| 模块 / 函数 | 行为 | 是否读历史 run |
|---|---|---|
| `boss_jd.fetch_jd(encrypt_job_id)` | `sync_playwright().connect_over_cdp(9222)` → `page.goto(f"...?encryptId={eid}")` → `frame.evaluate("document.body.innerText")` + `frame.evaluate(...querySelectorAll('input,textarea,[contenteditable]')...)` | ❌ **不读任何本地文件**，纯 CDP iframe 抓取 |
| `boss_jd` `__main__` | 把上面返回值 `json.dump` 写到 `<run_dir>/process/job_detail.json`（**新建**，`out_path.write_text`） | ❌ 不读历史 |
| `JobOutputManager.jd_path` | `os.path.join(process_dir, 'job_detail.json')` | 静态拼路径，不读 |
| `RunOrchestrator.bind_existing_run` | 读 `process/job_detail.json` 的 `encryptJobId` 字段做岗位匹配校验 | ⚠️ **只读 encryptJobId**，**不读 formValues** |
| `RunOrchestrator.mark_done / confirm_run / init_run_state` | 读 / 写 `run.json`，不接触 job_detail | ❌ |
| `recruiter_job_catalog.resolve_recruiter_job` | 调 BOSS 后端 `recruiter-jobs-list` 拿岗位列表 | ❌ 不读本地 |
| `JobRegistry.register` | 写 `jobs.json`（岗位名/公司/时间戳），不存 formValues | ❌ |

**审计结论**：

- 没有模块级（`globals()`）缓存；
- 没有文件级（`state/job_cache.json` 等）缓存；
- 没有浏览器级（localStorage / sessionStorage）缓存路径（grep 无）；
- 没有跨 run formValues 复用代码路径。

---

## 2. 实测：iframe 拿到的 formValues 是否真的来自当前 eid？

### 2.1 独立探针（不走 boss_jd，直接 patchright + CDP）

```python
page.goto(f'https://www.zhipin.com/web/chat/job/edit?encryptId={EID}&jobCreateSource=0&enterSource=6')
iframe = page.wait_for_selector('iframe')
frame = iframe.content_frame()
form_vals = frame.evaluate("...")  # 与 boss_jd 同款 selector
```

**第一次访问 `9a7759badfd95d350nFz3d-_F1NX`（清空 localStorage + sessionStorage 后）：**

```
iframe URL: https://www.zhipin.com/web/frame/job/publish-edit?jobversion=10882
                                     &encryptId=9a7759badfd95d350nFz3d-_F1NX
                                     &jobCreateSource=0&enterSource=6
iframe formValues count: 4
iframe formValues hash : 347abfb83cc20adc   ← 与历史 run 完全一致
localStorage keys (前 15 项):
  ka-uid, frame_timestamp_flag, wd_guid, no-debug-uuid,
  apmsdk_uv_timestamp, wljssdk_cross_new_user, i18nextLng,
  local_build_version_chat, warlockjssdkcross, __Local__Setting,
  ft-/web/frame/job/edit, apmsdk_data_cache, openId,
  apmsdk_browser_id, apmsdk_uv
sessionStorage keys:
  apmsdk_session_id, page-router-history, historyUrl, linkID
```

→ **iframe URL 真的就是当前 eid**；
→ **localStorage 没有 BOSS 表单草稿**（只有分析 SDK / 版本号 / 路由历史），说明不是浏览器存储缓存；
→ **清空 localStorage 后 hash 不变**。

### 2.2 换 eid 看是否真的换了内容

| encryptJobId | jobName | formValues hash | formValues count |
|---|---|---|---|
| `9a7759badfd95d350nFz3d-_F1NX` | 线控底盘制动、转向工程师 | `347abfb83cc20adc` | 4 |
| `f6955637fbe03b0b0nF90t64FFdQ` | 车架工程师 | `98d598faaed6b6e5` | (不同内容) |

→ **不同 eid 拿到不同 formValues**。若代码有跨 eid 复用，两边 hash 会相同。

### 2.3 连续两次访问同 eid

同探针对 `9a7759badfd95d350nFz3d-_F1NX` 连续访问两次（中间 `page.goto(target)` 强制重载）：

```
first visit hash : 347abfb83cc20adc
second visit hash: 347abfb83cc20adc
hashes match     : True
```

→ 同 eid 跨访问拿到的 formValues 相同。**这不是缓存**，是 BOSS 后端编辑器对该 eid 的当前状态（用户没在 BOSS 后台改过 JD）。

---

## 3. 为什么 hash 一致 ≠ 缓存

BOSS 编辑器 `https://www.zhipin.com/web/frame/job/publish-edit?encryptId=...` 返回的页面是该 eid 当前岗位的编辑态表单。**对于没在 BOSS 后台修改过的岗位，每次拿到的就是同一份数据**。这是**后端接口的幂等性**，不是缓存。

如果用户在 BOSS 后台改了 JD（职位描述、关键词、地址等），下次跑 `boss_jd` 拿到的 formValues 会立刻不同。本仓库已经做了所有应该做的隔离：

- 每次 `create_new_run()` 创建新 run_id（新目录）
- 落盘到 `<new_run_dir>/process/job_detail.json`（不写老目录）
- encryptJobId 来源：`args.encrypt_job_id` → `BOSS_HR_ENCRYPT_JOB_ID` env → `resolve_recruiter_job(query).encryptJobId` → 报错（**不静默用缓存**）

---

## 4. 修复原则（用户 §四）核对

| 原则 | 是否满足 |
|---|---|
| 优先使用本次实时接口响应 | ✅ `frame.evaluate` 直接读当前 iframe |
| 不允许从历史 run 复用 formValues | ✅ 代码路径**不存在**这种读操作 |
| 如果需要缓存，缓存 key 必须包含 encryptJobId | N/A（无缓存） |
| 缓存读取时必须校验岗位 ID | N/A |
| 不修改统一 CLI 的 start 契约 | ✅ 本轮不动 CLI |
| 不新增 continue/batch | ✅ |
| 不删除故障样本 run | ✅ `2026-08-04_090734` 已保留 |
| 不顺手修改 JD 文本格式 | ✅ |

---

## 5. 建议（**不**在本轮实现）

按用户 §五验证要求，**最小复现测试**可以加，但目标应当是：

- **跨 eid 隔离**：跑两个不同 eid，断言 formValues 哈希不同、encryptJobId 字段与 query 一致；
- **同 eid 跨 run** 数据来源可追踪：每次 `fetch_jd` 调用必须经过 patchright，断言子进程被调一次、写入对应 run 目录、不读历史 run 文件。

这些测试**应当在 inproc 单元层用 mock fetch 实现**，避免依赖真 BOSS 后端（详见 §6）。

---

## 6. ⚠️ 真正值得记录的小改进（不动 boss_jd 主体）

`boss_jd.fetch_jd` 当前没有"**校验拿到的 formValues 与 encryptJobId 对应**"的步骤。如果未来 BOSS 编辑器因任何原因（iframe 加载超时、CDP tab 残留）返回了**别的 eid** 的表单内容，boss_jd 会**静默写错**。

**不动 boss_jd**（用户禁止修改 JD 文本格式）；但可以在 `boss_jd` 落盘前加一行**强校验**：iframe URL 必须含 `encryptId=<args.encrypt_job_id>`。这是对用户 §四"缓存内容必须带岗位 ID 并在读取时校验"原则的等价物（即使是无缓存场景，跨 eid 误取同样需要校验）。

要不要加这一行校验，**等用户拍板**。本轮**未改代码**。

---

## 7. 故障样本 run 现状（保留）

| run | 状态 | encryptJobId |
|---|---|---|
| `2026-08-04_090734` | ✅ 保留（smoke 目录） | `9a7759badfd95d350nFz3d-_F1NX` |
| `2026-08-04_114431` | ✅ 保留（smoke 目录，本次探针产生） | `9a7759badfd95d350nFz3d-_F1NX` |
| `2026-08-04_114520` | ✅ 保留（smoke 目录，本次探针产生） | `f6955637fbe03b0b0nF90t64FFdQ` |

按用户指令**未删除任何 run**。