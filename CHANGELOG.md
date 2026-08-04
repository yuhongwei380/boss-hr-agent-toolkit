# Changelog

## v1.1.2 — 自动启动专用 Edge + waiting_user_login（CLI Preview，2026-08-04）

在 v1.1.0 / v1.1.1 之上，本版引入"无需先跑 doctor"的首次用户体验：
start / fetch / greet 共用 `boss_hr/adapters/browser_environment.ensure_browser_ready`，
9222 未监听时自动启动专用 Edge 并打开 BOSS 招聘者登录页；未登录则优雅返回
`status=waiting_user_login` 而非错误。

### 新增

- `boss_hr/adapters/browser_environment.py`
  - `ensure_browser_ready(auto_launch, login_wait_seconds)`：start/fetch/greet 共用
  - `launch_dedicated_edge()`：专用 Edge（`--user-data-dir=%LOCALAPPDATA%\boss-hr-edge-profile`
    + `--remote-debugging-port=9222`，**不污染**用户日常 Edge profile）
  - `_open_login_page()`：复用 `shared.cdp_preflight.connect_cdp` 的 session.page，
    导航到 BOSS 招聘者登录入口并 `bring_to_front`
- `boss-hr start --no-auto-launch`（调试/测试用；缺 CDP 时直接 `CDP_NOT_RUNNING`）
- `boss-hr start --login-wait-seconds N`（默认 20）
- 新 status：`waiting_user_login`（`ok=true`，`next_action=retry_same_command`，
  **不创建 run**）

### 修复（v1.1.2 fix 真实 smoke 暴露）

- `_open_login_page` 不再静默吞异常：返回 `(ok: bool, reason: str)`，reason 是
  异常类型名 + 短前缀，不含 Cookie / token / URL-secret
- 修复 `patchright` Sync API 在 asyncio loop 中冲突的 bug：
  `_open_login_page` 不再启动第二个 `sync_playwright()` 实例
- `ensure_browser_ready` 超时分支的 `message` 与 `remediation` 严格按
  `login_page_opened` 分支，**绝不伪称已打开登录页**
- `start_service` `waiting_user_login.message` 同步分支：
  - `login_page_opened=true` → "已为你打开专用 Edge，请在浏览器中扫码登录
    BOSS 招聘者后台。完成后回复"好了"，我会继续当前任务。"
  - `login_page_opened=false` → "已为你启动专用 Edge，但未能自动打开 BOSS
    招聘者登录页（<脱敏原因>）。请在已打开的专用 Edge 窗口中手动打开
    https://www.zhipin.com/web/chat/recommend 登录。完成后回复"好了"，
    我会继续当前任务。"

### 变更

- `boss-hr-auto/SKILL.md`：移除"首次必须先跑 doctor"的硬约束；新增
  `waiting_user_login` 智能体处理流程（直接告诉用户扫码登录并立即停止；
  用户回复"好了"后重试同一条 start，不传任何新参数）
- `README.md`：快速开始前置条件放宽（不再要求预先手动启动 Edge）
- `docs/CLI_WORKFLOW.md`：命令表扩为 8 个（含 doctor），每个标注浏览器依赖；
  §2 流程图加入自动启动 / `waiting_user_login` 分支；新增"waiting_user_login
  重试"子节
- `tests/test_v112_auto_browser.py`：25 个测试（v1.1.2 实现 18 个 +
  v1.1.2 fix 7 个回归保护）

### 测试基线

**336 passed, pytest exit code 0**。

### 已验证（真实 Windows 环境，2026-08-04）

- ✅ 9222 未监听 → start 自动启动专用 Edge（专用 profile + `--remote-debugging-port=9222`）
- ✅ `_open_login_page` 真实把专用 Edge 导航到 `https://www.zhipin.com/web/user/?ka=bticket`
  （BOSS 招聘者登录入口），并 `bring_to_front` 聚焦
- ✅ 未登录 → start 返回 `status=waiting_user_login`、`data.login_page_opened=true`、
  `data.login_page_open_error=""`、`run_id=null`（**不创建 run**）
- ✅ message 明确告诉用户扫码登录（与 SKILL.md 强制文案一致）
- ✅ 重试同一条命令（不传任何新参数）→ 行为幂等（再次 `waiting_user_login`，
  复用既有 Edge，再次成功导航到 zhipin.com）
- ✅ 不读取 `~/Desktop/boss-hr-output/jobs.json`（mtime 未变）
- ✅ confirm / score / report / status / greet 未触发
- ✅ `tests/test_v112_auto_browser.py` 25 个测试（含 7 个回归保护）全部通过
- ✅ 完整 pytest 336 passed

### 未验证（需真人 BOSS 招聘者扫码）

- ⏸ `status=waiting_user_confirmation` 的真实路径：本会话环境无 BOSS 招聘者
  账号扫码能力，`zp_at` / `wt2` / `bst` 三个关键 Cookie 全部缺失。第二次 start
  无法走通"实时解析岗位 → 创建 run → waiting_user_confirmation"完整路径
- ⏸ `boss-hr fetch --count N` 真实拉取 + 下载简历的端到端流程
- ⏸ `boss-hr greet` 真实点击打招呼（v1.1.0 起就标注"未受控验证"，本版不引入
  新风险）

如需在生产环境验证上述未验证路径，请在已扫码登录 BOSS 招聘者后台的
Windows + 9222 已就绪的环境执行：

