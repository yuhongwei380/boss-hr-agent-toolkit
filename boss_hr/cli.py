#!/usr/bin/env python3
"""boss-hr CLI — 统一入口（验证性重构第二轮）

本轮只新增 report 命令；其它命令按 status → report → confirm → score →
fetch → start → greet 顺序逐步迁移。

实现策略（按用户要求）：
  - 第一阶段：CLI → shared.cli_runner.run_python_cli() → 现有脚本
  - 第二阶段：逐步把旧脚本改为「业务函数 + 旧 main() 兼容入口」，CLI 直接 import
  - 禁止：复制旧业务逻辑到 boss_hr 包、禁止创建 spec_*.json 文件
  - 报告 HTML 生成、候选人排序、统计全部留在
    html-report/scripts/generate_html_report.py；CLI 只做编排 + 输出包装

退出码语义：**保留旧脚本的退出码**（不归一化）：
  0   - 成功
  1   - 参数错误 / FileNotFoundError（generate_html_report main 未捕获）
  2   - 缺 --run-id（argparse）
  27  - 缺 screening_results.json

JSON 输出 schema（report）：
  成功：
    {
      "ok": true,
      "command": "report",
      "status": "report_ready",
      "run_id": "...",
      "encrypt_job_id": "...",
      "job_name": "...",
      "data": {"report_file": "<绝对路径>"},
      "next_action": "greet_optional"
    }
  失败：
    {
      "ok": false,
      "command": "report",
      "run_id": "...",
      "encrypt_job_id": "...",
      "error": {"code": "MISSING_SCREENING|RUN_NOT_FOUND|JOB_MISMATCH|MISSING_ENCRYPT_JOB_ID|MISSING_RUN_ID|INTERNAL",
                "message": "..."}
    }
  日志写 stderr（不被 stdout 解析）。

用法：
  python -X utf8 boss_hr/cli.py report \
      --job-name "<岗位>" --encrypt-job-id "<id>" --run-id "<run_id>"
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
from typing import Any

# 工具包根 + shared/ 进 sys.path（generate_html_report.py 内部 sys.path.insert 也加 shared/）
_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLKIT_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _TOOLKIT_ROOT)
sys.path.insert(0, os.path.join(_TOOLKIT_ROOT, "shared"))


def _log(msg: str) -> None:
    """日志写 stderr，不污染 stdout JSON。"""
    sys.stderr.write(f"[boss_hr] {msg}\n")
    sys.stderr.flush()


def _emit(payload: dict, *, exit_code: int = 0) -> int:
    """统一 JSON 输出到 stdout（不带 emoji / 中文 print）。"""
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return exit_code


# ============================================================
# status 命令（v1.1-skill-stable 之上的新增；保持第一轮 schema 不变）
# ============================================================

def cmd_status(args: argparse.Namespace) -> int:
    """读取 runs/<run_id>/run.json + process/ 目录扫描，返回状态概览。

    status 不调任何子脚本，直接 import shared/output_manager
    + shared/run_orchestrator 做路径定位和 run.json 校验。
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

    steps_done = state.get("steps_done", [])
    confirmed = bool(state.get("confirmed"))
    finished = bool(state.get("finished"))
    if finished:
        workflow_state = "finished"
    elif not confirmed:
        workflow_state = "waiting_user_confirmation"
    elif "jd" not in steps_done:
        workflow_state = "ready_to_fetch"
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


# ============================================================
# report 命令（本轮新增）
# ============================================================

# 报告子进程 stdout 解析："✅ HTML 报告已生成: <path>"
_REPORT_PATH_RE = re.compile(r"HTML 报告已生成:\s*(\S.*?)(?:\s*$|\n)", re.MULTILINE)


def _resolve_report_path(eid: str, run_id: str, job_name: str) -> str:
    """从 JobOutputManager 算默认报告路径（旧脚本同款公式）。"""
    from shared.output_manager import JobOutputManager
    out = JobOutputManager(job_name, encrypt_job_id=eid, run_id=run_id, lazy=True)
    return os.path.join(out.runs_dir, run_id, f"{run_id}_screening_report.html")


