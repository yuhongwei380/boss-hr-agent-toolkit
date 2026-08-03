# -*- coding: utf-8 -*-
"""boss_hr.application.scoring_service — score 命令业务逻辑（C1）。

职责：
  - 校验 run 存在 + confirmed=true + new_resumes.json 存在
  - manifest 不存在时调 prepare_scoring_inputs.py 一次
  - 从 manifest 清单 + outputs/ 文件状态 找下一位需要评分的候选人
  - 返回 {candidate_id, name, input_file, output_file, remaining}
  - 不读完整 new_resumes.json（只 stat）
  - 不调 collect_llm_scores / score_resumes（留给 C2）

C2 阶段（finalize_when_ready）：
  - 所有 output 都齐 → 调 collect → 调 score_resumes
  - 有 invalid → 报告 invalid 候选人
  - 已有 screening_results.json → 幂等返回 scoring_complete
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve().parent
_BOSS_HR = _HERE.parent
_TOOLKIT_ROOT = _BOSS_HR.parent
sys.path.insert(0, str(_TOOLKIT_ROOT))
sys.path.insert(0, str(_TOOLKIT_ROOT / "shared"))

from boss_hr.contracts.results import CommandResult, ok, error
from boss_hr.contracts.errors import ExitCode, ErrorCode, UnifiedError
from boss_hr.adapters.legacy_runner import (
    run_legacy_cli, legacy_error, try_extract_blocked_message,
)


def _resolve_encrypt_job_id(cli_value: Optional[str]) -> Optional[str]:
    if cli_value:
        return cli_value
    return os.environ.get("BOSS_HR_ENCRYPT_JOB_ID")


def _require_run(job_name: str, eid: str, run_id: str) -> tuple[int, Optional[str]]:
    """校验 run 存在 + confirmed + new_resumes 存在；都通过返回 0，否则返回 (exit_code, msg)。

    返回 (exit_code, None/error_message)。exit_code=0 表示 OK。
    """
    from shared.run_orchestrator import (
        RunOrchestrator,
        EXIT_CODE_RUN_NOT_FOUND,
        EXIT_CODE_RUN_JOB_MISMATCH,
    )
    from shared.output_manager import JobOutputManager

    orch = RunOrchestrator(job_name, encrypt_job_id=eid)
    try:
        orch.bind_existing_run(run_id)
    except FileNotFoundError:
        return EXIT_CODE_RUN_NOT_FOUND, f"run_id={run_id} 在岗位目录下不存在"
    except RuntimeError as e:
        return EXIT_CODE_RUN_JOB_MISMATCH, str(e)

    out = JobOutputManager(job_name, encrypt_job_id=eid, run_id=run_id, lazy=True)
    run_json_path = os.path.join(out.runs_dir, run_id, "run.json")
    if os.path.exists(run_json_path):
        try:
            with open(run_json_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            if not state.get("confirmed"):
                return 20, f"run_id={run_id} 尚未用户确认，禁止执行 Step 3（评分）。请先跑 confirm"
        except Exception:
            pass

    # new_resumes.json 必须存在
    new_resumes_path = os.path.join(out.runs_dir, run_id, "process", "new_resumes.json")
    if not os.path.isfile(new_resumes_path):
        return 26, f"当前 run 缺少 process/new_resumes.json：{new_resumes_path}。请先跑 fetch"

    return 0, None


def _read_manifest(scoring_dir: str) -> Optional[dict]:
    path = os.path.join(scoring_dir, "manifest.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _ensure_manifest(job_name: str, eid: str, run_id: str,
                     scoring_dir: str) -> tuple[bool, Optional[dict]]:
    """manifest 不存在时调 prepare_scoring_inputs.py；返回 (ok, manifest)。

    ok=True 时 manifest 非 None；ok=False 时 manifest=None（失败）。
    """
    manifest = _read_manifest(scoring_dir)
    if manifest is not None:
        return True, manifest

    result = run_legacy_cli(
        "prepare_scoring_inputs",
        [
            "--job-name", job_name,
            "--encrypt-job-id", eid,
            "--run-id", run_id,
        ],
        timeout=60,
    )
    if result.returncode != 0:
        return False, None
    manifest = _read_manifest(scoring_dir)
    if manifest is None:
        return False, None
    return True, manifest


def _find_next(manifest: dict, scoring_dir: str) -> Optional[dict]:
    """从 manifest 清单 + output 文件状态 找下一位候选人。

    关键：不能只看 manifest entry.status == "pending"；
    若 output 文件已存在，跳过；只看 output 不存在（无论 manifest status）。
    """
    candidates = manifest.get("candidates", [])
    for entry in candidates:
        geek_id = entry.get("geek_id")
        if not geek_id:
            continue
        output_rel = entry.get("output_path")
        if not output_rel:
            continue
        output_abs = os.path.normpath(os.path.join(scoring_dir, output_rel))
        if os.path.isfile(output_abs):
            continue  # 已评分
        return {
            "geek_id": geek_id,
            "name": entry.get("name", ""),
            "input_path": entry.get("input_path"),
            "output_path": output_rel,
            "output_abs": output_abs,
        }
    return None


def _count_remaining(manifest: dict, scoring_dir: str) -> int:
    """还有几位候选人 output 文件不存在（即 remaining = 待评分数）。"""
    candidates = manifest.get("candidates", [])
    n = 0
    for entry in candidates:
        output_rel = entry.get("output_path")
        if not output_rel:
            continue
        output_abs = os.path.normpath(os.path.join(scoring_dir, output_rel))
        if not os.path.isfile(output_abs):
            n += 1
    return n


def find_next_candidate(*, job_name: str, encrypt_job_id: Optional[str],
                         run_id: Optional[str]) -> CommandResult:
    """C1：找下一位待评分的候选人，返回 (candidate_id, name, input_file, output_file, remaining)。

    状态机：waiting_llm（返回该候选人）/ 没有剩余候选人 → 也返回 waiting_llm
    且 candidate_id=null（理论上不会发生：剩余=0 时该走 finalize，但 C1 不实现）。
    """
    eid = _resolve_encrypt_job_id(encrypt_job_id)
    if not eid:
        return error(
            error_obj=UnifiedError(
                code=ErrorCode.MISSING_ENCRYPT_JOB_ID,
                message="缺少 encrypt_job_id",
            ),
            run_id=run_id, exit_code=ExitCode.GENERIC,
        )
    if not run_id:
        return error(
            error_obj=UnifiedError(
                code=ErrorCode.MISSING_RUN_ID,
                message="缺少 --run-id",
            ),
            exit_code=ExitCode.MISSING_RUN_ID,
        )

    rc, msg = _require_run(job_name, eid, run_id)
    if rc != 0:
        # 区分 exit code → UnifiedError code
        if rc == 23:
            err_code = ErrorCode.RUN_NOT_FOUND
        elif rc == 24:
            err_code = ErrorCode.JOB_MISMATCH
        elif rc == 20:
            err_code = ErrorCode.AWAITING_CONFIRMATION
        elif rc == 26:
            err_code = ErrorCode.INTERNAL
        else:
            err_code = ErrorCode.INTERNAL
        return error(
            error_obj=UnifiedError(code=err_code, message=msg),
            run_id=run_id, encrypt_job_id=eid, job_name=job_name,
            exit_code=ExitCode(rc),
        )

    # 定位 scoring dir
    from shared.output_manager import JobOutputManager
    out = JobOutputManager(job_name, encrypt_job_id=eid, run_id=run_id, lazy=True)
    process_dir = os.path.join(out.runs_dir, run_id, "process")
    scoring_dir = os.path.join(process_dir, "scoring")

    # manifest 不存在时跑 prepare
    ok_, manifest = _ensure_manifest(job_name, eid, run_id, scoring_dir)
    if not ok_ or manifest is None:
        return error(
            error_obj=UnifiedError(
                code=ErrorCode.INTERNAL,
                message="manifest.json 仍不存在（prepare 失败或 new_resumes 为空）",
            ),
            run_id=run_id, encrypt_job_id=eid, job_name=job_name,
            exit_code=ExitCode(26),
        )

    next_cand = _find_next(manifest, scoring_dir)
    if next_cand is None:
        # 没有待评分候选人：C1 阶段不实现 finalize，提示跑第二次会触发 C2
        return ok(
            status="waiting_llm",
            run_id=run_id, encrypt_job_id=eid, job_name=job_name,
            data={
                "candidate_id": None,
                "name": None,
                "input_file": None,
                "output_file": None,
                "remaining": 0,
                "note": "all outputs ready; run again to trigger finalize",
            },
            next_action="score_candidate_then_repeat",
        )

    remaining = _count_remaining(manifest, scoring_dir)
    return ok(
        status="waiting_llm",
        run_id=run_id, encrypt_job_id=eid, job_name=job_name,
        data={
            "candidate_id": next_cand["geek_id"],
            "name": next_cand["name"],
            "input_file": os.path.normpath(os.path.join(scoring_dir, next_cand["input_path"]))
                if next_cand.get("input_path") else None,
            "output_file": next_cand["output_abs"],
            "remaining": remaining,
        },
        next_action="score_candidate_then_repeat",
    )


__all__ = ["find_next_candidate"]
