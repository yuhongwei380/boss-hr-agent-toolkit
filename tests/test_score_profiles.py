# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "shared")))

from score_profiles import (
    DIM_KEYS,
    PROFILES,
    assert_profiles_valid,
    get_profile,
    normalize_profile_id,
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
