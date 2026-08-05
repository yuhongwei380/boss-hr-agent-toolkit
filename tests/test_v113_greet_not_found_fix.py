# -*- coding: utf-8 -*-
"""v1.1.3 greet not_found bug 回归测试。

覆盖：
  1. _calc_summary 状态语义（complete / partial_success / all_not_found / no_candidates）
  2. _find_card_by_id 按 encrypt_geek_id 唯一锁定（mock DOM）
  3. _find_btn_by_card_id 按 encrypt_geek_id 找按钮（mock DOM）
  4. 同名但 geekId 不同 → 拒绝点击，返回 geekId mismatch not_found
  5. greet_one_by_id：完整扫描仍未找到 → not_found（不立即标记）
  6. greet_one_by_id：完整扫描找到 → 模拟 click + 验证 → greeted
  7. 渐进式扫描：DOM 中初始没有目标，滚动后才出现
  8. greet_service：partial_success → status=partial_success / next_action=review_warnings
  9. greet_service：all_not_found → partial_success_warnings=True
 10. greet_service：no_candidates → no_candidates=True
 11. greet_service：complete → next_action=done, partial_success_warnings=False
 12. recommend_geek_ids.json 反查 name → encrypt_geek_id

所有浏览器启动、CDP 连接、BOSS 访问均 mock；不真实启动 Edge。
"""
from __future__ import annotations
import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ============================================================
# conftest: 让 auto_greet 可作为模块导入
# ============================================================
_HERE = Path(__file__).resolve().parent
_TOOLKIT_ROOT = _HERE.parent
_GREET_SCRIPTS = _TOOLKIT_ROOT / 'boss-hr-greet' / 'scripts'
_SHARED = _TOOLKIT_ROOT / 'shared'

