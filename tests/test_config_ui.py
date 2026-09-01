# -*- coding: utf-8 -*-
"""本地配置页：写出 rules.json + Agent 提示词。"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "config-ui"))
sys.path.insert(0, str(_ROOT / "shared"))

import serve as config_serve  # noqa: E402
from screening_rules import load_rules  # noqa: E402


def test_save_requires_job_query(tmp_path):
    with pytest.raises(ValueError, match="岗位"):
        config_serve.save_config({"job": {"query": "", "jd": "x"}}, str(tmp_path))


def test_save_uses_top_level_query_when_jobs_empty(tmp_path):
    result = config_serve.save_config(
        {
            "jobs": [{"query": "", "jd": ""}],
            "query": "车架工程师",
            "jd": "需要 CATIA",
            "education": ["本科"],
        },
        str(tmp_path),
    )
    assert result["job_query"] == "车架工程师"
    rules = load_rules(result["rules_path"])
    assert rules.job_query == "车架工程师"
    assert rules.jd == "需要 CATIA"


def test_save_writes_rules_and_prompt(tmp_path):
    raw = {
        "job": {"query": "车架工程师", "jd": "需要 CATIA"},
        "boss_filters": {"education": "本科", "experience": "3-5年", "keywords": "CATIA"},
        "coarse_screen": {
            "education_min": "本科",
            "years_min": 3,
            "years_max": 8,
            "keywords_any": ["CATIA", "车架"],
            "keywords_exclude": ["销售"],
        },
        "download": {"list_count": 30, "max_details": 6},
        "score": {"greet_threshold": 75},
    }
    result = config_serve.save_config(raw, str(tmp_path))
    path = Path(result["rules_path"])
    assert path.is_file()
    rules = load_rules(str(path))
    assert rules.job_query == "车架工程师"
    assert rules.jd == "需要 CATIA"
    assert rules.max_details == 6
    assert rules.score_profile == "tech"
    prompt = Path(result["rules_path"]).with_name("agent-prompt.txt").read_text(encoding="utf-8")
    assert "接着调用" in prompt
    assert "boss-hr greet --threshold 75" in prompt
    assert "--max 10" in prompt
    assert "车架工程师" in prompt
    assert str(path) in prompt
    assert "boss-hr start" in prompt
    assert "--rules" in prompt


def test_save_multiple_jobs_writes_each_rules_file(tmp_path):
    raw = {
        "jobs": [
            {"query": "车架工程师", "jd": "JD-A"},
            {"query": "结构工程师", "jd": "JD-B"},
        ],
        "education": ["本科", "硕士"],
        "experience": ["3-5年", "5-10年"],
        "list_count": 20,
        "max_details": 5,
    }
    result = config_serve.save_config(raw, str(tmp_path))
    assert result["job_count"] == 2
    assert len(result["jobs"]) == 2
    paths = [Path(j["rules_path"]) for j in result["jobs"]]
    assert all(p.is_file() for p in paths)
    a = load_rules(str(paths[0]))
    b = load_rules(str(paths[1]))
    assert a.job_query == "车架工程师" and a.jd == "JD-A"
    assert b.job_query == "结构工程师" and b.jd == "JD-B"
    assert a.education_min == "本科"
    prompt = (tmp_path / "_config" / "agent-prompt.txt").read_text(encoding="utf-8")
    assert "多个岗位" in prompt
    assert "车架工程师" in prompt and "结构工程师" in prompt
    assert "report → greet" in prompt


def test_build_agent_prompt_contains_path_and_auto_greet_after_report():
    text = config_serve.build_agent_prompt([
        {"rules_path": r"D:\rules.json", "query": "结构工程师"},
    ])
    assert r"D:\rules.json" in text
    assert "结构工程师" in text
    assert "接着调用" in text
    assert "boss-hr greet --threshold 70 --max 10" in text
    assert "不要自动打招呼" not in text
    assert "明确说打招呼" not in text
    assert "技术类岗位" in text
    assert "学历 25%" in text


def test_save_sales_profile_writes_rules_and_prompt(tmp_path):
    result = config_serve.save_config(
        {
            "jobs": [{"query": "销售代表", "jd": "负责客户开发"}],
            "education": ["本科"],
            "score_profile": "sales",
            "greet_threshold": 70,
        },
        str(tmp_path),
    )
    rules = load_rules(result["rules_path"])
    assert rules.score_profile == "sales"
    saved = json.loads(Path(result["rules_path"]).read_text(encoding="utf-8"))
    assert saved["score"]["profile"] == "sales"
    prompt = Path(result["rules_path"]).with_name("agent-prompt.txt").read_text(encoding="utf-8")
    assert "销售类岗位" in prompt
    assert "经验 35%" in prompt
    assert "学历 10%" in prompt


def test_save_greet_max_writes_rules_and_prompt(tmp_path):
    result = config_serve.save_config(
        {
            "jobs": [{"query": "销售代表", "jd": "JD"}],
            "education": ["本科"],
            "greet_threshold": 75,
            "greet_max": 5,
        },
        str(tmp_path),
    )
    rules = load_rules(result["rules_path"])
    assert rules.greet_max == 5
    assert rules.greet_threshold == 75
    prompt = Path(result["rules_path"]).with_name("agent-prompt.txt").read_text(encoding="utf-8")
    assert "--threshold 75" in prompt
    assert "--max 5" in prompt


def test_save_school_tier_erben_writes_min(tmp_path):
    result = config_serve.save_config(
        {
            "jobs": [{"query": "销售代表", "jd": "JD"}],
            "education": ["本科"],
            "school_tier": ["二本公办"],
        },
        str(tmp_path),
    )
    rules = load_rules(result["rules_path"])
    assert rules.school_tier_min == "二本公办"


def test_lowest_school_tier_picks_loosest_and_aliases():
    assert config_serve._lowest_school_tier(["C9", "一本公办"]) == "一本公办"
    assert config_serve._lowest_school_tier(["不限"]) is None
    assert config_serve._lowest_school_tier(["民办"]) == "民办本科"
    assert config_serve._lowest_school_tier(["985"]) == "985"


def test_save_jobs_array_without_legacy_job_key(tmp_path):
    result = config_serve.save_config(
        {
            "jobs": [{"query": "测试", "jd": "测试公式"}],
            "query": "测试",
            "jd": "测试公式",
            "education": ["本科"],
            "experience": ["3-5年"],
            "school_tier": [],
            "boss_keywords": [],
            "keywords_any": [],
            "keywords_exclude": [],
            "years_min": 3,
            "years_max": 10,
            "list_count": 40,
            "max_details": 10,
            "greet_threshold": 70,
        },
        str(tmp_path),
    )
    assert result["job_query"] == "测试"


def test_save_legacy_job_object(tmp_path):
    result = config_serve.save_config(
        {"job": {"query": "结构工程师", "jd": "JD"}, "education": ["本科"]},
        str(tmp_path),
    )
    assert result["job_query"] == "结构工程师"


def test_http_save_roundtrip(tmp_path):
    httpd = config_serve.make_server("127.0.0.1", 0, str(tmp_path))
    port = httpd.server_address[1]
    thread = __import__("threading").Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        import urllib.request
        payload = json.dumps({
            "jobs": [{"query": "测试岗", "jd": "JD 正文"}],
            "education": ["本科"],
            "list_count": 12,
            "max_details": 4,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/save",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        assert body["ok"] is True
        assert body["job_query"] == "测试岗"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=5) as resp:
            state = json.loads(resp.read().decode("utf-8"))
        assert state["saved"] is True
        assert state["form"]["jobs"][0]["query"] == "测试岗"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as resp:
            html = resp.read().decode("utf-8")
        assert "筛选配置" in html
        assert "添加岗位" in html
        assert "交给 Agent" in html
        assert "不想要的人" in html
        assert "非全日制" in html
        assert "希望看到的技能或方向" in html
        assert "这个分数怎么算" in html
        assert "评分标准" in html
        assert "销售类岗位" in html
        assert "实习生岗位" in html
        assert "技术类岗位" in html
        assert "看多少张简历卡片" in html
        assert "最多点开多少份简历" in html
        assert "最多给几个人打招呼" in html
        assert "报告后招呼" in html
        assert "自动发送" not in html
        assert "C9" in html
        assert "二本公办" in html
        assert "民办本科" in html
        assert "不限" in html
    finally:
        httpd.shutdown()
        httpd.server_close()
