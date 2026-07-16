---
name: boss-recommend-downloader
description: |
  推荐牛人简历批量下载器。安全获取推荐牛人页面的完整在线简历。
  
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
> **安全级别**：🟢 低风险（随机延迟 + 模拟真人行为）

---

## 流程总览

```
[Step 1] 获取候选人列表 ──── 浏览器滚动 + 拦截 API
     │
     ▼
[Step 2] 批量获取完整简历 ─ CLI + 随机延迟
     │
     ▼
[输出] 完整简历 JSON 文件
```

---

## 🔧 前置条件

### 依赖 Skill

本 skill 依赖 `boss-hr-auto` skill 完成以下准备工作：
- ✅ Python 3.10+ 环境
- ✅ uv 包管理器
- ✅ boss-agent-cli 安装
- ✅ patchright 安装（抗检测浏览器自动化）
- ✅ Edge 浏览器以 CDP 模式启动（端口 9222）
- ✅ BOSS 直聘扫码登录完成

**如果未完成上述准备，请先执行 `boss-hr-auto` skill。**

### 必需配置

#### 1. 关闭 CLI 低风险模式

```bash
# 创建/编辑配置文件
cat > ~/.boss-agent/config.json << 'EOF'
{
  "low_risk_mode": false,
  "platform": "zhipin",
  "role": "recruiter",
  "request_delay": [1.5, 3.0],
  "log_level": "error"
}
EOF
```

> ⚠️ **必须关闭**：`low_risk_mode` 默认开启会阻止简历获取。

#### 2. 环境变量

```bash
# 避免 CLI 的 GBK 编码问题（简历中包含 • 等特殊字符）
export PYTHONIOENCODING=utf-8
export PYTHONHOME=""
export PATH="$PATH:$HOME/.local/bin"
```

---

## Step 1: 获取候选人列表

**原理**：在推荐牛人页面滚动时，前端会懒加载调用 `geek/list` API。我们拦截这些 API 响应，提取候选人关键信息。

### 核心操作

```python
from patchright.sync_api import sync_playwright
import time, json

all_geeks = []
seen_ids = set()

def on_response(resp):
    """拦截 geek/list API 响应"""
    url = resp.url
    if 'geek/list' in url:
        try:
            data = resp.json()
            for g in data.get('zpData', {}).get('geekList', []):
                gid = g.get('encryptGeekId', '')
                if gid and gid not in seen_ids:
                    seen_ids.add(gid)
                    all_geeks.append(g)
        except:
            pass

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp('http://localhost:9222')
    ctx = browser.contexts[0]
    pg = ctx.pages[0] if ctx.pages else ctx.new_page()
    
    pg.on('response', on_response)
    
    # 打开推荐牛人页面
    pg.goto('https://www.zhipin.com/web/chat/recommend', 
            wait_until='networkidle', timeout=60000)
    time.sleep(5)
    
    # 找到 iframe
    iframe = pg.query_selector('iframe')
    frame = iframe.content_frame()
    
    # 持续滚动直到没有新数据
    import random
    no_new_count = 0
    
    while no_new_count < 5:
        prev = len(all_geeks)
        
        # 在 iframe 内滚动
        frame.evaluate('window.scrollBy(0, 1500)')
        
        # 随机延迟 3-6 秒（模拟真人滚动速度）
        delay = random.uniform(3, 6)
        time.sleep(delay)
        
        if len(all_geeks) == prev:
            no_new_count += 1
        else:
            no_new_count = 0
        
        print(f'{len(all_geeks)} candidates (stale: {no_new_count}/5)')
    
    print(f'\nTotal: {len(all_geeks)} candidates')
    
    # 保存候选人列表
    with open('recommend_geek_ids.json', 'w', encoding='utf-8') as f:
        json.dump(all_geeks, f, ensure_ascii=False, indent=2)
```

### 提取的关键信息

从 API 响应中提取每个候选人的：

