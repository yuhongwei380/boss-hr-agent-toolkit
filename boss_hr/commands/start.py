# -*- coding: utf-8 -*-
"""boss_hr.commands.start — start 命令处理（v1.1.2）。

start 的公开语义固定为"创建一次全新的筛选任务"：
- query 必填（岗位名称 / jobId / encryptJobId）
- --job-name 可选（实时解析后用 BOSS 真名）
- --encrypt-job-id 可选（与实时解析结果一致性校验）
- --no-auto-launch 调试/测试用：不自动启动 Edge
- --login-wait-seconds 自动启动 Edge 后等用户登录秒数（默认 20）
- **不接受 --run-id**（start 必须创建新 run，不复用旧任务）
- 不自动调 confirm / fetch / score
"""
from __future__ import annotations
import argparse
import os

from boss_hr.contracts.results import CommandResult
from boss_hr.application.start_service import start_new_run


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """start 公开参数（v1.1.2）。

    - query：必填位置参数。BOSS 实时岗位目录会自动解析：
        完整 encryptJobId | 数字 jobId | 岗位中文名（精确优先 / 模糊兜底）
    - --job-name：可选；最终值优先用实时解析出的 jobName
    - --encrypt-job-id：可选；与实时解析结果不一致会立即报错
    - --no-auto-launch：调试/测试用；不自动启动 Edge
    - --login-wait-seconds：自动启动 Edge 后等用户登录秒数（默认 20）
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
    parser.add_argument(
        "--no-auto-launch", action="store_true",
        help="不自动启动 Edge（调试/测试用；缺 CDP 直接返回 CDP_NOT_RUNNING）",
    )
    parser.add_argument(
        "--login-wait-seconds", type=int, default=20,
        help="自动启动 Edge 后等待用户登录的秒数（默认 20）",
    )


def run(args: argparse.Namespace) -> CommandResult:
    eid = args.encrypt_job_id or os.environ.get("BOSS_HR_ENCRYPT_JOB_ID")
    return start_new_run(
        query=args.query,
        job_name=args.job_name,
        encrypt_job_id=eid,
        auto_launch_browser=not bool(getattr(args, "no_auto_launch", False)),
        login_wait_seconds=int(getattr(args, "login_wait_seconds", 20) or 20),
    )


__all__ = ["add_arguments", "run"]