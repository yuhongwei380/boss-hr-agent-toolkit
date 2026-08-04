# Changelog

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