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
# BOSS 直聘 HR 简历筛选全流程

> ** 入口声明**：本 Skill 是 boss-hr-agent-toolkit 项目唯一入口。下文的子 Skill 均应按本 Skill 的编排顺序调用，不得作为独立入口加载。

## 流程总览

本工具包提供**两条简历获取路径**，根据场景选择：

### 路径 A：沟通列表简历下载（适合已有沟通记录）

```
用户提供岗位ID/链接
     │
     ▼
[Step 1] 提取 JD ──── 使用 skill: boss-job-detail
     │
     ▼
[Step 2A] 下载简历 ─ 使用 skill: boss-resume-downloader
     │              （从沟通列表获取候选人简历）
     ▼
[Step 3] 评分 ────── 使用 skill: resume-screener
     │
     ▼
[Step 4] 生成报告 ─ 使用 skill: html-report
```

### 路径 B：推荐牛人简历下载（适合从推荐列表获取）

```
用户提供岗位ID/链接
     │
     ▼
[Step 1] 提取 JD ──── 使用 skill: boss-job-detail
     │
     ▼
[Step 2B] 推荐牛人下载 ─ 使用 skill: boss-recommend-downloader
     │                  （从推荐牛人页面获取完整简历）
     ▼
[Step 3] 评分 ────── 使用 skill: resume-screener
     │
     ▼
[Step 4] 生成报告 ── 使用 skill: html-report
```

**❌ 不做：自动回复/打招呼**（CLI reply 权限不足，由用户在 BOSS 网页端操作）

---

## 用到的 Skill 列表

| # | Skill | 在流程中的作用 |
|:-:|:------|:-------------|
| 1 | **boss-job-detail** | Step 1：CDP+iframe 提取完整岗位 JD |
| 2A | **boss-resume-downloader** | Step 2A：从沟通列表批量下载候选人简历 |
| 2B | **boss-recommend-downloader** | Step 2B：从推荐牛人页面获取完整简历（新增） |
| 3 | **resume-screener** | Step 3：岗位类型判断→硬门槛过滤→加权评分→排名输出 |
| 4 | **html-report** | Step 4：生成 HTML 可视化报告 |
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
PYTHONHOME="" python scripts/boss_jd.py <encryptJobId 或 jobId 或 岗位名>
```

**输出：** 结构化 JD 数据（岗位名、学历、专业、经验、职责、技能栈），保存到 `process/job_detail.json`。

---

## Step 2A: 从沟通列表下载简历

**执行 skill：** `boss-resume-downloader`

**适用场景：** 已有候选人在沟通列表中

**核心操作：**
```bash
# 查看岗位列表获取 jobId
boss --role recruiter --platform zhipin --cdp-url http://localhost:9222 hr jobs list

# 分批下载（--max 是累计处理数，含已跳过）
python scripts/sync_boss_resumes.py sync-job --job-id <jobId> --max 10
```

**分批策略：**
- 第一轮 `--max 10` → 第二轮 `--max 20` → 第三轮 `--max 30`
- 脚本自带随机延迟防封

**输出：** 候选人简历数据，保存到 `process/test_resumes.json`。

---

## Step 2B: 从推荐牛人页面下载简历

**执行 skill：** `boss-recommend-downloader`

**适用场景：** 需要从推荐牛人页面获取候选人

**核心操作：**
```bash
# 分批运行（推荐，不刷新页面，顺序固定）
python scripts/recommend_list.py --job-name "车架工程师" --batch-size 25 --batch 1
python scripts/recommend_download_v2.py --job-name "车架工程师" --batch 1
# 评分后继续下一批
python scripts/recommend_list.py --job-name "车架工程师" --batch-size 25 --batch 2
python scripts/recommend_download_v2.py --job-name "车架工程师" --batch 2

# 或一次性运行
python scripts/recommend_list.py --job-name "车架工程师"
python scripts/recommend_download_v2.py --job-name "车架工程师"
```

> **注意**：`recommend_download_v2.py` 使用 patchright + 浏览器 fetch 方案（真实 Edge TLS 指纹），
> 替代了旧版 `recommend_download.py` 的 CLI 方案。详见 `boss-recommend-downloader` skill。

**安全策略：**
- TLS 指纹：真实 Edge 浏览器（服务器无法区分）
- 滚动延迟：3-6 秒随机（模拟真人浏览）
- 简历获取：5-15 秒随机（模拟真人阅读）
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

**输出位置：** `~/Desktop/boss-hr-output/<岗位名>/<岗位名>_简历筛选报告.html`

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

### 输出文件结构（所有 skill 必须遵守）

```
~/Desktop/boss-hr-output/                    # 所有输出放这里
└── <岗位名>/                                  # 按岗位名建子文件夹
    ├── <岗位名>_简历筛选报告.html              # 最终 HTML 报告
    └── process/                               # 过程文件（留痕查阅）
        ├── job_detail.json                    # JD 数据
        ├── recommend_geek_ids.json            # 候选人 ID 列表
        ├── test_resumes.json                  # 完整简历数据
        ├── screening_results.json             # 评分结果
        └── failed_resumes.json                # 失败列表
```

### 🚨 重要规则（所有智能体必须恪守）

1. **禁止在桌面散落文件** — 所有输出必须放到 `boss-hr-output/<岗位名>/` 下
2. **HTML 报告放岗位文件夹根目录** — 方便用户直接查看
3. **中间数据放 `process/` 子文件夹** — 留痕查阅，不影响最终交付
4. **临时 Python 脚本任务结束后删除** — `generate_report.py` 等工具文件不要留在桌面
5. **复用 skill 内已有的 Python 脚本** — 禁止重复造轮子
6. **岗位文件夹不存在时自动创建** — 不要询问用户，直接创建

### 文件路径获取方式

```python
import sys
import os

# 添加 shared 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from output_manager import JobOutputManager

# 初始化输出管理器
output = JobOutputManager('车架工程师')

# 获取文件路径
print(output.report_path)           # HTML 报告路径
print(output.jd_path)               # JD 数据路径
print(output.resumes_path)          # 简历数据路径
print(output.recommend_geek_ids_path)  # 候选人 ID 路径

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
- 推荐牛人下载：滚动 3-6 秒随机，简历获取 5-20 秒随机
