# -*- coding: utf-8 -*-
"""boss_hr.commands.fetch — fetch 命令处理。"""
from __future__ import annotations
import argparse

from boss_hr.contracts.results import CommandResult
from boss_hr.application.fetch_service import fetch_candidates
from boss_hr.commands._argparse_helpers import (
    add_required_arguments, require_encrypt_job_id,
)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    add_required_arguments(parser)
    parser.add_argument(
        "--count", type=int, default=10,
        help="拉取 + 下载的最大候选人数（默认 10）。传 --rules 时作为 list 下限，实际以规则 download.list_count / max_details 为准",
    )
    parser.add_argument(
        "--rules", default=None,
        help="筛选规则 JSON。不传则尝试读本次 run 的 process/screening_rules.json",
    )


def run(args: argparse.Namespace) -> CommandResult:
    eid = require_encrypt_job_id(args._parser, args)
    return fetch_candidates(
        job_name=args.job_name,
        encrypt_job_id=eid,
        run_id=args.run_id,
        count=args.count,
        rules_path=getattr(args, "rules", None),
    )


__all__ = ["add_arguments", "run"]