def cmd_report(args: argparse.Namespace) -> int:
    """Step 4：调 generate_html_report.py 生成可视化 HTML 报告。

    实现路径：
      1) CLI 参数校验（encrypt_job_id + run_id）
      2) 预校验 run 存在（避免子进程抛 FileNotFoundError → stderr traceback）
      3) cli_runner.run_python_cli("generate_html_report", [args], check=False)
      4) 解析子进程 stdout：抽报告路径
      5) 包装统一 JSON 输出
    """
    from shared.run_orchestrator import RunOrchestrator, EXIT_CODE_RUN_NOT_FOUND

    encrypt_job_id = args.encrypt_job_id or os.environ.get("BOSS_HR_ENCRYPT_JOB_ID")
    if not encrypt_job_id:
        return _emit({
            "ok": False, "command": "report", "run_id": args.run_id,
            "error": {"code": "MISSING_ENCRYPT_JOB_ID",
                      "message": "缺少 encrypt_job_id（传 --encrypt-job-id 或设环境变量 BOSS_HR_ENCRYPT_JOB_ID）"},
        }, exit_code=1)

    if not args.run_id:
        return _emit({
            "ok": False, "command": "report", "run_id": None,
            "error": {"code": "MISSING_RUN_ID",
                      "message": "缺少 --run-id（run_id 是数据边界，禁止自动选择历史 run）"},
        }, exit_code=2)

    # 预校验 run 存在 —— 把子进程会抛的 FileNotFoundError（→ 退出 1）拦在 CLI 层
    orch = RunOrchestrator(args.job_name, encrypt_job_id=encrypt_job_id)
    try:
        run_id = orch.bind_existing_run(args.run_id)
    except FileNotFoundError:
        return _emit({
            "ok": False, "command": "report",
            "run_id": args.run_id, "encrypt_job_id": encrypt_job_id,
            "error": {"code": "RUN_NOT_FOUND",
                      "message": f"run_id={args.run_id} 在岗位目录下不存在"},
        }, exit_code=EXIT_CODE_RUN_NOT_FOUND)
    except RuntimeError as e:
        return _emit({
            "ok": False, "command": "report",
            "run_id": args.run_id, "encrypt_job_id": encrypt_job_id,
            "error": {"code": "JOB_MISMATCH", "message": str(e)},
        }, exit_code=24)

    # 调旧脚本（cli_runner 白名单工具）
    from shared.cli_runner import run_python_cli

    expected_path = _resolve_report_path(encrypt_job_id, run_id, args.job_name)
    args_list = [
        "--job-name", args.job_name,
        "--encrypt-job-id", encrypt_job_id,
        "--run-id", run_id,
    ]
    _log(f"boss-hr report: 调 generate_html_report.py run_id={run_id}")
    proc = run_python_cli("generate_html_report", args_list, timeout=60, check=False)
    _log(f"generate_html_report.py returncode={proc.returncode}")

    # 失败映射（保留旧退出码语义）
    if proc.returncode != 0:
        # 子脚本缺 screening_results.json 时 stdout 含 {"status":"blocked","exit_code":27,...}
        # 我们把它解读为 MISSING_SCREENING；其他 rc=1 视为 INTERNAL（FileNotFoundError 已预校验）
        err_code = "INTERNAL"
        err_msg = "report 生成失败"
        if proc.returncode == 27:
            err_code = "MISSING_SCREENING"
            err_msg = "当前 run 缺少 process/screening_results.json（请先跑 score）"
        elif proc.returncode == 2:
            err_code = "MISSING_RUN_ID"
            err_msg = "子脚本 argparse 缺 --run-id（CLI 层已 required，此分支防御性保留）"
        # 抽 stdout 最后一行 JSON（如有）
        if proc.stdout:
            for line in proc.stdout.splitlines()[::-1]:
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    try:
                        j = json.loads(line)
                        if isinstance(j, dict) and "message" in j:
                            err_msg = j["message"]
                            break
                    except json.JSONDecodeError:
                        pass
        if proc.stderr:
            _log(f"子进程 stderr: {proc.stderr[-500:]}")
        return _emit({
            "ok": False, "command": "report",
            "run_id": run_id, "encrypt_job_id": encrypt_job_id,
            "error": {"code": err_code, "message": err_msg,
                      "subprocess_returncode": proc.returncode},
        }, exit_code=proc.returncode)

    # 成功：从 stdout 抽报告路径；抽不到就用 expected_path 兜底
    m = _REPORT_PATH_RE.search(proc.stdout or "")
    report_file = m.group(1).strip() if m else expected_path

    # 兜底校验：报告必须真存在
    if not os.path.isfile(report_file):
        return _emit({
            "ok": False, "command": "report",
            "run_id": run_id, "encrypt_job_id": encrypt_job_id,
            "error": {"code": "INTERNAL",
                      "message": f"子脚本 rc=0 但报告文件未生成：{report_file}"},
        }, exit_code=1)

    _log(f"report ready: {report_file}")
    return _emit({
        "ok": True, "command": "report",
        "status": "report_ready",
        "run_id": run_id, "encrypt_job_id": encrypt_job_id,
        "job_name": args.job_name,
        "data": {"report_file": os.path.abspath(report_file)},
        "next_action": "greet_optional",
    }, exit_code=0)


# ============================================================
# CLI 入口
# ============================================================

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

    # report
    p_report = sub.add_parser("report", help="Step 4：生成可视化 HTML 报告")
    p_report.add_argument("--job-name", required=True, help="岗位名")
    p_report.add_argument("--encrypt-job-id", default=None,
                          help="BOSS encryptJobId（推荐；亦可走 env BOSS_HR_ENCRYPT_JOB_ID）")
    p_report.add_argument("--run-id", required=True, help="【必填】run_id 是数据边界")

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "status":
        return cmd_status(args)
    if args.command == "report":
        return cmd_report(args)

    return _emit({
        "ok": False, "command": args.command,
        "error": {"code": "UNKNOWN_COMMAND", "message": f"未知命令：{args.command}"},
    }, exit_code=1)


if __name__ == "__main__":
    sys.exit(main())
