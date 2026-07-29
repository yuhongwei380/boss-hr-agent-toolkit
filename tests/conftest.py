# -*- coding: utf-8 -*-
"""pytest 配置

解决 school_tier.py 在 import 时对 sys.stdout 的 re-wrap 与 pytest 捕获/输出系统的冲突。

策略：在 conftest 加载阶段（早于任何测试代码 import），把 sys.stdout.encoding
置为 "utf-8"。这样 school_tier.py 里的 re-wrap 条件（`startswith("utf")`）
不成立，re-wrap 会被跳过，pytest 的捕获/输出就安全。
"""
import os
import sys
import tempfile

import pytest


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


@pytest.fixture(autouse=True)
def _isolate_output_root(tmp_path, monkeypatch):
    """强制把每个测试的输出根隔离到临时目录，防止污染用户真实的
    ~/Desktop/boss-hr-output/。

    为什么需要这个：`output_manager.OUTPUT_ROOT` 是模块级常量，在 import
    那一刻就由 BOSS_HR_OUTPUT_DIR 环境变量固化。测试内部再改环境变量对
    已 import 的模块无效 —— 曾因此在用户桌面留下 9 个「测试XxxJob」空壳
    文件夹（2026-07-29）。所以必须直接 patch 模块属性。
    """
    monkeypatch.setenv("BOSS_HR_OUTPUT_DIR", str(tmp_path))

    _shared = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "shared"))
    if _shared not in sys.path:
        sys.path.insert(0, _shared)

    try:
        import output_manager
    except ImportError:
        # shared/ 不可用的测试（如纯算法测试）无需隔离
        yield
        return

    monkeypatch.setattr(output_manager, "OUTPUT_ROOT", str(tmp_path), raising=False)
    yield
