# -*- coding: utf-8 -*-
"""推荐页必须切到本次岗位，不能沿用上次打开的职位。"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "shared"))
sys.path.insert(0, str(_ROOT / "boss-recommend-downloader" / "scripts"))

import recommend_filters as rf  # noqa: E402


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(rf.time, "sleep", lambda *a, **k: None)


def test_job_name_matches_ignores_intern_sibling():
    assert rf.job_name_matches("数据库应用研发工程师", "数据库应用研发工程师")
    assert rf.job_name_matches("数据库应用研发工程师 招聘中", "数据库应用研发工程师")
    assert not rf.job_name_matches("数据库内核实习生", "数据库应用研发工程师")
    assert not rf.job_name_matches("数据库内核实习生", "数据库")


def test_select_already_on_target(monkeypatch):
    monkeypatch.setattr(rf, "_read_current_job", lambda f: "数据库应用研发工程师")
    result = rf.select_recommend_job(object(), object(), {}, "数据库应用研发工程师")
    assert result["ok"] is True
    assert result["method"] == "already"


def test_select_clicks_job_filter(monkeypatch):
    visible = {"v": "数据库内核实习生"}
    monkeypatch.setattr(rf, "_read_current_job", lambda f: visible["v"])

    def pick(_page, _frame, _box, label, option):
        if label == "职位" and option == "数据库应用研发工程师":
            visible["v"] = option
            return True
        return False

    monkeypatch.setattr(rf, "_open_filter_and_pick", pick)
    result = rf.select_recommend_job(object(), object(), {}, "数据库应用研发工程师")
    assert result["ok"] is True
    assert result["method"] == "filter:职位"
    assert result["visible"] == "数据库应用研发工程师"


def test_select_reports_mismatch_when_stuck_on_other_job(monkeypatch):
    monkeypatch.setattr(rf, "_read_current_job", lambda f: "数据库内核实习生")
    monkeypatch.setattr(rf, "_open_filter_and_pick", lambda *a, **k: False)
    monkeypatch.setattr(rf, "_find_job_trigger_box", lambda f: None)
    monkeypatch.setattr(rf, "_click_job_option", lambda *a, **k: False)
    result = rf.select_recommend_job(object(), object(), {}, "数据库应用研发工程师")
    assert result["ok"] is False
    assert "数据库内核实习生" in result["reason"]


def test_ensure_recommend_page_goes_to_encrypt_job_id():
    class Page:
        def __init__(self):
            self.url = "https://www.zhipin.com/web/chat/recommend"
            self.got = []

        def goto(self, url, **_kw):
            self.got.append(url)
            self.url = url

    page = Page()
    rf.ensure_recommend_page(page, encrypt_job_id="EID_APP")
    assert page.got == [
        "https://www.zhipin.com/web/chat/recommend?encryptJobId=EID_APP"
    ]


def test_apply_recommend_filters_records_job(monkeypatch):
    monkeypatch.setattr(rf, "ensure_recommend_page", lambda *a, **k: None)
    monkeypatch.setattr(
        rf, "_iframe_and_frame",
        lambda p: (None, object(), {"x": 0, "y": 0}),
    )
    monkeypatch.setattr(
        rf, "select_recommend_job",
        lambda *a, **k: {
            "ok": True,
            "method": "already",
            "query": "数据库应用研发工程师",
            "visible": "数据库应用研发工程师",
        },
    )
    monkeypatch.setattr(rf, "click_recommend_tab", lambda *a, **k: True)
    rules = SimpleNamespace(
        job_query="数据库应用研发工程师",
        boss_keywords="",
        boss_education=None,
        boss_experience=None,
        boss_age=None,
        boss_salary=None,
    )
    log = rf.apply_recommend_filters(
        object(), rules,
        job_name="数据库应用研发工程师",
        encrypt_job_id="EID_APP",
    )
    assert log["job_selected"]["ok"] is True
    assert any(x.get("filter") == "job" for x in log["applied"])
