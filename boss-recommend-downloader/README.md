# boss-recommend-downloader

推荐牛人简历批量下载器 —— 安全获取推荐牛人页面的完整在线简历。

## 快速开始

### 1. 前置条件

确保已完成 `boss-hr-auto` skill 的环境准备和登录：

```bash
# 设置环境变量
export PYTHONIOENCODING=utf-8
export PYTHONHOME=""
export PATH="$PATH:$HOME/.local/bin"

# 关闭 CLI 低风险模式（必须）
cat > ~/.boss-agent/config.json << 'EOF'
{
  "low_risk_mode": false,
  "platform": "zhipin",
  "role": "recruiter"
}
EOF
```

### 2. 一键运行

```bash
cd boss-recommend-downloader
python scripts/run_all.py
```

### 3. 分步运行

```bash
# Step 1: 获取候选人列表
python scripts/recommend_list.py --output recommend_geek_ids.json

# Step 2: 批量获取简历
python scripts/recommend_download.py \
  --input recommend_geek_ids.json \
  --job-id <你的岗位ID>
```

## 输出文件

| 文件 | 内容 |
|------|------|
| `recommend_geek_ids.json` | 候选人列表（ID 信息） |
| `recommend_resumes.json` | 完整简历数据 |
| `recommend_failed.json` | 失败的候选人及原因 |

## 安全策略

- **滚动延迟**：3-6 秒随机（模拟真人浏览）
- **简历获取**：5-20 秒随机（模拟真人阅读）
- **运行时间**：建议工作时间（9:00-18:00）
- **批量控制**：单次建议不超过 100 人

## 故障排查

### CLI 返回 `'NoneType' object has no attribute`
候选人没有完整简历，跳过即可。

### CLI 返回 `今日查看已达上限`
BOSS 直聘每日限制，等待第二天刷新。

### 滚动时没有加载更多
确保在 iframe 内滚动，不是主页面。

## 依赖

- Python 3.10+
- patchright
- boss-agent-cli
- Edge 浏览器（CDP 模式，端口 9222）
