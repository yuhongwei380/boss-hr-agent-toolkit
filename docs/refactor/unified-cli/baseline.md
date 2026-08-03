# 测试基线（2026-08-03）

- pytest 9.1.1 + Python 3.13.12 + 系统 pip 装的 patchright 1.59.1
- 不在 .venv 跑（.venv 没装 pytest）
- 必须 `-p no:cacheprovider --capture=no`，否则 conftest 顶层的 `sys.stdout.reconfigure` 会让 `_pytest.capture` 在 collection 阶段抛 `I/O operation on closed file`

## 初始基线（修测试前）

- collected 97 items
- 96 passed
- 1 failed: `tests/test_score_resumes.py::test_main_cli_end_to_end`
  - 原因：测试直接调 `sr.main()` 时 sys.argv 只有 `--input / --output / --job-name`，没传 `--run-id`，argparse 拒绝
  - 生产代码的 `--run-id required=True` 是**设计约束**（run_id 是数据边界），不能降

## 修复后

- `tests/test_score_resumes.py` 新增 `fake_run` fixture：在 tmp_path 下建 `runs/<run_id>/process/new_resumes.json`（含 geek_id），并 monkeypatch `BOSS_HR_OUTPUT_DIR` 指向 tmp_path（conftest 已做）
- `test_main_cli_end_to_end` 改用 `fake_run`，显式传 `--encrypt-job-id` / `--run-id`；输入 LLM 评分也加上 `geek_id` 字段（与 fake_run 的 process 简历池对齐）
- 新增独立用例 `test_main_cli_missing_run_id_exits`：验证缺 `--run-id` 时 argparse 立即 `SystemExit(2)`
- **最终 98/98 passed**（97 原有 + 1 新增缺 run_id 失败用例）

## 分类（修测试前）

- A 类（文档与代码不一致）：已记 docs/refactor/unified-cli/issues-classified.md
- B 类（阻碍 CLI 重构）：已记同上
- C 类（与 CLI 无关）：test_main_cli_end_to_end 缺 `--run-id` 原本归 C，本次已修

## 已知遗留（不在本轮修）

- `sr.main()` 直接用 `print(...)` 写 stdout，与 pytest 进度行交错；
  跑测试时需要 `> /tmp/pytest.out 2>&1` 后再 grep。
  修法：把 sr.main() 内部 print 改去 stderr —— 但**改生产代码不在本轮范围**，单独立 B 类项。
