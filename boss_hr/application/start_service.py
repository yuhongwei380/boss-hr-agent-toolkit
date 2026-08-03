# -*- coding: utf-8 -*-
"""boss_hr.application.start_service — start 命令业务逻辑（C1）。

职责：
  - 校验 query / --job-name / --encrypt-job-id 显式提供
  - 调 cli_runner.run_python_cli('boss_jd', ...) 拿完整业务
  - 解析 boss_jd stdout 抽 run_id（多段混合输出，优先最后 1 个 JSON）
  - 校验 3 处 run_id 一致性
  - 返回 waiting_user_confirmation

不直接调 patchright / 不创建 run / 不写 job_detail.json / 不写 jobs.json
（全部由 boss_jd + RunOrchestrator + JobRegistry 负责）。

start 不接受 --run-id：每次 start 必须创建新 run，不复用旧 run。
公开参数：boss-hr start <query> --job-name ... --encrypt-job-id ...
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


# boss_jd stdout 三处出现 run_id（已验证）：
#   1) "run_id: <id>（orchestrator 创建）"  ← 含中文括号！
#   2) 末尾 JSON 的 "run_id": "<id>"
#   3) "run_id: <id>"（Saved to 之后）
#
# 严格 run_id 格式：YYYY-MM-DD_HHMMSS[_<suffix>]（十进制 / 十六进制 / base32），
# 末位是数字 / 字母 / 减号 / 下划线（不是中文括号）。
_RUN_ID_LINE_RE = re.compile(r"run_id:\s*([0-9]{4}-\d{2}-\d{2}_\d{6,8}(?:_[0-9A-Za-z]+)?)")


def _extract_run_id_from_stdout(stdout: str) -> Optional[str]:
    """从 boss_jd stdout 抽 run_id（3 处应一致；返回第一个合法匹配）。

    优先从末尾 JSON 拿；拿不到退回 regex 抓第一个 `run_id:` 行。
    """
    # 末尾 JSON 优先
    payload = try_extract_blocked_message(stdout)
    if payload and "run_id" in payload:
        rid = payload["run_id"]
        if isinstance(rid, str) and rid:
            return rid
    # 兜底：regex 抓第一个 `run_id: <id>` 行
    m = _RUN_ID_LINE_RE.search(stdout)
    if m:
        # 截掉末尾非 run_id 字符（如中文括号）
        return m.group(1).rstrip("（(").rstrip()
    return None


def _extract_job_detail_file_from_stdout(stdout: str) -> Optional[str]:
    """从 `Saved to <path>` 行抽 job_detail.json 路径。"""
    m = re.search(r"Saved to\s+(\S+\.json)", stdout)
    if m:
        return m.group(1)
    return None


def start_new_run(*, query: Optional[str], job_name: Optional[str],
                  encrypt_job_id: Optional[str]) -> CommandResult:
    """start 命令业务实现。

    流程：
      1) 校验 query / job_name / encrypt_job_id 必填（业务层防御）
      2) 调 cli_runner.run_python_cli('boss_jd', [query, --job-name, --encrypt-job-id], ...)
      3) 解析 stdout 抽 run_id + job_detail_file
      4) 校验 run_id 非空
      5) 返回 waiting_user_confirmation
    """
    if not query:
        return error(
            error_obj=UnifiedError(code=ErrorCode.INTERNAL,
                                    message="缺少 query（位置参数）"),
            exit_code=ExitCode.MISSING_RUN_ID,  # argparse rc=2
        )
    if not job_name:
        return error(
            error_obj=UnifiedError(code=ErrorCode.INTERNAL,
                                    message="缺少 --job-name"),
            exit_code=ExitCode.MISSING_RUN_ID,
        )
    if not encrypt_job_id:
        return error(
            error_obj=UnifiedError(code=ErrorCode.MISSING_ENCRYPT_JOB_ID,
                                    message="缺少 --encrypt-job-id（亦可设 env BOSS_HR_ENCRYPT_JOB_ID）"),
            exit_code=ExitCode.GENERIC,  # 1
        )

    # 不在 CLI 层强加 --run-id；让 boss_jd 自动 create_new_run
    from boss_hr.adapters import legacy_runner

    args_list = [
        query,
        "--job-name", job_name,
        "--encrypt-job-id", encrypt_job_id,
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
        # 子脚本 rc 可能不在 ExitCode enum 里（透传语义保留）；用 int 不用 ExitCode
        return error(
            error_obj=unified,
            job_name=job_name,
            exit_code=result.returncode,  # int 透传（CommandResult.exit_code: int）
        )

    # 解析 stdout
    run_id = _extract_run_id_from_stdout(result.stdout or "")
    if not run_id:
        return error(
            error_obj=UnifiedError(
                code=ErrorCode.INTERNAL,
                message="boss_jd 退出 0 但 stdout 无 run_id（无法可靠解析结构化输出）",
            ),
            job_name=job_name,
            exit_code=ExitCode.INTERNAL,
        )

    job_detail_file = _extract_job_detail_file_from_stdout(result.stdout or "")

    return ok(
        status="waiting_user_confirmation",
        run_id=run_id,
        encrypt_job_id=encrypt_job_id,
        job_name=job_name,
        data={
            "job_detail_file": job_detail_file,
            "confirmed": False,
        },
        next_action="confirm",
    )


__all__ = ["start_new_run"]
