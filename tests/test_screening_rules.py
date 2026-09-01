# -*- coding: utf-8 -*-
"""screening_rules：规则加载、年限映射、卡片粗筛。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "shared")))

from screening_rules import (
    coarse_screen_list,
    coarse_screen_one,
    load_rules,
    map_years_to_boss_experience,
    normalize_education,
    parse_geek_info_payload,
    rules_from_dict,
)


def _geek(*, name="张三", degree="本科", years="5年", extra=None):
    g = {
        "encryptGeekId": "gid_1",
        "geekCard": {
            "geekName": name,
            "geekDegree": degree,
            "geekWorkYear": years,
            "expectPosition": "结构设计",
        },
    }
    if extra:
        g["geekCard"].update(extra)
    return g


def test_map_years_buckets():
    assert map_years_to_boss_experience(3, 5) == "3-5年"
    assert map_years_to_boss_experience(5, 10) == "5-10年"
    assert map_years_to_boss_experience(0, 1) == "1年以内"
    assert map_years_to_boss_experience(10, None) == "10年以上"
    assert map_years_to_boss_experience(None, None) is None


def test_normalize_education():
    assert normalize_education("本科及以上") == "本科"
    assert normalize_education("硕士") == "硕士"
    assert normalize_education("专科") == "大专"


def test_load_rules_json(tmp_path: Path):
    p = tmp_path / "rules.json"
    p.write_text(json.dumps({
        "job": {"query": "车架工程师", "jd": "会 CATIA"},
        "coarse_screen": {
            "education_min": "本科",
            "years_min": 3,
            "keywords_any": ["CATIA"],
            "keywords_exclude": ["销售"],
        },
        "download": {"list_count": 20, "max_details": 5},
    }, ensure_ascii=False), encoding="utf-8")
    rules = load_rules(str(p))
    assert rules.job_query == "车架工程师"
    assert rules.education_min == "本科"
    assert rules.years_min == 3
    assert rules.boss_experience == "3-5年"
    assert rules.max_details == 5
    assert "CATIA" in rules.keywords_any


def test_coarse_reject_degree_and_years():
    rules = rules_from_dict({
        "coarse_screen": {"education_min": "本科", "years_min": 3, "years_max": 8},
    })
    low = coarse_screen_one(_geek(degree="大专", years="5年"), rules)
    assert low["pass"] is False
    assert any("学历" in r for r in low["reasons"])
    junior = coarse_screen_one(_geek(degree="本科", years="1年"), rules)
    assert junior["pass"] is False
    ok = coarse_screen_one(_geek(degree="本科", years="5年"), rules)
    assert ok["pass"] is True


def test_coarse_exclude_keywords():
    rules = rules_from_dict({
        "coarse_screen": {"keywords_exclude": ["销售"]},
    })
    hit = coarse_screen_one(_geek(extra={"expectPosition": "汽车销售顾问"}), rules)
    assert hit["pass"] is False
    miss = coarse_screen_one(_geek(extra={"expectPosition": "结构设计"}), rules)
    assert miss["pass"] is True


def test_keywords_any_does_not_reject_when_card_is_thin():
    """卡片上看不到关键词时不应一票否决，留给详情 JD。"""
    rules = rules_from_dict({
        "coarse_screen": {"keywords_any": ["CATIA", "车架"]},
    })
    r = coarse_screen_one(_geek(extra={"expectPosition": "结构设计"}), rules)
    assert r["pass"] is True


def test_coarse_screen_list_splits_passed_rejected():
    rules = rules_from_dict({"coarse_screen": {"education_min": "本科"}})
    geeks = [
        _geek(name="合格", degree="本科", years="4年"),
        {**_geek(name="淘汰", degree="大专", years="4年"), "encryptGeekId": "gid_2"},
    ]
    out = coarse_screen_list(geeks, rules)
    assert out["passed_count"] == 1
    assert out["rejected_count"] == 1
    assert out["passed"][0]["geekCard"]["geekName"] == "合格"


def test_parse_geek_info_payload():
    parsed = parse_geek_info_payload({
        "code": 0,
        "zpData": {
            "geekDetailInfo": {
                "geekBaseInfo": {
                    "name": "李四",
                    "degreeCategory": "本科",
                    "workYearDesc": "4年",
                },
                "geekWorkExpList": [
                    {"company": "A", "positionName": "结构", "responsibility": "做车架"},
                ],
                "geekDesc": "熟悉 CATIA",
            }
        },
    })
    assert parsed["ok"] is True
    assert parsed["name"] == "李四"
    assert parsed["work_experience"][0]["company"] == "A"
    assert parsed["user_desc"] == "熟悉 CATIA"


def test_parse_limit_dialog():
    parsed = parse_geek_info_payload({
        "code": 0,
        "zpData": {"blockDialog": {"title": "今日查看已达上限"}},
    })
    assert parsed["ok"] is False
    assert parsed.get("limit") is True
