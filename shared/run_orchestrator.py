"""跨 Step 串同一 run_id 的编排器 — 跟走 state/current_run.json。

约定（与原作者 state/current_run.json schema 一致）：
    state/current_run.json:
        {
            "run_id": "YYYY-MM-DD_HHMMSS",
            "job_name": "...",
            "job_id": "<encryptJobId>",
            "started_at": "...",
            "steps_done": ["jd","download","score","report","greet"],
            "last_step": "...",
            "last_step_at": "..."
        }

行为：
    bind_or_create(run_id, job_id, force):
      - run_id 显式：写入 current_run.json（允许跨 run 强制指定）。
      - 否则：跟走 current_run.json 的 current run_id（若存在且未 finish）；
              finished 时或没有时新建一个 run_id。
      - 同一秒内已经存在 run_id 时，自动加 _2 / _3 ... 后缀，避免覆盖。

不做的事（与原作者一致）：
    - 不创建目录。目录创建由 JobOutputManager.ensure_run_dir() 调用方按需触发。
    - 不落 greeting/score 等任何业务数据，仅维护 current_run.json。
"""
from __future__ import annotations
import json
import os
import time
from datetime import datetime
from typing import Optional

from output_manager import JobOutputManager, resolve_encrypt_job_id

CURRENT_RUN_FILENAME = "current_run.json"
COLLECTION_STATE_FILENAME = "collection_state.json"  # 旧版兼容：保留以备其他脚本读取


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class RunOrchestrator:
    """跨 Step 串同一 run_id 的编排器。

    路径定位（2026-07-29 新设计）：
      - 推荐传 encrypt_job_id（CLI --encrypt-job-id > env BOSS_HR_ENCRYPT_JOB_ID）
      - 不传 → 沿用兼容模式（job_name 当目录名），但不推荐
    """

    def __init__(self, job_name: str, encrypt_job_id: Optional[str] = None):
        self.job_name = job_name
        # encrypt_job_id 优先 CLI 透传 > env（兼容模式 None）
        self.encrypt_job_id = resolve_encrypt_job_id(encrypt_job_id)
        self._mgr = JobOutputManager(
            job_name,
            encrypt_job_id=self.encrypt_job_id,
            lazy=True,
        )
        self.current_run_path = os.path.join(self._mgr.state_dir, CURRENT_RUN_FILENAME)
        self.collection_path = os.path.join(self._mgr.state_dir, COLLECTION_STATE_FILENAME)

    # ---------- 内部：读写 current_run.json ----------
    def _load_current(self) -> dict:
        if not os.path.exists(self.current_run_path):
            return {}
        try:
            with open(self.current_run_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_current(self, state: dict) -> None:
        os.makedirs(os.path.dirname(self.current_run_path), exist_ok=True)
        # 不主动建 runs/<run_id>/ —— 留给子脚本第一次落盘时由
        # JobOutputManager.ensure_run_dir() 建。这样 bind_or_create 后
        # 若子脚本未实际写文件（dry-run / 异常退出），不会留空壳目录。
        tmp = self.current_run_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.current_run_path)

    def _gen_run_id(self) -> str:
        """生成新 run_id。同秒内已存在则追加 _2/_3/... 后缀。"""
        base = time.strftime("%Y-%m-%d_%H%M%S")
        candidate = base
        n = 2
        runs_dir = self._mgr.runs_dir
        os.makedirs(runs_dir, exist_ok=True)
        while os.path.isdir(os.path.join(runs_dir, candidate)):
            candidate = f"{base}_{n}"
            n += 1
        return candidate

    # ---------- 关键入口 ----------
    def bind_or_create(self, run_id: Optional[str] = None,
                       job_id: Optional[str] = None,
                       force: bool = False, verbose: bool = True) -> str:
        """返回当前 run_id，自动维护 current_run.json。

        优先级：
          1) 显式 run_id → 直接用并写入 current_run.json。
          2) current_run.json 里有过未 finish 且目录里有真实产物的 run → 沿用。
          3) 否则 → 新建一个 run_id（同秒冲突自动加 _N）。

        verbose=True 时打印一行说明（[orchestrator] ...），方便排查
        「为什么是这个 run_id」。
        """
        import sys as _sys
        _log = (lambda m: print(f'[orchestrator] {m}', file=_sys.stderr)) if verbose else (lambda m: None)

        # 1) 显式
        if run_id:
            # 如果 current_run.json 里已记录同一 run_id，保留 started_at
            # —— 否则它会被 _now_str 覆盖，造成 run_id=11:37 / started_at=11:57 的错位。
            cur = self._load_current()
            existing_started_at = (
                cur.get("started_at") if cur.get("run_id") == run_id else None
            )
            state = {
                "run_id": run_id,
                "job_name": self.job_name,
                "job_id": job_id,
                "started_at": existing_started_at or _now_str(),
                "steps_done": cur.get("steps_done", []) if cur.get("run_id") == run_id else [],
                "last_step": cur.get("last_step") if cur.get("run_id") == run_id else None,
                "last_step_at": cur.get("last_step_at", _now_str()) if cur.get("run_id") == run_id else _now_str(),
            }
            self._save_current(state)
            _log(f'显式 run_id={run_id}')
            return run_id

        # 2) 沿用
        cur = self._load_current()
        existing = cur.get("run_id")
        if existing and not force:
            # 沿用同一 run_id 的条件：
            #   (a) current_run.json 未 finished
            #   (b) runs/<run_id>/ 目录存在
            #   (c) 目录里必须有「真实产物」（process/ 子目录或 .html 报告）
            #       —— 否则视为空壳目录（run_orchestrator 或异常退出留下的），
            #       必须新建而不是沿用，避免「bind_or_create 创空目录后沿用」的死循环。
            finished = cur.get("finished", False)
            run_dir = os.path.join(self._mgr.job_dir, "runs", existing)
            if not finished and os.path.isdir(run_dir):
                # 目录里必须有「真实产物」（process/ 子目录或 .html 报告），
                # 否则视为空壳目录（run_orchestrator 或异常退出留下的），
                # 必须新建而不是沿用，避免「bind_or_create 创空目录后沿用」的死循环。
                has_real_output = (
                    os.path.isdir(os.path.join(run_dir, "process"))
                    or any(f.endswith(".html") for f in os.listdir(run_dir))
                )
                if has_real_output:
                    _log(f'沿用活跃 run={existing}')
                    return existing
                else:
                    _log(f'current_run={existing} 目录是空壳，跳过')
            elif finished:
                _log(f'current_run={existing} 已 finished')
            else:
                _log(f'current_run={existing} 目录不存在')
            # 否则视为全新状态 → 走下面"新建"路径

        # 3) 新建
        new_id = self._gen_run_id()
        state = {
            "run_id": new_id,
            "job_name": self.job_name,
            "job_id": job_id,
            "started_at": _now_str(),
            "steps_done": [],
            "last_step": None,
            "last_step_at": _now_str(),
        }
        self._save_current(state)
        _log(f'新建 run={new_id}')
        return new_id

    # ---------- 步骤标记 ----------
    def mark_done(self, step: str, run_id: Optional[str] = None) -> None:
        """标记某 step 完成。run_id 不传则默认当前活跃 run（来自 current_run.json）。"""
        cur = self._load_current()
        rid = run_id or cur.get("run_id")
        if not rid:
            return
        cur["run_id"] = rid
        cur.setdefault("steps_done", [])
        if step not in cur["steps_done"]:
            cur["steps_done"].append(step)
        cur["last_step"] = step
        cur["last_step_at"] = _now_str()
        self._save_current(cur)

    def finish(self) -> None:
        """标记整个 run 结束。

        2026-07-28 行为：仅写 `finished=true` 到 current_run.json，不动原作者的
        collection_state.json schema（顶层 last_collected_at / last_total 等字段
        由 recommend_download.py 的 job_resume_store 维护，避免冲突）。
        """
        cur = self._load_current()
        rid = cur.get("run_id") or ""
        if not rid:
            return
        cur["finished"] = True
        cur["finished_at"] = _now_str()
        self._save_current(cur)
