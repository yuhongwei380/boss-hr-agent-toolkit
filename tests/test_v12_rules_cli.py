# -*- coding: utf-8 -*-
"""v1.2 start --rules 自动 confirm；fetch --rules 走粗筛 + click-detail。"""
from __future__ import annotations

import json
from collections import namedtuple
from pathlib import Path

import pytest

from boss_hr.application import start_service as ss
from boss_hr.application import fetch_service as fs
from boss_hr.adapters.legacy_runner import LegacyRunResult


def test_start_rules_auto_confirms(tmp_path, monkeypatch):
    monkeypatch.setenv("BOSS_HR_OUTPUT_DIR", str(tmp_path))
    eid = "eid_v12"
    job = "v12岗"
    rid = "2026-08-31_180000"
    process = tmp_path / eid / "runs" / rid / "process"
    process.mkdir(parents=True)
    (tmp_path / eid / "runs" / rid / "run.json").write_text(json.dumps({
        "run_id": rid, "encrypt_job_id": eid, "confirmed": False,
        "steps_done": ["jd"],
    }), encoding="utf-8")
    (process / "job_detail.json").write_text(json.dumps({
        "jobName": job, "encryptJobId": eid, "bodyText": "old",
    }), encoding="utf-8")

    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({
        "job": {"query": eid, "jd": "需要 CATIA 与车架"},
        "coarse_screen": {"education_min": "本科", "years_min": 3},
        "download": {"list_count": 20, "max_details": 5},
    }, ensure_ascii=False), encoding="utf-8")

    calls = []

    def _fake(tool, args, **kwargs):
        calls.append(tool)
        if tool == "boss_jd":
            return LegacyRunResult(
                returncode=0,
                stdout=f"run_id: {rid}\nSaved to {process / 'job_detail.json'}\n",
                stderr="",
            )
        if tool == "confirm_run":
            run_json = tmp_path / eid / "runs" / rid / "run.json"
            data = json.loads(run_json.read_text(encoding="utf-8"))
            data["confirmed"] = True
            data["user_confirmed_at"] = "2026-08-31 18:00:00"
            run_json.write_text(json.dumps(data), encoding="utf-8")
            return LegacyRunResult(returncode=0, stdout="{}", stderr="")
        return LegacyRunResult(returncode=99, stdout="", stderr=tool)

    monkeypatch.setattr("boss_hr.adapters.legacy_runner.run_legacy_cli", _fake)
    monkeypatch.setattr("boss_hr.application.confirm_service.run_legacy_cli", _fake)
    monkeypatch.setattr(ss, "_resolve_recruiter_job",
                        lambda q: {"encryptJobId": eid, "jobName": job})

    res = ss.start_new_run(
        query=eid, job_name=job, encrypt_job_id=eid,
        skip_preflight=True, skip_resolve=False,
        rules_path=str(rules),
    )
    assert res.ok is True
    assert res.status == "ready_to_fetch"
    assert res.next_action == "fetch"
    assert res.data["auto_confirmed"] is True
    assert "confirm_run" in calls
    saved = json.loads((process / "screening_rules.json").read_text(encoding="utf-8"))
    assert saved["coarse_screen"]["education_min"] == "本科"
    jd = json.loads((process / "job_detail.json").read_text(encoding="utf-8"))
    assert jd["user_jd"] == "需要 CATIA 与车架"


def test_fetch_rules_click_detail_and_screen(tmp_path, monkeypatch):
    monkeypatch.setenv("BOSS_HR_OUTPUT_DIR", str(tmp_path))
    eid = "eid_v12f"
    job = "v12岗"
    rid = "2026-08-31_181000"
    process = tmp_path / eid / "runs" / rid / "process"
    process.mkdir(parents=True)
    (tmp_path / eid / "runs" / rid / "run.json").write_text(json.dumps({
        "run_id": rid, "encrypt_job_id": eid, "confirmed": True,
        "steps_done": ["jd"],
    }), encoding="utf-8")

    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({
        "coarse_screen": {
            "education_min": "本科",
            "keywords_exclude": ["销售"],
        },
        "download": {"list_count": 12, "max_details": 4},
    }, ensure_ascii=False), encoding="utf-8")

    calls = []

    def _fake(tool, args, **kwargs):
        calls.append({"tool": tool, "args": list(args)})
        if tool == "recommend_list":
            geeks = [
                {"encryptGeekId": "ok1", "geekCard": {
                    "geekName": "合格", "geekDegree": "本科",
                    "geekWorkYear": "5年", "encryptJobId": eid,
                    "securityId": "s1", "expectPosition": "结构",
                }},
                {"encryptGeekId": "bad1", "geekCard": {
                    "geekName": "销售", "geekDegree": "本科",
                    "geekWorkYear": "5年", "encryptJobId": eid,
                    "securityId": "s2", "expectPosition": "汽车销售",
                }},
            ]
            (process / "recommend_geek_ids.json").write_text(
                json.dumps(geeks, ensure_ascii=False), encoding="utf-8")
            return LegacyRunResult(returncode=0, stdout="", stderr="")
        if tool == "recommend_download":
            (process / "new_resumes.json").write_text(json.dumps([
                {"ok": True, "name": "合格", "detail_description": "做车架",
                 "_meta": {"encrypt_geek_id": "ok1", "opened_by_click": True}},
            ], ensure_ascii=False), encoding="utf-8")
            (process / "failed_resumes.json").write_text("[]", encoding="utf-8")
            return LegacyRunResult(returncode=0, stdout="", stderr="")
        return LegacyRunResult(returncode=99, stdout="", stderr=tool)

    monkeypatch.setattr("boss_hr.adapters.legacy_runner.run_legacy_cli", _fake)
    monkeypatch.setattr(fs, "ensure_browser_ready", lambda **kw: type(
        "R", (), {"ok": True, "error_obj": None, "next_action": None,
                  "remediation": None, "info": {}}
    )())

    res = fs.fetch_candidates(
        job_name=job, encrypt_job_id=eid, run_id=rid, count=10,
        rules_path=str(rules),
    )
    assert res.ok is True
    assert res.data["listed_count"] == 2
    assert res.data["screened_count"] == 1
    assert res.data["rejected_count"] == 1
    assert res.data["downloaded_count"] == 1
    assert res.data["click_detail"] is True
    list_args = calls[0]["args"]
    assert "--rules-file" in list_args
    dl_args = calls[1]["args"]
    assert "--click-detail" in dl_args
    assert "--ids-file" in dl_args
    screened = json.loads((process / "screened_geek_ids.json").read_text(encoding="utf-8"))
    assert len(screened) == 1
    assert screened[0]["encryptGeekId"] == "ok1"
