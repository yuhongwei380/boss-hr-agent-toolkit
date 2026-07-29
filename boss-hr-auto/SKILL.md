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
> （用浏览器真实的 wt2/zp_at/bst cookie），不依赖 boss CLI 内部的 `__zp_stoken__`。
> 如果 `boss_login_guard.py check --purpose resume` 返回 warning 提到 stoken 缺失，
> **直接忽略继续运行**即可。需要用裸 `boss` CLI（不走本工具包）时，再手动跑
> `python boss_login_guard.py ensure-stoken`。

# BOSS 直聘 HR 简历筛选全流程

> ** 入口声明**：本 Skill 是 boss-hr-agent-toolkit 项目唯一入口。下文的子 Skill 均应按本 Skill 的编排顺序调用，不得作为独立入口加载。
>
> **本 Skill 是纯文档，没有一把梭脚本。** 智能体按下文 Step 顺序逐个调用子 Skill 的 `scripts/`。

## 🚨 铁律：先开 run_id，每步都显式传

**这是最容易犯错的地方。** 所有脚本不传 `--run-id` 时会去读 `state/current_run.json`，
那里存的可能是**上一次任务的旧 run_id** —— 产物就会写进旧目录，污染历史记录。

```bash
# ① 开工第一件事：拿到本次 run_id + encryptJobId
ENCRYPT_ID="<Step 1 boss_jd.py 返回的 encryptJobId>"
JOB_NAME="<中文岗位名>"

RUN_ID=$(python -X utf8 -c "
import sys; sys.path.insert(0,'shared')
from run_orchestrator import RunOrchestrator
print(RunOrchestrator(job_name='$JOB_NAME', encrypt_job_id='$ENCRYPT_ID').bind_or_create())
")

# ② 之后每一个脚本都带上它（run_id + encrypt_job_id 必须同时传）
export BOSS_HR_ENCRYPT_JOB_ID="$ENCRYPT_ID"   # 6 个 CLI 脚本统一读 env
python -X utf8 <任意子脚本>.py ... --run-id "$RUN_ID" --encrypt-job-id "$ENCRYPT_ID"
```

### 新接口铁律：5 步脚本全部要传 `--encrypt-job-id`

**6 个 CLI 脚本**（`boss_jd.py` / `recommend_list.py` / `recommend_download.py` / `score_resumes.py` / `generate_html_report.py` / `auto_greet.py`）**都必须传 `--encrypt-job-id`**（或 env `BOSS_HR_ENCRYPT_JOB_ID`），缺则直接 `ValueError` 退出，**不会静默回退到中文目录名**。

**设计原因**：新工作区目录名 = `encryptJobId`（不再是中文岗位名）。CLI 脚本只接收并透传，**路径选择集中在 `shared/output_manager.JobOutputManager`**——避免你以为跑了新路径、实际又落到中文路径的事故。

**共享同一个 encryptJobId**：5 步必须传同一个 `--encrypt-job-id`，否则产物会落到不同工作区目录，list/download 找不到 score 文件，反之亦然。

### run 卡住怎么办？

如果 `state/current_run.json` 指向的 `runs/<run_id>/` 是空壳目录（只有 `process/` 子目录或 `.html` 报告才算「真实产物」），下一次 `bind_or_create()` 会新建 run。

但如果目录里**有真实产物但你确实想开新 run**（例如上一步半途失败要重来），传 `--run-id` 显式指定一个新 ID：

```bash
# 显式开新 run（无视 current_run.json，产物落在指定目录）
python -X utf8 boss-recommend-downloader/scripts/recommend_list.py \
  --job-name "车架工程师" --max 25 --run-id "2026-07-29_120000"
```

或通过 `bind_or_create(run_id="...", force=False)` 同理。**`force` 参数仅供脚本内部用**——它跳过沿用检查，直接强制新建（用于一连串子脚本的 batch 模式）。

### 跑完后清理

A 流程跑完后 `greet` **默认会自动 `finish()`**（只要招呼成功 ≥1 人且非 dry-run），下次跑会自动开新 run。

| 场景 | 行为 |
|------|------|
| 默认招呼成功 | 自动 finish()，下次跑 bind_or_create() 开新 run |
| 显式 `--no-finish` | 不 finish()，保留「回头补招呼同一 run」能力 |
| `--dry-run` 或招呼成功 0 人 | 不 finish()，提示手动调 |

如果需要手动 finish：

```bash
python -X utf8 -c "
import sys; sys.path.insert(0,'shared')
from run_orchestrator import RunOrchestrator
RunOrchestrator('<岗位名>').finish()   # 标记 finished=true，下次起新 run
"
```

| ❌ 禁止 | ✅ 正确 |
|--------|--------|
| 直接调 `recommend_list.py` 不传 run-id | 先 `bind_or_create()` 再逐步传 `--run-id` |
| 每个 Step 各开各的 run_id | 5 个 Step 共用同一个 |
| 不传 `--encrypt-job-id` 跑 CLI（会 `ValueError`） | 5 步脚本统一传同一个 encryptJobId，或设 `BOSS_HR_ENCRYPT_JOB_ID` |
| 自己造 `_split_N.json` / `_llm_N.json` 等中间文件 | 直接写规范内的 `_llm_scores.json` |