| 字段 | 位置 | 用途 |
|------|------|------|
| `encryptGeekId` | 顶层字段 | CLI 获取简历的候选人 ID |
| `securityId` | `geekCard` 对象内 | CLI 获取简历的安全验证 ID |
| `geekName` | `geekCard` 对象内 | 候选人姓名（用于显示） |

**数据结构示例**：
```json
{
  "encryptGeekId": "abc123...",
  "geekCard": {
    "securityId": "xyz789...",
    "geekName": "张三",
    "ageDesc": "25岁",
    "degreeDesc": "本科"
  }
}
```

### 输出文件

`recommend_geek_ids.json` — 候选人列表，包含所有候选人的 ID 信息。

---

## Step 2: 批量获取完整简历

**原理**：使用 CLI `boss hr resume` 命令，传入 Step 1 获取的 `encryptGeekId` 和 `securityId`，获取完整简历数据。

### 核心操作

```python
import json, subprocess, time, random
from datetime import datetime

# 读取候选人列表
with open('recommend_geek_ids.json', 'r', encoding='utf-8') as f:
    geek_list = json.load(f)

# 从 URL 或岗位列表获取 jobId
job_id = 'f6955637fbe03b0b0nF90t64FFdQ'  # 示例，实际需动态获取

resumes = []
failed = []
hit_limit = False

start_time = datetime.now()
print(f'Start: {start_time.strftime("%H:%M:%S")}')

for i, g in enumerate(geek_list):
    geek_id = g.get('encryptGeekId', '')
    geek_card = g.get('geekCard', {})
    security_id = geek_card.get('securityId', '') if isinstance(geek_card, dict) else ''
    name = geek_card.get('geekName', '') if isinstance(geek_card, dict) else ''
    
    if not geek_id or not security_id:
        failed.append({'index': i+1, 'name': name, 'reason': 'no IDs'})
        continue
    
    # 随机延迟 5-20 秒（模拟真人看简历的时间）
    delay = random.uniform(5, 20)
    
    elapsed = (datetime.now() - start_time).total_seconds() / 60
    print(f'[{elapsed:.1f}min] #{i+1}: {name}...', end=' ', flush=True)
    
    # 调用 CLI 获取简历
    cmd = [
        'boss.exe', '--role', 'recruiter', '--platform', 'zhipin',
        '--cdp-url', 'http://localhost:9222',
        'hr', 'resume', geek_id,
        '--security-id', security_id,
        '--job-id', job_id
    ]
    
    result = subprocess.run(cmd, capture_output=True)
    stdout = result.stdout.decode('utf-8', errors='ignore')
    
    try:
        resp = json.loads(stdout)
        if resp.get('ok'):
            data = resp.get('data', {})
            zpdata = data.get('zpData', {}) if isinstance(data, dict) else {}
            block = zpdata.get('blockDialog', {}) if isinstance(zpdata, dict) else {}
            
            # 检查是否触发每日上限
            if block.get('title') and '上限' in block.get('title', ''):
                print(f'LIMIT: {block.get("title")}')
                hit_limit = True
                break
            elif data.get('basic'):
                # 提取完整简历
                resumes.append({
                    'name': data.get('basic', {}).get('name', name),
                    'age': data.get('basic', {}).get('age'),
                    'degree': data.get('basic', {}).get('degree'),
                    'work_years': data.get('basic', {}).get('work_years'),
                    'expectation': data.get('expectation'),
                    'work_experience': data.get('work_experience', []),
                    'project_experience': data.get('project_experience', []),
                    'education': data.get('education', []),
                    'certifications': data.get('certifications', [])
                })
                print('OK')
            else:
                print('EMPTY')
                failed.append({'index': i+1, 'name': name, 'reason': 'empty'})
        else:
            err = resp.get('error', {}).get('message', '')
            print(f'ERR: {err[:40]}')
            failed.append({'index': i+1, 'name': name, 'reason': err[:50]})
    except:
        print('PARSE ERR')
        failed.append({'index': i+1, 'name': name, 'reason': 'parse error'})
    
    # 随机延迟
    if not hit_limit and i < len(geek_list) - 1:
        time.sleep(delay)

# 保存结果
duration = (datetime.now() - start_time).total_seconds() / 60
print(f'\nDuration: {duration:.1f} min')
print(f'Success: {len(resumes)}')
print(f'Failed: {len(failed)}')
print(f'Hit daily limit: {hit_limit}')

with open('recommend_resumes.json', 'w', encoding='utf-8') as f:
    json.dump(resumes, f, ensure_ascii=False, indent=2)

with open('recommend_failed.json', 'w', encoding='utf-8') as f:
    json.dump(failed, f, ensure_ascii=False, indent=2)
```

