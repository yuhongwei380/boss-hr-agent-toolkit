---
name: boss-recommend-downloader
description: |
  推荐牛人简历批量下载器。通过真实浏览器指纹安全获取推荐牛人页面的完整在线简历。

  **本 Skill 是 boss-hr-auto 编排流程的子步骤（Step 2B），由 boss-hr-auto 在提取 JD 后调用，不应作为入口 Skill 直接加载。**
  
  **触发场景**：
  - "下载推荐牛人简历"
  - "获取推荐候选人完整简历"
  - "批量下载推荐人才"
  
  **不触发场景**：
  - 仅查看推荐列表（不下载完整简历）
  - 从沟通/互动页面下载简历（用 boss-resume-downloader）
  
  **依赖**：本 skill 依赖 `boss-hr-auto` skill 完成环境准备和登录。请先确保已完成登录流程。
type: tool
---
# 推荐牛人简历批量下载

> **核心目标**：安全、批量地获取推荐牛人页面的完整在线简历数据。
>
> **安全级别**：🟢 极低风险（真实浏览器 TLS 指纹 + 随机延迟）

---

## 流程总览

```
[Step 1] 获取候选人列表 ──── patchright 滚动 + 拦截 geek/list API
     │
     ▼
[Step 2] 批量获取完整简历 ─ patchright + 浏览器 fetch（真实 Edge 指纹）
     │
     ▼
[输出] 完整简历 JSON 文件
```

**核心原理**：Step 2 通过 patchright 在真实 Edge 浏览器内执行 `fetch()` 调用 BOSS API，
请求使用 **浏览器的真实 TLS 指纹和 Cookie**，与真人操作完全一致，服务器无法区分。

---

## 🔧 前置条件

### 依赖 Skill

本 skill 依赖 `boss-hr-auto` skill 完成以下准备工作：
- ✅ Python 3.10+ 环境
- ✅ patchright 安装（`pip install patchright`）
- ✅ Edge 浏览器以 CDP 模式启动（端口 9222）
- ✅ BOSS 直聘扫码登录完成

**如果未完成上述准备，请先执行 `boss-hr-auto` skill。**

---

## Step 1: 获取候选人列表

**脚本**：`scripts/recommend_list.py`

**原理**：在推荐牛人页面滚动时，前端懒加载调用 `geek/list` API。用 patchright 拦截这些 API 响应，提取候选人 ID。

### 核心操作

```bash
# 普通模式：获取所有候选人
python scripts/recommend_list.py --job-name 车架工程师

# 分批模式：每批25人，不刷新页面（顺序固定）
python scripts/recommend_list.py --job-name 车架工程师 --batch-size 25 --batch 1
python scripts/recommend_list.py --job-name 车架工程师 --batch-size 25 --batch 2
# batch 2+ 会连接已有页面继续滚动，不重新加载
```

### 提取的关键信息

| 字段 | 位置 | 用途 |
|------|------|------|
| `encryptGeekId` | 顶层字段 | 获取简历的候选人 ID |
| `securityId` | `geekCard` 对象内 | 安全验证 ID |
| `encryptJobId` | `geekCard` 对象内 | 岗位 ID |
| `geekName` | `geekCard` 对象内 | 候选人姓名 |

### 输出文件

`process/recommend_geek_ids.json`（或分批模式：`process/batch_N_ids.json`）

---

## Step 2: 批量获取完整简历

**脚本**：`scripts/recommend_download_v2.py`

**原理**：用 patchright 在真实 Edge 浏览器内执行 JavaScript `fetch()` 调用 BOSS API
`/wapi/zpjob/view/geek/info`。请求通过浏览器发出，使用**真实的 Edge TLS 指纹 + 浏览器 Cookie**，
与招聘者真人浏览 BOSS 直聘时发出的请求完全一致。

### 为什么不用 CLI？

| 对比项 | CLI（v1，已弃用） | patchright + fetch（v2） |
|--------|:----------------:|:----------------------:|
| TLS 指纹 | ❌ Python requests（可被识别） | ✅ 真实 Edge 浏览器 |
| 编码问题 | ❌ Windows GBK 导致解析失败 | ✅ 无编码问题 |
| 封号风险 | ⚠️ 中等 | 🟢 极低 |
| 速度 | 5-20秒/人 | ~8秒/人 |

### 核心操作

```bash
# 普通模式：下载全部
python scripts/recommend_download_v2.py --job-name 车架工程师

# 分批模式：下载第1批
python scripts/recommend_download_v2.py --job-name 车架工程师 --batch 1

# 限制数量
python scripts/recommend_download_v2.py --job-name 车架工程师 --batch 1 --max 10
```

### 完整简历数据结构

