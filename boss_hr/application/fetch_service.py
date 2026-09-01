# -*- coding: utf-8 -*-
"""boss_hr.application.fetch_service — fetch 命令业务逻辑。

职责（C1）：
  - 校验 run 存在 + confirmed=true + count > 0
  - 调 cli_runner.run_python_cli('recommend_list', ...) 拉候选人列表
  - 列表成功后才调 cli_runner.run_python_cli('recommend_download', ...) 下载简历
  - download 失败时不回滚（保留 list 产物）
  - 返回 {requested_count, listed_count, downloaded_count, failed_count,
          candidate_list_file, new_resumes_file, failed_resumes_file}

不直接调 patchright / 不读 recommend_list.py 的 print 输出。
所有调用走 adapters/legacy_runner。
"""
from __future__ import annotations
import json
import os
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
from boss_hr.adapters import legacy_runner
# 重要：用全限定名 `legacy_runner.run_legacy_cli(...)` 而非局部 `run_legacy_cli(...)`；
# 这样 monkeypatch.setattr("boss_hr.adapters.legacy_runner.run_legacy_cli", ...) 才生效
# （import-from 后的引用在调用方命名空间独立，setattr 不会传播）。
from boss_hr.adapters.legacy_runner import legacy_error, try_extract_blocked_message
from boss_hr.adapters.browser_environment import ensure_browser_ready


def _resolve_encrypt_job_id(cli_value: Optional[str]) -> Optional[str]:
    if cli_value:
        return cli_value
    return os.environ.get("BOSS_HR_ENCRYPT_JOB_ID")


# download 超时策略：
# - 节流时间长，固定 1800 仅为下限
# - 随候选人数量 count 线性放大：300 + count * 60
_DOWNLOAD_TIMEOUT_MIN_SECONDS = 1800
_DOWNLOAD_TIMEOUT_BASE_SECONDS = 300
_DOWNLOAD_TIMEOUT_PER_CANDIDATE_SECONDS = 60

# list 抓取缓冲倍数：list 阶段多抓候选，作为 download 的供给缓冲，
# 避免部分候选已命中 success/limit_hit 或失败吃掉配额，导致实际下载份数低于请求的 count。
_LIST_FETCH_BUFFER_MULTIPLIER = 2


def _calculate_download_timeout(count: int) -> int:
    return max(
        _DOWNLOAD_TIMEOUT_MIN_SECONDS,
        _DOWNLOAD_TIMEOUT_BASE_SECONDS
        + count * _DOWNLOAD_TIMEOUT_PER_CANDIDATE_SECONDS,
    )


def _infer_run_paths(job_name: str, eid: str, run_id: str) -> dict:
    """从 JobOutputManager 算 list / download 产物路径。"""
    from shared.output_manager import JobOutputManager
    out = JobOutputManager(job_name, encrypt_job_id=eid, run_id=run_id, lazy=True)
    runs_dir = out.runs_dir
    process_dir = os.path.join(runs_dir, run_id, "process")
    return {
        "runs_dir": runs_dir,
        "process_dir": process_dir,
        "candidate_list_file": os.path.join(process_dir, "recommend_geek_ids.json"),
        "new_resumes_file": os.path.join(process_dir, "new_resumes.json"),
        "failed_resumes_file": os.path.join(process_dir, "failed_resumes.json"),
        "rules_file": os.path.join(process_dir, "screening_rules.json"),
        "screened_file": os.path.join(process_dir, "screened_geek_ids.json"),
        "coarse_log_file": os.path.join(process_dir, "coarse_screen_log.json"),
        "applied_filters_file": os.path.join(process_dir, "applied_filters.json"),
    }


