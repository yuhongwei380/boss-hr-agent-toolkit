# -*- coding: utf-8 -*-
"""pytest 配置

解决 school_tier.py 在 import 时对 sys.stdout 的 re-wrap 与 pytest 捕获/输出系统的冲突。

策略：在 conftest 加载阶段（早于任何测试代码 import），把 sys.stdout.encoding
置为 "utf-8"。这样 school_tier.py 里的 re-wrap 条件（`startswith("utf")`）
不成立，re-wrap 会被跳过，pytest 的捕获/输出就安全。
"""
import sys


# 在 conftest 加载时立刻生效,优先于任何测试文件 import
if sys.platform == "win32":
    # 直接给 sys.stdout 替换 encoding（不重建 TextIOWrapper,避免破坏 pytest 的捕获）
    try:
        # Python 3.7+ 的 reconfigure 方法
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        # 某些捕获器不支持 reconfigure,降级处理
        try:
            sys.stdout.encoding = "utf-8"  # type: ignore[attr-defined]
            sys.stderr.encoding = "utf-8"  # type: ignore[attr-defined]
        except Exception:
            pass
