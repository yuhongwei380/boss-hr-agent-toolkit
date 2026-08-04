# -*- coding: utf-8 -*-
"""boss_hr.application.start_service — start 命令业务逻辑（v1.1.2）。

职责：
  - 校验 query（必填）、--job-name（可选）、--encrypt-job-id（可选一致性校验）
  - **不**接受 --run-id（每次 start 创建新 run）
  - **通过 BOSS 实时岗位目录解析 query**（不读 jobs.json / 旧 run / 历史 HTML）
  - 启动前调 ensure_browser_ready（v1.1.2 自动启动专用 Edge）
    - 缺 CDP → 自动启动专用 Edge + 等登录
    - 未登录 → waiting_user_login（不创建 run）
    - 缺 CDP 且 --no-auto-launch → CDP_NOT_RUNNING
    - BOSS_LOGIN_REQUIRED 但已登录成功 → 继续
  - 把实时解析的 encrypt_job_id 传给 boss_jd 业务入口
  - 解析 boss_jd stdout 抽 run_id
  - 返回 waiting_user_confirmation
"""
from __future__ import annotations
import json
import os
import re
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
    legacy_error, try_extract_blocked_message,
)
from boss_hr.adapters.browser_environment import ensure_browser_ready


_RUN_ID_LINE_RE = re.compile(
    r"run_id:\s*([0-9]{4}-\d{2}-\d{2}_\d{6,8}(?:_[0-9A-Za-z]+)?)"
)


def _extract_run_id_from_stdout(stdout: str) -> Optional[str]:
    payload = try_extract_blocked_message(stdout)
    if payload and "run_id" in payload:
        rid = payload["run_id"]
        if isinstance(rid, str) and rid:
            return rid
    m = _RUN_ID_LINE_RE.search(stdout)
    if m:
        return m.group(1).rstrip("（(").rstrip()
    return None


def _extract_job_detail_file_from_stdout(stdout: str) -> Optional[str]:
    m = re.search(r"Saved to\s+(\S+\.json)", stdout)
    if m:
        return m.group(1)
    return None


def _resolve_recruiter_job(query: str) -> dict | list | None:
    """通过 shared.recruiter_job_catalog 实时解析岗位。

    显式拒绝：
      - 读取 jobs.json
      - 读取历史 run/job_detail.json
      - 读取 state 文件
      - 读取历史 HTML 报告
      - 扫描最近 run
      - 读取 current_run.json

    Returns:
        dict 单匹配 — {encryptJobId, jobName, ...}
        list  多匹配 — [{...}, {...}]
        None  解析失败
    """
    from shared.recruiter_job_catalog import resolve_recruiter_job
    return resolve_recruiter_job(query)


def _build_preflight_error(preflight) -> CommandResult:
    """PreflightResult.ok=False → 统一结构的 error CommandResult。"""
    err = preflight.error_obj
    return error(
        error_obj=err,
        exit_code=ExitCode.GENERIC,
        next_action=preflight.next_action,
        remediation=preflight.remediation,
    )


def _job_not_found_error(query: str) -> CommandResult:
    return error(
        error_obj=UnifiedError(
            code=ErrorCode.JOB_NOT_FOUND,
            message=f"BOSS 实时岗位目录中找不到 '{query}'。请提供精确的岗位名称、jobId 或 encryptJobId。",
            recoverable=True,
        ),
        exit_code=ExitCode.GENERIC,
        next_action="retry_with_exact_query",
        remediation={
            "instructions": [
                "提供更精确的 query：完整岗位名 / jobId 数字 / 完整 encryptJobId",
                "或运行 `boss-hr doctor` 确认 BOSS 招聘者登录态有效",
            ],
        },
    )


