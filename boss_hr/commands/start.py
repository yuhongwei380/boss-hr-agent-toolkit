# -*- coding: utf-8 -*-
"""boss_hr.commands.start — start 命令处理（v1.1.1）。

start 的公开语义固定为"创建一次全新的筛选任务"：
- query 必填（岗位名称 / jobId / encryptJobId）
- --job-name 可选（实时解析后用 BOSS 真名）
- --encrypt-job-id 可选（与实时解析结果一致性校验）
- **不接受 --run-id**（start 必须创建新 run，不复用旧任务）
- 不自动调 confirm / fetch / score
"""
from __future__ import annotations
import argparse
import os

from boss_hr.contracts.results import CommandResult
from boss_hr.application.start_service import start_new_run


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """start 公开参数（v1.1.1）。

    - query：必填位置参数。BOSS 实时岗位目录会自动解析：
        完整 encryptJobId | 数字 jobId | 岗位中文名（精确优先 / 模糊兜底）
    - --job-name：可选；最终值优先用实时解析出的 jobName
    - --encrypt-job-id：可选；与实时解析结果不一致会立即报错
    """
    parser.add_argument(
        "query",
        help="岗位名称 / jobId 数字 / 完整 encryptJobId（实时由 BOSS 解析）",
    )
    parser.add_argument(
        "--job-name", default=None,
        help="岗位中文名（可选；实时解析会用 BOSS 真名覆盖）",
    )
    parser.add_argument(
        "--encrypt-job-id", default=None,
        help="可选一致性校验：与实时解析结果不一致会立即停止",
    )


def run(args: argparse.Namespace) -> CommandResult:
    eid = args.encrypt_job_id or os.environ.get("BOSS_HR_ENCRYPT_JOB_ID")
    return start_new_run(
        query=args.query,
        job_name=args.job_name,
        encrypt_job_id=eid,
    )


__all__ = ["add_arguments", "run"]