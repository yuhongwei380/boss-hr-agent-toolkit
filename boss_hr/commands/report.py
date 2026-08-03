"""boss_hr.commands.report — report 命令处理。

使用通用 ok/error schema（第二轮）。
"""
from __future__ import annotations
import argparse

from boss_hr.contracts.results import CommandResult
from boss_hr.application.report_service import generate_report


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--job-name", required=True, help="岗位名")
    parser.add_argument("--encrypt-job-id", default=None,
                        help="BOSS encryptJobId（推荐；亦可走 env BOSS_HR_ENCRYPT_JOB_ID）")
    parser.add_argument("--run-id", required=True, help="【必填】run_id 是数据边界")


def run(args: argparse.Namespace) -> CommandResult:
    return generate_report(
        job_name=args.job_name,
        encrypt_job_id=args.encrypt_job_id,
        run_id=args.run_id,
    )


__all__ = ["add_arguments", "run"]
