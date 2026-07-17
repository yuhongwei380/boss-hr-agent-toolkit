# boss-recommend-downloader

推荐牛人简历批量下载器 —— 通过真实浏览器指纹安全获取推荐牛人页面的完整在线简历。

## 核心原理

使用 patchright 控制真实 Edge 浏览器，在页面内执行 `fetch()` 调用 BOSS API。
请求使用**浏览器的真实 TLS 指纹和 Cookie**，与真人操作完全一致，服务器无法区分。

## 快速开始

### 1. 前置条件

确保已完成 `boss-hr-auto` skill 的环境准备和登录：
- Python 3.10+
- patchright（`pip install patchright`）
- Edge 浏览器 CDP 模式（端口 9222）
- BOSS 直聘已扫码登录

### 2. 分批运行（推荐）

```bash
cd boss-recommend-downloader/scripts

# Batch 1：收集25人 → 下载简历
python recommend_list.py --job-name 车架工程师 --batch-size 25 --batch 1
python recommend_download_v2.py --job-name 车架工程师 --batch 1

# Batch 2：继续滚动（不刷新页面）→ 下载
python recommend_list.py --job-name 车架工程师 --batch-size 25 --batch 2
python recommend_download_v2.py --job-name 车架工程师 --batch 2
```

### 3. 一次性运行

```bash
python recommend_list.py --job-name 车架工程师
python recommend_download_v2.py --job-name 车架工程师
```

## 输出文件

所有文件保存在 `~/Desktop/boss-hr-output/<岗位名>/process/` 下：

| 文件 | 内容 |
|------|------|
| `batch_N_ids.json` | 第 N 批候选人 ID |
| `batch_N_resumes.json` | 第 N 批下载的完整简历 |
| `test_resumes.json` | 累计所有已下载简历 |
| `batch_N_failed.json` | 失败的候选人及原因 |
| `recommend_geek_ids.json` | 累计所有候选人 ID |

## 安全策略

- **TLS 指纹**：真实 Edge 浏览器（非 Python requests），服务器无法区分
- **滚动延迟**：3-6 秒随机（模拟真人浏览）
- **简历获取**：5-15 秒随机（模拟真人阅读）
- **运行时间**：建议工作时间（9:00-18:00）
- **批量控制**：单批建议 25-50 人，超过则分多批

## 故障排查

| 问题 | 原因 | 解决 |
|------|------|------|
| 今日查看已达上限 | BOSS 每日查看数量限制 | 等待第二天刷新 |
| fetch 返回空数据 | 登录 session 过期 | 重新 `boss login --cdp` |
| 滚动不加载更多 | 在主页面而非 iframe 内滚动 | 脚本已自动处理 |

## 脚本说明

| 脚本 | 用途 |
|------|------|
| `recommend_list.py` | Step 1：滚动页面拦截 API 获取候选人列表 |
| `recommend_download_v2.py` | Step 2：patchright + fetch 下载简历（**主方案**） |
| `recommend_download.py` | Step 2：CLI 下载简历（已弃用，仅供开发者备用） |
| `run_all.py` | 一键运行 Step 1 + Step 2 |