def _job_ambiguous_error(query: str, candidates: list) -> CommandResult:
    items = []
    for c in candidates:
        if not isinstance(c, dict):
            continue
        items.append({
            "job_name": c.get("jobName") or c.get("job_name"),
            "encrypt_job_id": c.get("encryptJobId") or c.get("encrypt_job_id"),
            "job_id": c.get("jobId") or c.get("job_id"),
        })
    return error(
        error_obj=UnifiedError(
            code=ErrorCode.JOB_AMBIGUOUS,
            message=f"存在多个与 '{query}' 匹配的岗位；请用 encryptJobId 精确指定。",
            recoverable=True,
        ),
        exit_code=ExitCode.GENERIC,
        next_action="rerun_start_with_job_id",
        remediation={
            "instructions": [
                "从下方候选列表选择一个 encryptJobId，重新跑 boss-hr start",
                "或在 BOSS 网页找到精确 encryptJobId 后再调用",
            ],
        },
        data={"candidates": items},
    )


def _job_id_mismatch_error(query_eid: str, resolved_eid: str,
                            job_name: str) -> CommandResult:
    return error(
        error_obj=UnifiedError(
            code=ErrorCode.JOB_ID_MISMATCH,
            message=(
                f"--encrypt-job-id 与 BOSS 实时解析结果不一致："
                f"传入={query_eid!r} 实时={resolved_eid!r}"
            ),
            recoverable=True,
        ),
        exit_code=ExitCode.GENERIC,
        next_action="retry_without_arg_or_with_correct_eid",
        remediation={
            "instructions": [
                "去掉 --encrypt-job-id，让 start 完全依赖实时解析",
                "或传入与 BOSS 后端一致的 encryptJobId",
            ],
        },
    )