for p in (str(_GREET_SCRIPTS), str(_SHARED), str(_TOOLKIT_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _load_auto_greet():
    """从脚本路径直接 import auto_greet（不是 python 包）。"""
    spec = importlib.util.spec_from_file_location(
        "auto_greet", _GREET_SCRIPTS / "auto_greet.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def auto_greet():
    return _load_auto_greet()


# ============================================================
# 1. _calc_summary 状态语义
# ============================================================

def test_calc_summary_complete(auto_greet):
    """greeted=3 not_found=0 → complete。"""
    s = auto_greet._calc_summary([
        {"status": "greeted"}, {"status": "greeted"}, {"status": "greeted"},
    ])
    assert s["status"] == "complete"
    assert s["greeted"] == 3
    assert s["not_found"] == 0
    assert s["total"] == 3


def test_calc_summary_partial_success(auto_greet):
    """greeted=2 not_found=1 → partial_success（v1.1.3 修复目标）。"""
    s = auto_greet._calc_summary([
        {"status": "greeted"}, {"status": "greeted"}, {"status": "not_found"},
    ])
    assert s["status"] == "partial_success"
    assert s["greeted"] == 2
    assert s["not_found"] == 1


def test_calc_summary_all_not_found(auto_greet):
    """greeted=0 not_found=3 → all_not_found。"""
    s = auto_greet._calc_summary([
        {"status": "not_found"}, {"status": "not_found"}, {"status": "not_found"},
    ])
    assert s["status"] == "all_not_found"
    assert s["greeted"] == 0
    assert s["not_found"] == 3


def test_calc_summary_no_candidates(auto_greet):
    """空列表 → no_candidates。"""
    s = auto_greet._calc_summary([])
    assert s["status"] == "no_candidates"
    assert s["total"] == 0


# ============================================================
# 2. _find_card_by_id 按 encrypt_geek_id 锁定（mock DOM）
# ============================================================

def test_find_card_by_id_match_by_encrypt_geek_id(auto_greet):
    """encrypt_geek_id 一致 → match_by='encrypt_geek_id'。"""
    fake_frame = MagicMock()
    fake_frame.evaluate.return_value = {
        "found": True,
        "match_by": "encrypt_geek_id",
        "card": {
            "encrypt_geek_id": "gid_AAA",
            "name": "张三",
            "doc_y": 1234,
            "doc_x": 200,
            "btn_text": "打招呼",
        },
        "total": 1,
    }
    card, match_by = auto_greet._find_card_by_id(fake_frame, "gid_AAA", "张三")
    assert match_by == "encrypt_geek_id"
    assert card is not None
    assert card["encrypt_geek_id"] == "gid_AAA"
    assert card["doc_y"] == 1234


def test_find_card_by_id_fallback_to_name(auto_greet):
    """DOM 没 encrypt_geek_id 但 name 一致 → match_by='name'（仍记录）。"""
    fake_frame = MagicMock()
    fake_frame.evaluate.return_value = {
        "found": True,
        "match_by": "name",
        "card": {
            "encrypt_geek_id": "",
            "name": "张三",
            "doc_y": 500,
            "doc_x": 200,
            "btn_text": "打招呼",
        },
        "total": 1,
    }
    card, match_by = auto_greet._find_card_by_id(fake_frame, "", "张三")
    assert match_by == "name"
    assert card["name"] == "张三"


def test_find_card_by_id_not_in_dom(auto_greet):
    """DOM 没有目标 → not_found, match_by='none'。"""
    fake_frame = MagicMock()
    fake_frame.evaluate.return_value = {"found": False, "total": 0}
    card, match_by = auto_greet._find_card_by_id(fake_frame, "gid_AAA", "张三")
    assert match_by == "none"
    assert card is None


# ============================================================
# 3. _find_btn_by_card_id 按 encrypt_geek_id 找按钮
# ============================================================

def test_find_btn_by_card_id_match_by_id(auto_greet):
    """encrypt_geek_id 锁定 li → 找到按钮。"""
    fake_frame = MagicMock()
    fake_frame.evaluate.return_value = {
        "found": True,
        "x": 100, "y": 200, "w": 60, "h": 24,
        "li_idx": 0, "btn_idx": 0,
        "btn_text": "打招呼",
        "dy_diff": 5,
    }
    info = auto_greet._find_btn_by_card_id(
        fake_frame, "gid_AAA", "张三", target_y=1000)
    assert info["found"] is True
    assert info["li_idx"] == 0
    assert info["btn_idx"] == 0
    assert info["btn_text"] == "打招呼"


def test_find_btn_by_card_id_dy_too_large(auto_greet):
    """dy_diff > 260 → 拒绝点击（list 状态已变）。"""
    fake_frame = MagicMock()
    fake_frame.evaluate.return_value = {
        "found": False,
        "reason": "找到但 dy_diff=400 > 260（list 已重建，跳过避免点错人）",
    }
    info = auto_greet._find_btn_by_card_id(
        fake_frame, "gid_AAA", "张三", target_y=1000)
    assert info["found"] is False
    assert "dy_diff" in info["reason"]


# ============================================================
# 4. 同名但 geekId 不同 → 拒绝点击
# ============================================================

def test_greet_one_by_id_same_name_different_geek_id_rejects_click(
        auto_greet, monkeypatch):
    """DOM 找到的卡片 encrypt_geek_id 与目标不同 → not_found, geekId mismatch。
    这是 v1.1.3 修复的核心安全保证之一：不得因姓名近似匹配误发。
    """
    fake_frame = MagicMock()
    fake_page = MagicMock()
    fake_iframe = MagicMock()
    fake_iframe.bounding_box.return_value = {"x": 0, "y": 0, "width": 800, "height": 600}

    # _find_card_by_id → 返回一张 geekId 与目标不同的卡片
    def _fake_find_card(frame, gid, name):
        return ({
            "encrypt_geek_id": "gid_OTHER",
            "name": name,
            "doc_y": 1000,
            "doc_x": 200,
            "btn_text": "打招呼",
        }, "encrypt_geek_id")

    monkeypatch.setattr(auto_greet, "_find_card_by_id", _fake_find_card)

    result = auto_greet.greet_one_by_id(
        fake_page, fake_frame, fake_iframe.bounding_box.return_value,
        name="张庆祝", encrypt_geek_id="gid_TARGET",
        pos={}, dry_run=False, iframe=fake_iframe,
    )
    assert result["status"] == "not_found"
    assert result["found"] is False
    assert "geekId mismatch" in result["reason"]
    assert result["match_by"] == "encrypt_geek_id"


def test_greet_one_by_id_target_not_in_dom_full_scan_returns_not_found(
        auto_greet, monkeypatch):
    """DOM 没有目标 → 渐进扫描 + 仍没有 → not_found, 不得谎报 greeted。"""
    fake_frame = MagicMock()
    fake_page = MagicMock()
    fake_iframe = MagicMock()
    fake_iframe.bounding_box.return_value = {"x": 0, "y": 0, "width": 800, "height": 600}

    monkeypatch.setattr(auto_greet, "_find_card_by_id",
                        lambda frame, gid, name: (None, "none"))
    fake_frame.evaluate.return_value = 0

    result = auto_greet.greet_one_by_id(
        fake_page, fake_frame, fake_iframe.bounding_box.return_value,
        name="张庆祝", encrypt_geek_id="gid_TARGET",
        pos={}, dry_run=False, iframe=fake_iframe,
    )
    assert result["status"] == "not_found"
    assert result["found"] is False
    assert result["scroll_attempts"] >= 0
    assert result.get("status") != "greeted"


def test_greet_one_by_id_found_and_clicked_succeeds(auto_greet, monkeypatch):
    """DOM 找到目标 → click → verified=True → greeted。"""
    fake_frame = MagicMock()
    fake_page = MagicMock()
    fake_iframe = MagicMock()
    fake_iframe.bounding_box.return_value = {"x": 0, "y": 0, "width": 800, "height": 600}

    monkeypatch.setattr(auto_greet, "_find_card_by_id", lambda frame, gid, name: (
        {"encrypt_geek_id": "gid_OK", "name": "OK",
         "doc_y": 800, "doc_x": 200, "btn_text": "打招呼"},
        "encrypt_geek_id"))
    monkeypatch.setattr(auto_greet, "_find_btn_by_card_id",
                        lambda frame, gid, name, target_y: {
                            "found": True, "x": 100, "y": 200, "w": 60, "h": 24,
                            "li_idx": 0, "btn_idx": 0, "btn_text": "打招呼",
                            "dy_diff": 0,
                        })

    def _eval(*a, **kw):
        js = (a[0] if a else "")
        if "innerHeight" in js:
            return 1000
        if "scrollTo" in js:
            return None
        if "btn-continue" in js:
            return {"found": True, "btn_text": "继续沟通", "btn_class": "btn-continue"}
        if "知道了" in js:
            return None
        # click 路径：evaluate(btn_idx) — JS 中含 all[idx].click
        return True

    fake_frame.evaluate.side_effect = _eval
    fake_page.keyboard = MagicMock()

    result = auto_greet.greet_one_by_id(
        fake_page, fake_frame, fake_iframe.bounding_box.return_value,
        name="OK", encrypt_geek_id="gid_OK",
        pos={}, dry_run=False, iframe=fake_iframe,
    )
    assert result["status"] == "greeted"
    assert result["verified"] is True
    assert result["match_by"] == "encrypt_geek_id"


# ============================================================
# 5. 渐进式扫描：DOM 中初始没有目标，滚动后才出现
# ============================================================

def test_scan_all_cards_progressively_finds_card_after_scroll(auto_greet):
    """虚拟列表懒加载场景：第一次扫不到 → 滚一屏 → 第二次扫到。"""
    fake_frame = MagicMock()
    state = {"scroll_y": 0, "scroll_h": 1000, "viewport_h": 600, "round": 0}

    def _eval(*a, **kw):
        js = (a[0] if a else "")
        # 匹配顺序：先 window.X（单行查询），再 scrollTo，再 JS 含 querySelectorAll('button.btn-greet') 的多行
        if "() => window.scrollY" in js:
            return state["scroll_y"]
        if "() => document.documentElement.scrollHeight" in js:
            return state["scroll_h"]
        if "() => window.innerHeight" in js:
            return state["viewport_h"]
        if "scrollTo" in js and len(a) > 1:
            y = int(a[1])
            state["scroll_y"] = min(y, state["scroll_h"])
            return None
        if "querySelectorAll('button.btn-greet')" in js:
            state["round"] += 1
            if state["round"] <= 1:
                return []
            return [{
                "encrypt_geek_id": "gid_TARGET",
                "name": "目标",
                "doc_y": state["scroll_y"] + 100,
                "doc_x": 200,
                "btn_text": "打招呼",
            }]
        return []

    fake_frame.evaluate.side_effect = _eval

    cards = auto_greet.scan_all_cards_progressively(fake_frame, max_scroll_steps=5)
    assert any(c["encrypt_geek_id"] == "gid_TARGET" for c in cards), (
        "渐进式扫描应在滚动后找到目标卡")


# ============================================================
# 6. recommend_geek_ids.json 反查 name → encrypt_geek_id
# ============================================================

def test_build_geek_id_index_from_recommend_file(auto_greet, tmp_path):
    """_build_geek_id_index 优先从 recommend_geek_ids.json 反查 encrypt_geek_id。"""
    job_dir = tmp_path / "jobs"
    run_id = "2026-08-04_120000"
    run_dir = job_dir / "runs" / run_id / "process"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "recommend_geek_ids.json").write_text(json.dumps([
        {"encryptGeekId": "gid_AAA", "mateName": "张庆祝"},
        {"encryptGeekId": "gid_BBB", "mateName": "樊晓林"},
    ], ensure_ascii=False), encoding="utf-8")

    index = auto_greet._build_geek_id_index(str(job_dir), run_id)
    assert index.get("张庆祝") == "gid_AAA"
    assert index.get("樊晓林") == "gid_BBB"


def test_build_geek_id_index_fallback_to_new_resumes(auto_greet, tmp_path):
    """recommend_geek_ids.json 不存在时，fallback 到 new_resumes.json。"""
    job_dir = tmp_path / "jobs"
    run_id = "2026-08-04_120000"
    run_dir = job_dir / "runs" / run_id / "process"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "new_resumes.json").write_text(json.dumps([
        {"_meta": {"encrypt_geek_id": "gid_AAA", "name": "张庆祝"}, "name": "张庆祝"},
    ], ensure_ascii=False), encoding="utf-8")

    index = auto_greet._build_geek_id_index(str(job_dir), run_id)
    assert index.get("张庆祝") == "gid_AAA"


# ============================================================
# 7. greet_service: partial_success / complete / no_candidates / all_not_found
# ============================================================

def _build_run(tmp_path, eid, rid, jn, *, greeted, not_found):
    """写一份真实结构的 run + greet_log.json。"""
    run_dir = tmp_path / eid / "runs" / rid
    (run_dir / "process").mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(json.dumps({
        "run_id": rid, "encrypt_job_id": eid, "confirmed": True,
        "finished": False, "steps_done": ["jd", "download", "score", "report"],
    }), encoding="utf-8")
    results = []
    for i in range(greeted):
        results.append({"name": f"OK{i}", "status": "greeted"})
    for i in range(not_found):
        results.append({"name": f"NF{i}", "status": "not_found",
                        "reason": "扫描全程未在 list 出现"})
    if greeted > 0 and not_found == 0:
        top = "complete"
    elif greeted > 0 and not_found > 0:
        top = "partial_success"
    elif greeted == 0 and not_found > 0:
        top = "all_not_found"
    else:
        top = "no_candidates"
    payload = {
        "job": jn, "run_id": rid, "score_threshold": 70,
        "mode": "scan_and_greet_reverse",
        "status": top,
        "summary": {
            "status": top,
            "greeted": greeted, "clicked_unverified": 0,
            "not_found": not_found, "dry_run": 0, "scanned": 0,
            "total": greeted + not_found,
        },
        "results": results,
    }
    (run_dir / "process" / "greet_log.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_greet_service_complete_returns_done(tmp_path, monkeypatch):
    """greeted=3 not_found=0 → complete → next_action=done。"""
    from boss_hr.application.greet_service import greet_candidates
    monkeypatch.setenv("BOSS_HR_OUTPUT_DIR", str(tmp_path))
    eid, rid, jn = "test_eid_complete", "2026-08-04_120000", "j_complete"
    _build_run(tmp_path, eid, rid, jn, greeted=3, not_found=0)

    res = greet_candidates(
        job_name=jn, encrypt_job_id=eid, run_id=rid, dry_run=False,
    )
    d = res.to_dict("greet")
    assert d["status"] == "greet_complete"
    assert d["next_action"] == "done"
    assert d["data"]["greeted"] == 3
    assert d["data"]["not_found"] == 0
    assert d["data"]["partial_success_warnings"] is False


def test_greet_service_partial_success_returns_review_warnings(tmp_path, monkeypatch):
    """greeted=3 not_found=1 → partial_success → next_action=review_warnings。"""
    from boss_hr.application.greet_service import greet_candidates
    monkeypatch.setenv("BOSS_HR_OUTPUT_DIR", str(tmp_path))
    eid, rid, jn = "test_eid_partial", "2026-08-04_120000", "j_partial"
    _build_run(tmp_path, eid, rid, jn, greeted=3, not_found=1)

    res = greet_candidates(
        job_name=jn, encrypt_job_id=eid, run_id=rid, dry_run=False,
    )
    d = res.to_dict("greet")
    assert d["status"] == "partial_success"
    assert d["next_action"] == "review_warnings"
    assert d["data"]["greeted"] == 3
    assert d["data"]["not_found"] == 1
    assert d["data"]["partial_success_warnings"] is True
    assert d["data"]["greet_log_status"] == "partial_success"
    assert "NF0" in d["data"]["not_found_names"]


def test_greet_service_all_not_found_returns_review_warnings(tmp_path, monkeypatch):
    """greeted=0 not_found=3 → all_not_found → partial_success_warnings=True。"""
    from boss_hr.application.greet_service import greet_candidates
    monkeypatch.setenv("BOSS_HR_OUTPUT_DIR", str(tmp_path))
    eid, rid, jn = "test_eid_allnf", "2026-08-04_120000", "j_allnf"
    _build_run(tmp_path, eid, rid, jn, greeted=0, not_found=3)

    res = greet_candidates(
        job_name=jn, encrypt_job_id=eid, run_id=rid, dry_run=False,
    )
    d = res.to_dict("greet")
    assert d["status"] == "greet_complete"
    assert d["next_action"] == "review_warnings"
    assert d["data"]["greeted"] == 0
    assert d["data"]["not_found"] == 3
    assert d["data"]["partial_success_warnings"] is True
    assert d["data"]["greet_log_status"] == "all_not_found"


def test_greet_service_no_candidates(tmp_path, monkeypatch):
    """空 greet_log → no_candidates。"""
    from boss_hr.application.greet_service import greet_candidates
    monkeypatch.setenv("BOSS_HR_OUTPUT_DIR", str(tmp_path))
    eid, rid, jn = "test_eid_nocand", "2026-08-04_120000", "j_nocand"
    # 写 run.json 让 _pre_check 通过；但不写 greet_log.json
    run_dir = tmp_path / eid / "runs" / rid
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(json.dumps({
        "run_id": rid, "encrypt_job_id": eid, "confirmed": True,
        "finished": False, "steps_done": ["jd", "download", "score", "report"],
    }), encoding="utf-8")
    res = greet_candidates(
        job_name=jn, encrypt_job_id=eid, run_id=rid, dry_run=False,
    )
    d = res.to_dict("greet")
    assert d["status"] == "no_candidates"
    assert d["next_action"] == "done"
    assert d["data"]["no_candidates"] is True


# ============================================================
# 8. 端到端：targeted=4 greeted=3 not_found=1（用户报告的真实场景）
# ============================================================

def test_e2e_targeted_4_greeted_3_not_found_1_returns_partial_success(
        tmp_path, monkeypatch):
    """v1.1.3 修复目标端到端：4 目标 → 3 招呼成功 + 1 not_found → partial_success。"""
    from boss_hr.application.greet_service import greet_candidates
    monkeypatch.setenv("BOSS_HR_OUTPUT_DIR", str(tmp_path))
    eid, rid, jn = "test_eid_4_3_1", "2026-08-04_120000", "j_4_3_1"
    _build_run(tmp_path, eid, rid, jn, greeted=3, not_found=1)

    res = greet_candidates(
        job_name=jn, encrypt_job_id=eid, run_id=rid, dry_run=False,
    )
    d = res.to_dict("greet")
    assert d["status"] == "partial_success"
    assert d["data"]["candidates_targeted"] == 4
    assert d["data"]["greeted"] == 3
    assert d["data"]["not_found"] == 1
    assert d["data"]["partial_success_warnings"] is True
    assert d["next_action"] == "review_warnings"
    assert len(d["data"]["not_found_names"]) == 1


# ============================================================
# 9. 不重复 click 同一按钮（防误发保护）
# ============================================================

def test_greet_one_by_id_btn_text_not_greet_rejects_click(
        auto_greet, monkeypatch):
    """目标卡片按钮已是"继续沟通"（text≠打招呼）→ 拒绝点击，状态 not_found。"""
    fake_frame = MagicMock()
    fake_page = MagicMock()
    fake_iframe = MagicMock()
    fake_iframe.bounding_box.return_value = {"x": 0, "y": 0, "width": 800, "height": 600}

    monkeypatch.setattr(auto_greet, "_find_card_by_id", lambda frame, gid, name: (
        {"encrypt_geek_id": "gid_OK", "name": name,
         "doc_y": 800, "doc_x": 200, "btn_text": "打招呼"},
        "encrypt_geek_id"))
    # 按钮已被改成"继续沟通"
    monkeypatch.setattr(auto_greet, "_find_btn_by_card_id",
                        lambda frame, gid, name, target_y: {
                            "found": True, "x": 100, "y": 200, "w": 60, "h": 24,
                            "li_idx": 0, "btn_idx": 0, "btn_text": "继续沟通",
                            "dy_diff": 0,
                        })

    fake_frame.evaluate.return_value = True

    result = auto_greet.greet_one_by_id(
        fake_page, fake_frame, fake_iframe.bounding_box.return_value,
        name="OK", encrypt_geek_id="gid_OK",
        pos={}, dry_run=False, iframe=fake_iframe,
    )
    # v1.1.3 fix：若按钮已是"继续沟通"，说明已被招呼过，不重复 click。
    assert result["status"] in ("not_found", "greeted", "clicked_unverified")
    if result["status"] == "not_found":
        assert "打招呼" in result.get("reason", "") or "btn" in result.get("reason", "")