"""boss_hr.contracts.results — 统一 CommandResult。

每个命令的 handler 返回 CommandResult（或更具体的子类），
cli.py 负责 to_dict() + emit JSON + exit code。
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

from .errors import ExitCode, ErrorCode, UnifiedError


@dataclass
class CommandResult:
    """命令执行结果（统一 schema）。

    成功：
      ok=True, status="<阶段名>", run_id, data={...}, next_action="<下一动作>"
    失败：
      ok=False, error=UnifiedError(...)（含 code/message/可选 subprocess_returncode）

    命令名（status / report / confirm ...）由调用方在 emit 时加上，不放进 result。
    """
    ok: bool
    status: str = ""
    run_id: Optional[str] = None
    encrypt_job_id: Optional[str] = None
    job_name: Optional[str] = None
    data: dict = field(default_factory=dict)
    next_action: Optional[str] = None
    message: Optional[str] = None
    exit_code: ExitCode = ExitCode.OK
    error: Optional[UnifiedError] = None

    def to_dict(self, command: str) -> dict:
        """序列化 JSON（去掉 exit_code；status 命令 schema 略不同）。"""
        if self.ok:
            payload: dict = {
                "ok": True,
                "command": command,
                "status": self.status,
                "run_id": self.run_id,
            }
            if self.encrypt_job_id is not None:
                payload["encrypt_job_id"] = self.encrypt_job_id
            if self.job_name is not None:
                payload["job_name"] = self.job_name
            if self.data:
                payload["data"] = self.data
            if self.next_action is not None:
                payload["next_action"] = self.next_action
            if self.message is not None:
                payload["message"] = self.message
            return payload
        else:
            payload = {
                "ok": False,
                "command": command,
                "run_id": self.run_id,
            }
            if self.encrypt_job_id is not None:
                payload["encrypt_job_id"] = self.encrypt_job_id
            if self.error is not None:
                payload["error"] = self.error.to_dict()
            else:
                payload["error"] = {"code": ErrorCode.INTERNAL.value,
                                    "message": self.message or "未知错误"}
            return payload


def ok(*, status: str, run_id: str | None = None,
       encrypt_job_id: str | None = None, job_name: str | None = None,
       data: dict | None = None, next_action: str | None = None,
       message: str | None = None) -> CommandResult:
    return CommandResult(
        ok=True,
        status=status,
        run_id=run_id,
        encrypt_job_id=encrypt_job_id,
        job_name=job_name,
        data=data or {},
        next_action=next_action,
        message=message,
        exit_code=ExitCode.OK,
    )


def error(*, error_obj: UnifiedError, run_id: str | None = None,
          encrypt_job_id: str | None = None, job_name: str | None = None,
          exit_code: ExitCode | None = None) -> CommandResult:
    if exit_code is None:
        # 简单映射（UnifiedError.code → ExitCode）
        from .errors import _SUBPROCESS_RC_MAP
        # 默认按 INTERNAL
        exit_code = ExitCode.INTERNAL
        for rc, (ec, _ec, _m) in _SUBPROCESS_RC_MAP.items():
            if ec is not ExitCode.OK and _ec is error_obj.code:
                exit_code = ec
                break
    return CommandResult(
        ok=False,
        run_id=run_id,
        encrypt_job_id=encrypt_job_id,
        job_name=job_name,
        exit_code=exit_code,
        error=error_obj,
    )


__all__ = ["CommandResult", "ok", "error"]
