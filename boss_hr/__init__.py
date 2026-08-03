# boss_hr/ — 统一 CLI 子包占位说明

## 目的

按用户的"验证性统一 CLI 重构"任务逐步迁移旧脚本到 `boss-hr` 命令。
第一轮只实现 status；后续按 status → report → confirm → score → fetch → start → greet 顺序。

## 第一阶段实现策略（用户指定）

> 统一 CLI → shared.cli_runner.run_python_cli() → 现有脚本

但 **status 没有对应的旧脚本**，所以 status 在 `boss_hr/cli.py` 内部直接
import 共享层（shared/output_manager + shared/run_orchestrator）读 run.json
和 process/ 目录，**不走 subprocess**。

## 包结构（规划）

```
boss_hr/
├── __init__.py           # 占位
├── cli.py                # 统一入口（argparse + subcommands）
├── commands/             # 每条命令一个文件（status / report / confirm / ...）
└── application/          # 业务层；调用 shared/* 库
```

status 当前直接放在 `cli.py:cmd_status()` 里（避免过度拆分）。

## 退出码

详见 `cli.py` 顶部注释。
