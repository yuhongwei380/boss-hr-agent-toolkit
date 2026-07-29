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

from output_manager import JobOutputManager

CURRENT_RUN_FILENAME = "current_run.json"
COLLECTION_STATE_FILENAME = "collection_state.json"  # 旧版兼容：保留以备其他脚本读取


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class RunOrchestrator:
    def __init__(self, job_name: str):
        self.job_name = job_name
        self._mgr = JobOutputManager(job_name, lazy=True)
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
                       force: bool = False) -> str:
        """返回当前 run_id，自动维护 current_run.json。

        优先级：
          1) 显式 run_id → 直接用并写入 current_run.json。
          2) current_run.json 里有过未 finish 的 run → 沿用。
          3) 否则 → 新建一个 run_id（同秒冲突自动加 _N）。
        """
        # 1) 显式
        if run_id:
            state = {
                "run_id": run_id,
                "job_name": self.job_name,
                "job_id": job_id,
                "started_at": _now_str(),
                "steps_done": [],
                "last_step": None,
                "last_step_at": _now_str(),
            }
            self._save_current(state)
            return run_id

        # 2) 沿用
        cur = self._load_current()
        existing = cur.get("run_id")
        if existing and not force:
            # 只要当前活跃 run 至少有"启动过"的痕迹（steps_done 非空，
            # 或 job_id 已绑定，或未显式 finished），就沿用同一 run_id。
            # 这样 5 步流程里 Step 2/3/4/5 都能落入同一 runs/<run_id>/。
            steps_done = cur.get("steps_done") or []
            finished = cur.get("finished", False)
            if steps_done or cur.get("job_id"):
                if not finished:
                    return existing
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