### 完整简历数据结构

```json
{
  "name": "张三",
  "age": "25岁",
  "degree": "本科",
  "work_years": "3年",
  "expectation": {
    "position": "测试工程师",
    "salary": "10-15K",
    "city": "宁波"
  },
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
| `recommend_resumes.json` | 成功获取的完整简历列表 |
| `recommend_failed.json` | 失败的候选人及原因 |

---

## ⚠️ 安全策略

### 随机延迟（核心）

| 操作 | 延迟范围 | 说明 |
|------|---------|------|
| 页面滚动 | 3-6 秒 | 模拟真人浏览速度 |
| 获取简历 | 5-20 秒 | 模拟真人看简历的时间（有的快扫 5 秒，有的细看 20 秒） |

### 运行时间

- ✅ **推荐**：工作时间（9:00-18:00）
-  **避免**：凌晨或深夜（异常行为）

### 批量控制

- 单次运行建议不超过 100 人
- 如需获取更多，分多次运行
- 遇到"今日查看已达上限"立即停止

### 风控检测维度

| 维度 | 安全做法 | 危险做法 |
|------|---------|---------|
| 请求频率 | 5-20 秒随机 | 固定间隔或高频 |
| 操作时间 | 工作时间 | 凌晨 |
| 行为模式 | 有滚动有停顿 | 纯 API 无页面交互 |
| 总量控制 | 分批次 | 一次几百个 |

---

##  故障排查

### CLI 返回 `'NoneType' object has no attribute`

**原因**：候选人没有完整简历或数据结构异常。

**解决**：跳过该候选人，继续处理下一个。

### CLI 返回 `今日查看已达上限`

**原因**：BOSS 直聘每日查看简历数量限制。

**解决**：等待第二天额度刷新后继续。

### CLI 返回 GBK 编码错误

**原因**：简历中包含 `•` 等特殊字符，GBK 无法编码。

**解决**：设置环境变量 `PYTHONIOENCODING=utf-8`。

### 滚动时没有加载更多候选人

**原因**：可能在主页面滚动而非 iframe 内。

**解决**：确保在 iframe 内执行 `window.scrollBy()`：
```python
iframe = pg.query_selector('iframe')
frame = iframe.content_frame()
frame.evaluate('window.scrollBy(0, 1500)')
```

---

## 📊 预期结果

| 指标 | 数值 |
|------|------|
| 候选人列表获取 | 100-500 人（取决于岗位推荐量） |
| 简历获取成功率 | 10-30%（部分候选人无完整简历） |
| 单人耗时 | 5-20 秒 |
| 100 人耗时 | 约 10-30 分钟 |
| 封号风险 | 🟢 极低（随机延迟 + 真人行为模拟） |

---

## 📝 使用示例

```bash
# 1. 确保已完成登录（参考 boss-hr-auto skill）
source scripts/setup_env.sh

# 2. 设置环境变量
export PYTHONIOENCODING=utf-8

# 3. 运行 Step 1：获取候选人列表
python scripts/recommend_list.py

# 4. 运行 Step 2：批量获取简历
python scripts/recommend_download.py
```

**输出文件位置**：
- `recommend_geek_ids.json` — 候选人列表
- `recommend_resumes.json` — 完整简历
- `recommend_failed.json` — 失败列表
