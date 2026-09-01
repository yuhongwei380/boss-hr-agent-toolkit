# -*- coding: utf-8 -*-
"""打招呼暂时关闭：不启浏览器、不调 auto_greet。"""
from __future__ import annotations

from boss_hr.application.greet_service import greet_candidates


def test_greet_disabled_skips_browser_and_legacy(monkeypatch):
    monkeypatch.setenv("BOSS_HR_GREET_ENABLED", "0")

    def _boom(*_a, **_k):
        raise AssertionError("禁用状态下不得启动浏览器")

    def _boom_legacy(*_a, **_k):
        raise AssertionError("禁用状态下不得调用 auto_greet")

    monkeypatch.setattr(
        "boss_hr.application.greet_service.ensure_browser_ready", _boom,
    )
    monkeypatch.setattr(
        "boss_hr.adapters.legacy_runner.run_legacy_cli", _boom_legacy,
    )

    res = greet_candidates(
        job_name="测试岗",
        encrypt_job_id="eid_x",
        run_id="rid_x",
    )
    payload = res.to_dict("greet")
    assert payload["ok"] is True
    assert payload["status"] == "greet_disabled"
    assert payload["next_action"] == "done"
    assert payload["data"]["disabled"] is True
    assert payload["data"]["greeted"] == 0
    assert res.exit_code == 0