```json
{
  "name": "张三",
  "age": "25岁",
  "degree": "本科",
  "work_years": "3年",
  "expectation": { "position": "测试工程师", "salary": "10-15K", "city": "宁波" },
  "work_experience": [
    {
      "company": "XX 公司",
      "position": "测试工程师",
      "start": "2023.09",
      "end": "2026.06",
      "duration": "2年9个月",
      "responsibility": "工作职责详细描述...",
      "keywords": ["CANoe", "JIRA", "UDS"]
    }
  ],
  "project_experience": [
    {
      "name": "XX 项目",
      "role": "测试工程师",
      "start": "2025.04",
      "end": "2026.06",
      "description": "项目描述...",
      "achievement": "业绩描述..."
    }
  ],
  "education": [
    {
      "school": "XX 大学",
      "major": "车辆工程",
      "degree": "本科"
    }
  ],
  "certifications": ["驾驶证 C1", "英语四级"]
}
```

### 输出文件

| 文件 | 内容 |
|------|------|
| `process/batch_N_resumes.json` | 当批成功获取的简历 |
| `process/test_resumes.json` | 累计所有已下载简历 |
| `process/batch_N_failed.json` | 失败的候选人及原因 |

---

## ⚠️ 安全策略

### 为什么 v2 更安全

v2 使用 patchright 在**真实 Edge 浏览器**中执行 `fetch()` 请求。从 BOSS 服务器视角看：
- TLS 指纹 = 真实 Edge 浏览器（不是 Python requests）
- Cookie = 用户真实登录 session
- 请求头 = 浏览器自动添加的标准头
- 无法与真人操作区分

### 随机延迟

| 操作 | 延迟范围 | 说明 |
|------|---------|------|
| 页面滚动 | 3-6 秒 | 模拟真人浏览速度 |
| 获取简历 | 5-15 秒 | 模拟真人看简历（有的快扫，有的细看） |

### 运行建议

- ✅ **推荐**：工作时间（9:00-18:00）
- ⚠️ **避免**：凌晨或深夜
- 单次建议不超过 50 人，超过则分批次
- 遇到"今日查看已达上限"立即停止

---

## 📝 完整分批工作流示例

```bash
# Batch 1：收集25人 → 下载 → 评分
python scripts/recommend_list.py --job-name 车架工程师 --batch-size 25 --batch 1
python scripts/recommend_download_v2.py --job-name 车架工程师 --batch 1
# → AI 读取 batch_1_resumes.json 进行评分

# Batch 2：继续滚动（不刷新页面）→ 下载 → 评分
python scripts/recommend_list.py --job-name 车架工程师 --batch-size 25 --batch 2
python scripts/recommend_download_v2.py --job-name 车架工程师 --batch 2
# → AI 读取 batch_2_resumes.json 进行评分

# Batch 3：同上...
```

---

## 🔧 故障排查

### `今日查看已达上限`

**原因**：BOSS 直聘每日查看简历数量限制（与下载方式无关，CLI 和 fetch 都会触发）。

**解决**：等待第二天额度刷新后继续。

### `fetch` 返回空数据或报错

**原因**：登录 session 过期。

**解决**：重新执行 `boss login --cdp --timeout 30` 同步浏览器 Cookie 到 CLI。

### 滚动时没有加载更多候选人

**原因**：可能在主页面滚动而非 iframe 内。

**解决**：脚本已自动在 iframe 内滚动。如仍有问题，确认推荐牛人页面已正确加载。

---

## 📊 预期结果

| 指标 | 数值 |
|------|------|
| 候选人列表获取 | 100-500 人（取决于岗位推荐量） |
| 简历获取成功率 | 10-30%（部分候选人隐藏简历或需付费查看） |
| 单人耗时 | ~8 秒 |
| 25 人批次耗时 | 约 3-5 分钟 |
| 封号风险 | 🟢 极低（真实浏览器指纹） |

---

<!-- 
  ============================================================
  以下为 v1 CLI 方案（已弃用），仅供开发者参考。
  智能体不应使用此方案，请使用上方的 v2 patchright + fetch 方案。
  ============================================================

  v1 脚本：scripts/recommend_download.py
  原理：通过 boss-agent-cli 的 `boss hr resume` 命令获取简历
  问题：Python requests 的 TLS 指纹可被 BOSS 识别，Windows 下存在 GBK 编码问题
  
  命令示例：
    boss.exe --role recruiter --platform zhipin --cdp-url http://localhost:9222 \
      hr resume <encryptGeekId> --security-id <securityId> --job-id <jobId>

  已知问题：
  1. TLS 指纹与真实浏览器不同，高频使用有封号风险
  2. Windows 默认 GBK 编码导致简历中 • 等特殊字符解析失败
  3. json.loads() 可能因混合编码失败

  仅在 v2 方案不可用时（如 patchright 未安装）作为降级方案。
-->