def start_new_run(*, query: Optional[str], job_name: Optional[str],
                  encrypt_job_id: Optional[str],
                  skip_preflight: bool = False,
                  skip_resolve: bool = False,
                  auto_launch_browser: bool = True,
                  login_wait_seconds: int = 20) -> CommandResult:
    """start 命令业务实现（v1.1.2 自动启动 Edge）。

    流程：
      1) query 必填
      2) ensure_browser_ready（start 必须连 BOSS 后端拉岗位列表）
         auto_launch_browser=True（默认）：缺 CDP → 自动启动专用 Edge
         未登录 → 自动打开登录页 + 短轮询 → 登录后继续；
         超时未登录 → waiting_user_login（不创建 run）
         auto_launch_browser=False（--no-auto-launch）：缺 CDP → CDP_NOT_RUNNING
      3) _resolve_recruiter_job(query) 实时解析（可被 skip_resolve 旁路）
         → 0 匹配 → JOB_NOT_FOUND
         → 多匹配 → JOB_AMBIGUOUS（带 candidates）
         → 1 匹配 → 取 encryptJobId + jobName
      4) --encrypt-job-id 一致性校验（不一致 → JOB_ID_MISMATCH）
      5) 调 cli_runner.run_python_cli('boss_jd', ...)
      6) 解析 stdout 抽 run_id
      7) 返回 waiting_user_confirmation
    """
    if not query:
        return error(
            error_obj=UnifiedError(
                code=ErrorCode.INTERNAL,
                message="缺少 query（位置参数）。请提供岗位名称、jobId 或 encryptJobId。",
                recoverable=True,
            ),
            exit_code=ExitCode.MISSING_RUN_ID,
            next_action="provide_query",
            remediation={
                "instructions": [
                    "提供岗位名称、jobId 数字 或 完整 encryptJobId 作为位置参数",
                    "示例: boss-hr start '线控底盘制动、转向工程师'",
                ],
            },
        )

    # 浏览器 + 登录态（v1.1.2：自动启动 Edge + 登录页轮询）
    if not skip_preflight:
        ready = ensure_browser_ready(
            auto_launch=auto_launch_browser,
            login_wait_seconds=login_wait_seconds,
        )
        if not ready.ok:
            # 仍可能用户未登录且超时 → waiting_user_login（不是错误）
            if ready.error_obj and ready.error_obj.code == ErrorCode.BOSS_LOGIN_REQUIRED:
                _info = ready.info or {}
                _opened = bool(_info.get("login_page_opened", False))
                if _opened:
                    _msg = (
                        "已为你打开专用 Edge，请在浏览器中扫码登录 BOSS 招聘者后台。"
                        "完成后回复“好了”，我会继续当前任务。"
                    )
                else:
                    # 登录页未自动打开：明确告诉用户手工打开
                    _err = _info.get("login_page_open_error") or ""
                    _suffix = f"（{_err}）" if _err else ""
                    _msg = (
                        "已为你启动专用 Edge，但未能自动打开 BOSS 招聘者登录页"
                        f"{_suffix}。"
                        "请在已打开的专用 Edge 窗口中手动打开 "
                        "https://www.zhipin.com/web/chat/recommend 登录。"
                        "完成后回复“好了”，我会继续当前任务。"
                    )
                return ok(
                    status="waiting_user_login",
                    message=_msg,
                    data={
                        "browser_auto_launched": _info.get("browser_auto_launched", False),
                        "login_page_opened": _opened,
                        "login_page_open_error": _info.get("login_page_open_error", ""),
                        "login_wait_seconds": _info.get("login_wait_seconds", 0),
                    },
                    next_action="retry_same_command",
                )
            # 真正环境错误（Edge 不存在 / CDP 不可达 / auto_launch=False）
            return error(
                error_obj=ready.error_obj,
                exit_code=ExitCode.GENERIC,
                next_action=ready.next_action,
                remediation=ready.remediation,
            )

    # 实时解析
    if not skip_resolve:
        resolved = _resolve_recruiter_job(query)
    else:
        # skip_resolve=True：直接把 query 当作 encryptJobId，name 用 --job-name 或 query
        resolved = {"encryptJobId": query, "jobName": job_name or query,
                    "jobId": None, "address": "", "salaryDesc": ""}
    if resolved is None:
        return _job_not_found_error(query)
    if isinstance(resolved, list):
        return _job_ambiguous_error(query, resolved)

    # 单匹配
    resolved_eid = resolved.get("encryptJobId") or resolved.get("encrypt_job_id")
    resolved_name = resolved.get("jobName") or resolved.get("job_name")
    if not resolved_eid:
        return _job_not_found_error(query)

    # --encrypt-job-id 一致性校验（可选）
    if encrypt_job_id and encrypt_job_id != resolved_eid:
        return _job_id_mismatch_error(encrypt_job_id, resolved_eid,
                                      resolved_name or job_name or "")

    # 优先用实时解析的 name（用户传的 --job-name 仅作为提示）
    final_job_name = job_name or resolved_name or ""

    # 调业务脚本
    from boss_hr.adapters import legacy_runner

    args_list = [
        query,
        "--job-name", final_job_name,
        "--encrypt-job-id", resolved_eid,
    ]
    result = legacy_runner.run_legacy_cli(
        "boss_jd",
        args_list,
        timeout=120,
    )

    if result.returncode != 0:
        better_msg = try_extract_blocked_message(result.stdout)
        unified = legacy_error(result)
        if better_msg:
            unified = UnifiedError(
                code=unified.code, message=better_msg,
                subprocess_returncode=unified.subprocess_returncode,
            )
        return error(
            error_obj=unified,
            encrypt_job_id=resolved_eid,
            job_name=final_job_name,
            exit_code=result.returncode,
        )

    run_id = _extract_run_id_from_stdout(result.stdout or "")
    if not run_id:
        return error(
            error_obj=UnifiedError(
                code=ErrorCode.INTERNAL,
                message="boss_jd 退出 0 但 stdout 无 run_id（无法可靠解析结构化输出）",
            ),
            encrypt_job_id=resolved_eid,
            job_name=final_job_name,
            exit_code=ExitCode.INTERNAL,
        )

    job_detail_file = _extract_job_detail_file_from_stdout(result.stdout or "")

    return ok(
        status="waiting_user_confirmation",
        run_id=run_id,
        encrypt_job_id=resolved_eid,
        job_name=final_job_name,
        data={
            "job_detail_file": job_detail_file,
            "confirmed": False,
            "resolved_from": "live_boss_catalog",
        },
        next_action="confirm",
    )


__all__ = ["start_new_run"]