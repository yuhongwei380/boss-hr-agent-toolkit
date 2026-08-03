# -*- coding: utf-8 -*-
"""tests/cli/conftest.py — fetch 专用 mock fixture（autouse=True）。

autouse mock 真实写真实文件：fetch_service 调 legacy_runner 后会读
process/{recommend_geek_ids.json, new_resumes.json, failed_resumes.json}，
mock 必须写真实文件 fetch 才能正确算 listed/downloaded/failed。
"""
from __future__ import annotations
import json
import os
import re
from pathlib import Path
from typing import Optional

import pytest


class _FakeLegacyResult:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _parse_fetch_args(args: list) -> dict:
    """从 recommend_list / recommend_download 的 args 提 eid/rid。"""
    out = {}
    for i, a in enumerate(args):
        if a in ("--encrypt-job-id", "-eid") and i + 1 < len(args):
            out["eid"] = args[i + 1]
        elif a in ("--run-id",) and i + 1 < len(args):
            out["rid"] = args[i + 1]
        elif a in ("--job-name",) and i + 1 < len(args):
            out["job_name"] = args[i + 1]
    return out


def _process_dir(workspace_root: Path, eid: str, rid: str) -> Path:
    return workspace_root / eid / "runs" / rid / "process"


def _write_fake_outputs(workspace_root: Path, eid: str, rid: str) -> Path:
    """写真实 list + download 产物（让 fetch_service 能正确算统计）。"""
    process_dir = _process_dir(workspace_root, eid, rid)
    process_dir.mkdir(parents=True, exist_ok=True)
    # list 产物
    list_path = process_dir / "recommend_geek_ids.json"
    list_path.write_text(json.dumps([
        {"encryptGeekId": f"gid_a_{i:03d}", "name": f"姓名{i}",
         "geekCard": {"encryptJobId": eid, "securityId": f"sec_{i}"}}
        for i in range(5)
    ], ensure_ascii=False), encoding="utf-8")
    # download 产物：3 成功 + 2 失败
    (process_dir / "new_resumes.json").write_text(json.dumps([
        {"ok": True, "name": f"姓名{i}", "_meta": {"encrypt_geek_id": f"gid_a_{i:03d}"}}
        for i in range(3)
    ], ensure_ascii=False), encoding="utf-8")
    (process_dir / "failed_resumes.json").write_text(json.dumps([
        {"ok": False, "name": f"姓名{i}", "reason": "已达查看上限",
         "encrypt_geek_id": f"gid_a_{i:03d}"}
        for i in range(3, 5)
    ], ensure_ascii=False), encoding="utf-8")
    return process_dir


@pytest.fixture(autouse=True)
def _auto_mock_legacy_runner(monkeypatch, tmp_path):
    """autouse：mock run_legacy_cli（按 eid/rid 写真实文件）。

    所有 tests/cli/test_fetch.py 的测试自动接收；返回 {tmp_path} 让测试用。
    """
    def _smart_fake(tool, args, *, timeout=60, **kwargs):
        parsed = _parse_fetch_args(list(args))
        eid = parsed.get("eid")
        rid = parsed.get("rid")
        if not eid or not rid:
            return _FakeLegacyResult(returncode=99)
        process_dir = _process_dir(tmp_path, eid, rid)
        if tool == "recommend_list":
            # 写真实 list 产物
            _write_fake_outputs(tmp_path, eid, rid)
            return _FakeLegacyResult(returncode=0)
        if tool == "recommend_download":
            # 需要 list 产物先在
            if not process_dir.exists():
                return _FakeLegacyResult(returncode=26)
            if not (process_dir / "recommend_geek_ids.json").exists():
                # 没 list 产物，写真实
                _write_fake_outputs(tmp_path, eid, rid)
            return _FakeLegacyResult(returncode=0)
        return _FakeLegacyResult(returncode=99)

    monkeypatch.setattr("boss_hr.adapters.legacy_runner.run_legacy_cli", _smart_fake)
    return tmp_path