> 评分环节即使有几十份简历，也**直接写一个 `_llm_scores.json`**。
> 需要分批处理时在内存里分，不要在 `process/` 里落临时分片文件。

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
| - | **boss-agent-cli** | 基础：CLI 命令参考、双模式登录 |

---

## 环境准备

### 必需安装

1. **Python 3.10+** — 从 python.org 安装，勾选 "Add Python to PATH"
2. **uv** — `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
3. **boss-agent-cli** — `uv tool install boss-agent-cli`
4. **patchright** — `pip install patchright`（抗检测浏览器自动化）

### 环境变量（每次运行前必做）

```bash
export PYTHONHOME=""
export PATH="$PATH:$HOME/.local/bin"
export PYTHONIOENCODING=utf-8
```

### CLI 登录验证

```bash
# 验证是否真登录
boss.exe --role recruiter me
boss.exe --role recruiter --platform zhipin --cdp-url http://localhost:9222 hr jobs list
```

**判定标准：**
| `hr jobs list` 结果 | `boss me` 结果 | 含义 | 操作 |
|:-------------------|:--------------|:----|:----|
| `data: [{...}]`（有数据） | `name: "真实姓名"` | ✅ 真登录 | 继续执行 |
| `data: {}` 或 `data: []`（空） | `name: ""`（空） | ❌ 假阳性 | `boss login --cdp --timeout 30` |

**假阳性修复命令（唯一正确方式）：**
```bash
boss login --cdp --timeout 30
```

### 启动 CDP 浏览器

```bash
# Windows Edge
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" ^
  --remote-debugging-port=9222 ^
  --user-data-dir="%USERPROFILE%\.workbuddy\chrome-profiles\boss-cdp"
```

### 关闭 CLI 低风险模式（简历下载必需）

```bash
# 创建/编辑配置文件
cat > ~/.boss-agent/config.json << 'EOF'
{
  "low_risk_mode": false,
  "platform": "zhipin",
  "role": "recruiter"
}
EOF
```

> ⚠️ **必须关闭**：`low_risk_mode` 默认开启会阻止简历获取。

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
# 公共参数（与 Step 1 同一个 encryptJobId）
export ENCRYPT_ID="<Step 1 拿到的 encryptJobId>"
export JOB_NAME="<岗位中文名>"

# 分批运行（推荐，不刷新页面，顺序固定）
python -X utf8 boss-recommend-downloader/scripts/recommend_list.py \
  --job-name "$JOB_NAME" --encrypt-job-id "$ENCRYPT_ID" \
  --batch-size 25 --batch 1
python -X utf8 boss-recommend-downloader/scripts/recommend_download.py \
  --job-name "$JOB_NAME" --encrypt-job-id "$ENCRYPT_ID" \
  --batch 1
# 评分后继续下一批
python -X utf8 boss-recommend-downloader/scripts/recommend_list.py \
  --job-name "$JOB_NAME" --encrypt-job-id "$ENCRYPT_ID" \
  --batch-size 25 --batch 2
python -X utf8 boss-recommend-downloader/scripts/recommend_download.py \
  --job-name "$JOB_NAME" --encrypt-job-id "$ENCRYPT_ID" \
  --batch 2

# 或一次性运行
python -X utf8 boss-recommend-downloader/scripts/recommend_list.py \
  --job-name "$JOB_NAME" --encrypt-job-id "$ENCRYPT_ID"
python -X utf8 boss-recommend-downloader/scripts/recommend_download.py \
  --job-name "$JOB_NAME" --encrypt-job-id "$ENCRYPT_ID"
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

A 流程默认招呼成功 ≥1 时**自动 `finish()`**，下次跑 `bind_or_create()` 自动开新 run。

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
    │   ├── geek_positions.json
    │   └── current_run.json
    └── runs/                                       # 每次筛选任务一个 run_id 子目录
        └── <run_id>/
            ├── <run_id>_screening_report.html     # 最终 HTML 报告
            └── process/                            # 过程文件（留痕查阅）
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

### CLI 假阳性检测（重要）
`boss status` 返回 `logged_in: true` 但实际 token 可能已过期。**确认方法：**
```bash
# ✅ 真阳性 — 能返回在线岗位数据
boss --role recruiter --platform zhipin --cdp-url http://localhost:9222 hr jobs list

# ❌ 假阳性 — 返回 data: {}（空对象），token 已过期
```
关键判断：如果 `hr jobs list` 返回 `"data": {}`（空 JSON 对象）而非岗位数组，说明 CLI session 已过期。**不要继续依赖 CLI**，立即切换到 CDP 浏览器直接操作。

### 编码
- BOSS CLI stdout 为 GBK 编码
- 禁止用 PowerShell 管道处理中文 → 乱码
- 看到乱码直接如实报告，不要猜测中文内容

### 模式切换
- 求职者模式：`boss ...`（默认）
- 招聘者（HR）模式：`boss --role recruiter hr ...`
- 不同模式命令不同，模式不对会超时或返回空

### 防封
- 简历下载每次只下一份，脚本自带随机延迟
- 不要连续快速操作同一接口
- 推荐牛人下载：滚动 3-6 秒随机，简历获取 60-120 秒随机
