# -*- coding: utf-8 -*-
"""boss_hr.commands.start — start 命令处理。

start 的公开语义固定为"创建一次全新的筛选任务"：
- 必须显式传 query / --job-name / --encrypt-job-id
- **不接受 --run-id**（start 必须创建新 run，不复用旧任务）
- 不自动调 confirm / list / download
"""
from __future__ import annotations
import argparse
import os

from boss_hr.contracts.results import CommandResult
from boss_hr.application.start_service import start_new_run


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """start 公开参数。

    与 status/report/confirm 不同：start 用位置参数 query，且**不**提供 --run-id。
    --job-name / --encrypt-job-id 也必填。
    """
    parser.add_argument(
        "query",
        help="encryptJobId | jobId | 岗位名",
    )
    parser.add_argument(
        "--job-name", required=True,
        help="岗位中文名（写入 jobs.json metadata）",
    )
    parser.add_argument(
        "--encrypt-job-id", default=None,
        help="BOSS encryptJobId（推荐；亦可走 env BOSS_HR_ENCRYPT_JOB_ID）",
    )


def run(args: argparse.Namespace) -> CommandResult:
    eid = args.encrypt_job_id or os.environ.get("BOSS_HR_ENCRYPT_JOB_ID")
    return start_new_run(
        query=args.query,
        job_name=args.job_name,
        encrypt_job_id=eid,
    )


__all__ = ["add_arguments", "run"]
