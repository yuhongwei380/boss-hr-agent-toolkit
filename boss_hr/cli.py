#!/usr/bin/env python3
"""boss-hr CLI — v1.1-skill-stable 统一入口（验证性重构第一轮）

第一轮只实现 status 命令；其它命令按 status → report → confirm → score →
fetch → start → greet 顺序逐步迁移。

实现策略（按用户要求）：
  - 第一阶段：CLI → shared.cli_runner.run_python_cli() → 现有脚本
  - 第二阶段：逐步把旧脚本改为「业务函数 + 旧 main() 兼容入口」，CLI 直接 import
  - 禁止：复制旧业务逻辑到 boss_hr 包、禁止创建 spec_*.json 文件

退出码（v1.1 沿用 cli_runner 退出码，status 不调子脚本所以这里只列规范）：
  0   - OK
  1   - 参数错误（通用）
  22  - 缺 --run-id
  23  - run 不存在
  24  - run 与岗位不匹配
  26  - 缺输入文件
  27  - 缺输出文件
  99  - 内部错误

JSON 输出格式：
  {
    "status":  "ok" | "blocked" | "error",
    "command": "status",
    "run_id":  "...",
    "data":    {...},
    "message": "..."
  }

用法：
  python -X utf8 boss_hr/cli.py status --job-name "<岗位>" \
      --encrypt-job-id "<id>" --run-id "<run_id>"
"""
from __future__ import annotations
import argparse
import json
import os
import sys

# 把仓库根目录加进 sys.path，方便 import shared/*
_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLKIT_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _TOOLKIT_ROOT)
# shared/* 内部互相 import 用「模块名」形式（不带 shared. 前缀），
# 旧脚本会在自己文件里 sys.path.insert(0, shared/)；新 CLI 也得加。
sys.path.insert(0, os.path.join(_TOOLKIT_ROOT, "shared"))


def _emit(payload: dict, *, exit_code: int = 0) -> int:
    """统一 JSON 输出到 stdout。"""
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return exit_code


# ---------------- status 命令 ----------------

def cmd_status(args: argparse.Namespace) -> int:
    """读取 runs/<run_id>/run.json + process/ 目录扫描，返回状态概览。

    第一阶段（v1.1）：status 不调任何子脚本，直接 import shared/output_manager
    + shared/run_orchestrator 做路径定位和 run.json 校验。

    Returns:
        exit code: 0 / 1 / 23（run 不存在）/ 24（run 与岗位不匹配）
    """
    from shared.output_manager import JobOutputManager
    from shared.run_orchestrator import (
        RunOrchestrator,
        EXIT_CODE_RUN_NOT_FOUND,
        EXIT_CODE_RUN_JOB_MISMATCH,
    )

    encrypt_job_id = args.encrypt_job_id or os.environ.get("BOSS_HR_ENCRYPT_JOB_ID")
    if not encrypt_job_id:
        return _emit({
            "status": "error",
            "command": "status",
            "message": "缺少 encrypt_job_id（传 --encrypt-job-id 或设环境变量 BOSS_HR_ENCRYPT_JOB_ID）",
        }, exit_code=1)

    if not args.run_id:
        return _emit({
            "status": "error",
            "command": "status",
            "run_id": None,
            "message": "缺少 --run-id（run_id 是数据边界，禁止自动选择历史 run）",
        }, exit_code=22)

    orch = RunOrchestrator(args.job_name, encrypt_job_id=encrypt_job_id)
    try:
        run_id = orch.bind_existing_run(args.run_id)
    except FileNotFoundError:
        return _emit({
            "status": "blocked",
            "command": "status",
            "run_id": args.run_id,
            "encrypt_job_id": encrypt_job_id,
            "message": f"run_id={args.run_id} 在岗位目录下不存在",
        }, exit_code=EXIT_CODE_RUN_NOT_FOUND)
    except RuntimeError as e:
        return _emit({
            "status": "blocked",
            "command": "status",
            "run_id": args.run_id,
            "encrypt_job_id": encrypt_job_id,
            "message": str(e),
        }, exit_code=EXIT_CODE_RUN_JOB_MISMATCH)

    out = JobOutputManager(args.job_name, encrypt_job_id=encrypt_job_id, run_id=run_id, lazy=True)
    run_json_path = os.path.join(out.runs_dir, run_id, "run.json")

    state: dict = {}
    if os.path.exists(run_json_path):
        try:
            with open(run_json_path, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception as e:
            state = {"_read_error": str(e)}

    # 扫 process/ 目录看哪些文件已经存在
    process_dir = os.path.join(out.runs_dir, run_id, "process")
    files = {}
    if os.path.isdir(process_dir):
        for fn in sorted(os.listdir(process_dir)):
            full = os.path.join(process_dir, fn)
            if os.path.isdir(full):
                files[fn] = {"type": "dir", "entries": sorted(os.listdir(full))[:20]}
            else:
                try:
                    files[fn] = {"type": "file", "size": os.path.getsize(full)}
                except OSError:
                    files[fn] = {"type": "file"}

    # 判断当前 workflow 状态
    steps_done = state.get("steps_done", [])
    confirmed = bool(state.get("confirmed"))
    finished = bool(state.get("finished"))
    if finished:
        workflow_state = "finished"
    elif not confirmed:
        workflow_state = "waiting_user_confirmation"
    elif "jd" not in steps_done:
        workflow_state = "ready_to_fetch"  # unlikely
    elif "download" not in steps_done:
        workflow_state = "ready_to_fetch"
    elif "score" not in steps_done:
        workflow_state = "ready_to_score"
    elif "report" not in steps_done:
        workflow_state = "ready_to_report"
    else:
        workflow_state = "report_ready"

    return _emit({
        "status": "ok",
        "command": "status",
        "run_id": run_id,
        "encrypt_job_id": encrypt_job_id,
        "job_name": args.job_name,
        "workflow_state": workflow_state,
        "confirmed": confirmed,
        "finished": finished,
        "last_step": state.get("last_step"),
        "last_step_at": state.get("last_step_at"),
        "steps_done": steps_done,
        "started_at": state.get("started_at"),
        "user_confirmed_at": state.get("user_confirmed_at"),
        "finished_at": state.get("finished_at"),
        "paths": {
            "run_dir": os.path.join(out.runs_dir, run_id),
            "process_dir": process_dir,
            "report_html": os.path.join(out.runs_dir, run_id, f"{run_id}_screening_report.html"),
        },
        "process_files": files,
    }, exit_code=0)


# ---------------- CLI 入口 ----------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="boss-hr",
        description="BOSS HR 工具包统一 CLI（v1.1+）。",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # status
    p_status = sub.add_parser("status", help="查询指定 run 的状态（不修改任何文件）")
    p_status.add_argument("--job-name", required=True, help="岗位名（jobs.json metadata）")
    p_status.add_argument("--encrypt-job-id", default=None,
                          help="BOSS encryptJobId（推荐；亦可走 env BOSS_HR_ENCRYPT_JOB_ID）")
    p_status.add_argument("--run-id", required=True, help="【必填】run_id 是数据边界")

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "status":
        return cmd_status(args)

    return _emit({
        "status": "error",
        "command": args.command,
        "message": f"未知命令：{args.command}",
    }, exit_code=1)


if __name__ == "__main__":
    sys.exit(main())