```bash
boss-hr start "<encryptJobId|jobId|岗位名>"
# 第二次执行同一条命令后应返回 waiting_user_confirmation + 新 run_id
boss-hr status --job-name "<>" --encrypt-job-id "<>" --run-id "<rid>"
# 应返回 confirmed=false，process/job_detail.json 已存在
```

### 当前限制（GitHub Preview）

- 不支持 `continue` / `batch` / `--batch-size` / 多批累计
- 真实 `greet` 成功路径（≥70 分候选人浏览器实际点击发送）**尚未完成受控验证**
- 仅在 Windows + Git Bash 上完整测试过；macOS / Linux 需自测
- 当前发布形态：**GitHub 源码工具包 + editable install**，**不是**独立 wheel；
  移动源码后必须重新 `pip install -e .`
- 不发布到 PyPI；不在 wheel 中包含完整业务脚本

### 安装

```bash
git clone https://github.com/<owner>/boss-hr-agent-toolkit
cd boss-hr-agent-toolkit
python -m pip install -e .
boss-hr --help           # 验证 8 个公开命令（含 doctor）
```

或 Windows：

```bat
install-windows.bat
```

---

## v1.1.0 — 统一 CLI Preview（2026-08-04）

GitHub 首版发布状态：**v1.1.0 / CLI Preview**。

### 新增

- **统一 CLI `boss-hr`**（子包 `boss_hr/`），7 个公开命令：
  - `boss-hr start` — 创建新 run，停在人工确认门
  - `boss-hr confirm` — `confirmed` 翻 true；不入 `steps_done`
  - `boss-hr fetch --count N` — 拉候选人列表 + 下载 N 份简历
  - `boss-hr score` — 评分协调（一次返回 1 位候选人）
  - `boss-hr report` — 生成 HTML 报告
  - `boss-hr greet` — ≥70 分候选人打招呼（需用户明确批准）
  - `boss-hr status` — 读 `runs/<run_id>/run.json` + process 目录
- 统一 JSON 输出 schema；退出码语义保留旧脚本契约
- 人工确认门：start 后必须停下，等用户回复"继续"
- 单候选人评分循环：`score` 命令必须 LLM 多次调用，每次一位
- `boss_hr/__main__.py`：让 `python -m boss_hr` 工作
- `pyproject.toml`：唯一 console_script `boss-hr = "boss_hr.cli:main"`
- Windows 脚本：`install-windows.bat` / `uninstall-windows.bat`
- 文档：
  - `docs/CLI_WORKFLOW.md`（GitHub 用户/开发者向）
  - `docs/refactor/unified-cli/HANDOFF.md`（已迁移完成）
  - `docs/refactor/unified-cli/real-smoke-2026-08-04.md`（真实 smoke 脱敏记录）
  - `docs/debug/boss_jd-cache-audit-2026-08-04.md`（JD formValues 调查）

### 修复（auto_greet.py 旧业务缺陷）

- `edc6959 fix(greet): prevent deletion of existing run data`
  - 之前 atexit 调 `prune_if_empty()` 会 `rmtree` 整个 run 目录
  - 现在改为 `note_skip_if_unsaved()` 只写日志 + sentry，永不删文件
  - 23 例回归测试覆盖（11 prune + 12 maybe_finish）
- `ad243ad fix(greet): finish the explicit run after successful greeting`
  - 之前 `orch.finish()` 缺 `run_id` 实参 + `except Exception` 吞错
  - 现在用 `maybe_finish()` 显式传 `run_id`，异常不静默

### 变更

- `boss-hr-auto/SKILL.md` 重写为唯一面向智能体的工作流入口
  （350 行 → 187 行），不再指导调用旧业务脚本
- 其他子 SKILL.md 标记为"业务实现参考"，不再暗示是工作流入口
- `README.md` 头部增加"统一 CLI + editable install"产品定位

### 安装

```bash
git clone https://github.com/<owner>/boss-hr-agent-toolkit
cd boss-hr-agent-toolkit
python -m pip install -e .
boss-hr --help           # 验证 7 个公开命令
```

或 Windows：

```bat
install-windows.bat
```

### 测试基线

发布时：**272 passed, pytest exit code 0**。

包括：
- 业务测试（`tests/test_*`）：CLI 子层、run_id 边界、cli_runner、school_tier、job_registry
- 统一 CLI 测试（`tests/cli/test_*.py`）：每条命令都有专项覆盖
- 安装入口测试（`tests/test_install_entry.py`）：12 例

### 当前限制（GitHub 首版）

**必须如实记录**：

- 不支持 `continue` / `batch` / `--batch-size` / 多批累计
- 真实 `greet` 成功路径（≥70 分候选人浏览器实际点击发送）**尚未完成受控验证**
- 仅在 Windows + Git Bash 上完整测试过；macOS / Linux 需自测
- 当前发布形态：**GitHub 源码工具包 + editable install**，**不是**独立 wheel；
  移动源码后必须重新 `pip install -e .`
- 不发布到 PyPI；不在 wheel 中包含完整业务脚本

### 已知不修的旧脚本缺陷（按"无行为变化"约束保留）

- `auto_greet.py` 函数体引用只在 `__main__` 定义的全局 `args` — 新 CLI 走子进程规避

### 升级提示

从 v1.1-skill-stable（旧版直接调 9 个脚本）升级：

1. 旧脚本保留作为内部实现（cli_runner 子进程调用）
2. 所有调用改用 `boss-hr` 命令
3. 不再直接 `python boss_jd.py` / `python auto_greet.py`
4. 不再创建 `spec_*.json` 模板