def _pre_check(job_name: str, eid: str, run_id: str, count: int
               ) -> tuple[int, Optional[str], Optional[dict]]:
    """前置校验：run 存在 + confirmed=true + count>0 + new_resumes 不必存在（fetch 会建）。

    返回 (exit_code, error_msg, paths)。
    - (0, None, paths)：通过
    - (rc!=0, msg, None)：失败
    """
    if count is None or count <= 0:
        return ExitCode(1).value if False else 1, f"--count 必须为正整数（当前 {count}）", None
    from shared.run_orchestrator import (
        RunOrchestrator,
        EXIT_CODE_RUN_NOT_FOUND,
        EXIT_CODE_RUN_JOB_MISMATCH,
    )
    orch = RunOrchestrator(job_name, encrypt_job_id=eid)
    try:
        orch.bind_existing_run(run_id)
    except FileNotFoundError:
        return EXIT_CODE_RUN_NOT_FOUND, f"run_id={run_id} 在岗位目录下不存在", None
    except RuntimeError as e:
        return EXIT_CODE_RUN_JOB_MISMATCH, str(e), None

    run_json_path = os.path.join(orch._mgr.runs_dir, run_id, "run.json")
    if os.path.exists(run_json_path):
        try:
            with open(run_json_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            if not state.get("confirmed"):
                return 20, f"run_id={run_id} 尚未用户确认", None
        except Exception:
            pass

    paths = _infer_run_paths(job_name, eid, run_id)
    return 0, None, paths


def _read_json_array(path: str) -> list:
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def fetch_candidates(*, job_name: str, encrypt_job_id: Optional[str],
                     run_id: Optional[str], count: int,
                     rules_path: Optional[str] = None) -> CommandResult:
    """fetch 命令业务实现。

    流程：
      1) 预校验（run/confirmed/count）
      2) 调 recommend_list.py --max N
      3) list 失败 → 透传 rc（list 阶段失败）
      4) list 成功 → 读 recommend_geek_ids.json 算 listed_count
      5) 调 recommend_download.py --max N
      6) download 失败 → 透传 rc（download 阶段失败，list 产物保留）
      7) download 成功 → 读 new_resumes.json / failed_resumes.json
      8) 返回 candidates_fetched
    """
    eid = _resolve_encrypt_job_id(encrypt_job_id)
    if not eid:
        return error(
            error_obj=UnifiedError(
                code=ErrorCode.MISSING_ENCRYPT_JOB_ID,
                message="缺少 encrypt_job_id",
            ),
            run_id=run_id, exit_code=ExitCode.GENERIC,
        )
    if not run_id:
        return error(
            error_obj=UnifiedError(
                code=ErrorCode.MISSING_RUN_ID,
                message="缺少 --run-id",
            ),
            exit_code=ExitCode.MISSING_RUN_ID,
        )

    rc, msg, paths = _pre_check(job_name, eid, run_id, count)
    if rc != 0:
        if rc == 23:
            code = ErrorCode.RUN_NOT_FOUND
        elif rc == 24:
            code = ErrorCode.JOB_MISMATCH
        elif rc == 20:
            code = ErrorCode.AWAITING_CONFIRMATION
        else:
            code = ErrorCode.INTERNAL
        return error(
            error_obj=UnifiedError(code=code, message=msg or "前置校验失败"),
            run_id=run_id, encrypt_job_id=eid, job_name=job_name,
            exit_code=ExitCode(rc),
        )

    # v1.1.2: 自动启动 Edge + 登录态（不再要求用户预跑 doctor）。
    # v1.1.3: fetch 保留 v1.1.2 旧轮询路径（wait_for_user_login=True，
    # 默认 20s）。start 由单一参数 --login-wait-seconds 推导，
    # =0 不阻塞、>0 阻塞；fetch/greet 保持兼容接线不变。
    ready = ensure_browser_ready(auto_launch=True, wait_for_user_login=True)
    if not ready.ok:
        return error(
            error_obj=ready.error_obj,
            run_id=run_id, encrypt_job_id=eid, job_name=job_name,
            exit_code=ExitCode.GENERIC,
            next_action=ready.next_action,
            remediation=ready.remediation,
        )

    # Step 1: 调 recommend_list
    # 有规则：按 list_count 拉卡片，并让 list 脚本点推荐 Tab + BOSS 筛选器
    # 无规则：按 count * 缓冲倍数多抓（旧行为）
    rules = None
    rules_file_for_list = None
    if rules_path:
        from screening_rules import load_rules
        try:
            rules = load_rules(rules_path)
        except FileNotFoundError as e:
            return error(
                error_obj=UnifiedError(
                    code=ErrorCode.INTERNAL,
                    message=str(e),
                    recoverable=True,
                ),
                run_id=run_id, encrypt_job_id=eid, job_name=job_name,
                exit_code=ExitCode.GENERIC,
            )
        rules_file_for_list = os.path.abspath(rules_path)
    elif os.path.isfile(paths["rules_file"]):
        from screening_rules import load_rules
        rules = load_rules(paths["rules_file"])
        rules_file_for_list = paths["rules_file"]

    list_max = count * _LIST_FETCH_BUFFER_MULTIPLIER
    list_args = [
        "--job-name", job_name,
        "--encrypt-job-id", eid,
        "--run-id", run_id,
        "--max", str(list_max),
    ]
    if rules is not None:
        list_max = max(count, rules.list_count)
        list_args[-1] = str(list_max)
        list_args.extend(["--rules-file", rules_file_for_list])

    list_result = legacy_runner.run_legacy_cli(
        "recommend_list",
        list_args,
        timeout=600,
    )

    if list_result.returncode != 0:
        better_msg = try_extract_blocked_message(list_result.stdout)
        unified = legacy_error(list_result)
        if better_msg:
            unified = UnifiedError(code=unified.code, message=better_msg,
                                   subprocess_returncode=unified.subprocess_returncode)
        return error(
            error_obj=unified,
            run_id=run_id, encrypt_job_id=eid, job_name=job_name,
            exit_code=ExitCode(list_result.returncode),
        )

    # 读 list 产物
    listed = _read_json_array(paths["candidate_list_file"])
    listed_count = len(listed)

    download_args = [
        "--job-name", job_name,
        "--encrypt-job-id", eid,
        "--run-id", run_id,
        "--max", str(count),
    ]
    screened_count = listed_count
    rejected_count = 0
    if rules is not None:
        from screening_rules import coarse_screen_list, save_rules
        save_rules(rules, paths["rules_file"])
        screened = coarse_screen_list(listed, rules)
        passed = screened["passed"][: rules.max_details]
        with open(paths["screened_file"], "w", encoding="utf-8") as f:
            json.dump(passed, f, ensure_ascii=False, indent=2)
        with open(paths["coarse_log_file"], "w", encoding="utf-8") as f:
            json.dump({
                "listed_count": screened["listed_count"],
                "passed_count": screened["passed_count"],
                "rejected_count": screened["rejected_count"],
                "download_count": len(passed),
                "rejected": [
                    {"encryptGeekId": x.get("encryptGeekId"),
                     "name": x.get("name"),
                     "reasons": x.get("reasons")}
                    for x in screened["rejected"]
                ],
            }, f, ensure_ascii=False, indent=2)
        screened_count = len(passed)
        rejected_count = screened["rejected_count"]
        download_args[-1] = str(rules.max_details)
        download_args.extend(["--ids-file", paths["screened_file"], "--click-detail"])

    # Step 2: 调 recommend_download
    dl_result = legacy_runner.run_legacy_cli(
        "recommend_download",
        download_args,
        timeout=_calculate_download_timeout(
            rules.max_details if rules is not None else count
        ),
    )

    if dl_result.returncode != 0:
        # 保留 list 产物，不回滚
        better_msg = try_extract_blocked_message(dl_result.stdout)
        unified = legacy_error(dl_result)
        if better_msg:
            unified = UnifiedError(code=unified.code, message=better_msg,
                                   subprocess_returncode=unified.subprocess_returncode)
        return error(
            error_obj=unified,
            run_id=run_id, encrypt_job_id=eid, job_name=job_name,
            exit_code=ExitCode(dl_result.returncode),
        )

    # 读 download 产物
    new_resumes = _read_json_array(paths["new_resumes_file"])
    failed_resumes = _read_json_array(paths["failed_resumes_file"])
    downloaded_count = sum(1 for r in new_resumes if r.get("ok", True))
    failed_count = len(failed_resumes)

    return ok(
        status="candidates_fetched",
        run_id=run_id, encrypt_job_id=eid, job_name=job_name,
        data={
            "requested_count": count,
            "listed_count": listed_count,
            "screened_count": screened_count,
            "rejected_count": rejected_count,
            "downloaded_count": downloaded_count,
            "failed_count": failed_count,
            "candidate_list_file": paths["candidate_list_file"],
            "new_resumes_file": paths["new_resumes_file"],
            "failed_resumes_file": paths["failed_resumes_file"],
            "click_detail": bool(rules is not None),
        },
        next_action="score",
    )


__all__ = ["fetch_candidates"]
