# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "shared")))

from score_profiles import (
    DIM_KEYS,
    PROFILES,
    TECH_STACKS,
    assert_profiles_valid,
    get_profile,
    normalize_profile_id,
    normalize_tech_stacks,
)


def test_profiles_valid():
    assert_profiles_valid()
    assert set(PROFILES) == {"tech", "sales", "intern"}


def test_normalize_aliases():
    assert normalize_profile_id(None) == "tech"
    assert normalize_profile_id("") == "tech"
    assert normalize_profile_id("销售类岗位") == "sales"
    assert normalize_profile_id("intern") == "intern"
    assert normalize_profile_id("unknown") == "tech"


def test_tech_matches_legacy_weights():
    p = get_profile("tech")
    assert p.weights == {"edu": 0.25, "exp": 0.25, "skill": 0.25, "proj": 0.15, "major": 0.10}
    assert p.weights_pct == {"edu": 25, "exp": 25, "skill": 25, "proj": 15, "major": 10}


def test_sales_and_intern_shift_weights():
    sales = get_profile("sales")
    intern = get_profile("intern")
    assert sales.weights["exp"] > sales.weights["edu"]
    assert intern.weights["edu"] > intern.weights["exp"]
    assert intern.weights["major"] > get_profile("tech").weights["major"]
    for p in (sales, intern):
        assert set(p.weights) == set(DIM_KEYS)
        assert abs(sum(p.weights.values()) - 1.0) < 1e-9


def test_tech_stacks_catalog_covers_jishu_tracks():
    assert "C++" in TECH_STACKS
    assert "JavaScript / TypeScript" in TECH_STACKS
    assert "数据库内核" in TECH_STACKS
    assert "Query Engine / Optimizer" in TECH_STACKS
    assert "图数据库" in TECH_STACKS
    assert "AI 应用开发" in TECH_STACKS
    assert len(TECH_STACKS) == len(set(TECH_STACKS))


def test_normalize_tech_stacks_aliases_and_unknown():
    assert normalize_tech_stacks(None) == []
    assert normalize_tech_stacks(["C++", "数据库内核", "C++", "未知栈"]) == ["C++", "数据库内核"]
    assert normalize_tech_stacks("JS, Query Engine, 图计算") == [
        "JavaScript / TypeScript",
        "Query Engine / Optimizer",
        "图计算 / 图算法",
    ]

