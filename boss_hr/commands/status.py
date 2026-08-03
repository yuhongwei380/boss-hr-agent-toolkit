"""boss_hr.commands.status — status 命令处理。

注意：status 命令的 schema 与通用 ok/error schema 不一致（保留第一轮
固定 schema）。本命令返回 (exit_code, payload_dict)；cli.py 直接 emit。
"""
from __future__ import annotations
import argparse
from typing import Tuple

from boss_hr.application.status_service import get_status


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--job-name", required=True, help="岗位名（jobs.json metadata）")
    parser.add_argument("--encrypt-job-id", default=None,
                        help="BOSS encryptJobId（推荐；亦可走 env BOSS_HR_ENCRYPT_JOB_ID）")
    parser.add_argument("--run-id", required=True, help="【必填】run_id 是数据边界")


def run(args: argparse.Namespace) -> Tuple[int, dict]:
    return get_status(
        job_name=args.job_name,
        encrypt_job_id=args.encrypt_job_id,
        run_id=args.run_id,
    )


__all__ = ["add_arguments", "run"]
