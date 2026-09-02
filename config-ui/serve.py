#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地筛选配置页：多岗位 + 芯片多选，写出规则文件和 Agent 提示词。

用法：
  python config-ui/serve.py
  python config-ui/serve.py --port 8765 --no-open
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

_HERE = Path(__file__).resolve().parent
_TOOLKIT_ROOT = _HERE.parent
sys.path.insert(0, str(_TOOLKIT_ROOT))
sys.path.insert(0, str(_TOOLKIT_ROOT / "shared"))

from output_manager import OUTPUT_ROOT  # noqa: E402
from screening_rules import (  # noqa: E402
    DEGREE_RANK,
    TIER_MIN_SCORE,
    load_rules,
    map_years_to_boss_experience,
    normalize_education,
    rules_from_dict,
    save_rules,
)
from score_profiles import (  # noqa: E402
    get_profile,
    normalize_profile_id,
    normalize_tech_stacks,
)

INDEX_HTML = _HERE / "index.html"
DEFAULT_PORT = 8765
CONFIG_DIRNAME = "_config"
RULES_FILENAME = "rules.json"
BUNDLE_FILENAME = "bundle.json"
PROMPT_FILENAME = "agent-prompt.txt"

EXP_YEARS = {
    "在校/应届": (0, 0),
    "1年以内": (0, 1),
    "1-3年": (1, 3),
    "3-5年": (3, 5),
    "5-10年": (5, 10),
    "10年以上": (10, 99),
}

EMPTY_FORM: dict[str, Any] = {
    "jobs": [{"query": "", "jd": ""}],
    "education": ["本科"],
    "experience": ["3-5年"],
    "school_tier": [],
    "boss_keywords": [],
    "keywords_any": [],
    "keywords_exclude": [],
    "years_min": 3,
    "years_max": 10,
    "list_count": 40,
    "max_details": 10,
    "greet_threshold": 70,
    "greet_max": 10,
    "score_profile": "tech",
    "tech_stacks": [],
}


def config_dir(output_root: Optional[str] = None) -> Path:
    return Path(output_root or OUTPUT_ROOT) / CONFIG_DIRNAME


def rules_file(output_root: Optional[str] = None) -> Path:
    return config_dir(output_root) / RULES_FILENAME


def bundle_file(output_root: Optional[str] = None) -> Path:
    return config_dir(output_root) / BUNDLE_FILENAME


def prompt_file(output_root: Optional[str] = None) -> Path:
    return config_dir(output_root) / PROMPT_FILENAME


TIER_FORM_ALIASES = {
    "民办": "民办本科",
    "民办/独立学院": "民办本科",
}


def _int_or_default(value: Any, default: int) -> int:
    """空值用默认；0 要保留（例如 greet_max=0 表示不自动打招呼）。"""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    m = re.search(r"-?\d+", str(value))
    return int(m.group(0)) if m else default


def _as_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [p.strip() for p in re.split(r"[,，、\s]+", value) if p.strip()]
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return [str(value).strip()]


def _lowest_education(names: list[str]) -> Optional[str]:
    ranked: list[tuple[int, str]] = []
    for name in names:
        norm = normalize_education(name)
        if not norm:
            continue
        ranked.append((DEGREE_RANK.get(norm, 99), norm))
    if not ranked:
        return None
    ranked.sort()
    return ranked[0][1]


def _lowest_school_tier(names: list[str]) -> Optional[str]:
    ranked: list[tuple[int, str]] = []
    for name in names:
        text = str(name).strip()
        if not text or text == "不限":
            continue
        text = TIER_FORM_ALIASES.get(text, text)
        score = TIER_MIN_SCORE.get(text)
        if score is None:
            continue
        ranked.append((score, text))
    if not ranked:
        return None
    ranked.sort()
    return ranked[0][1]


def _years_from_experience(names: list[str]) -> tuple[Optional[int], Optional[int]]:
    lows: list[int] = []
    highs: list[int] = []
    for name in names:
        pair = EXP_YEARS.get(name)
        if not pair:
            continue
        lows.append(pair[0])
        highs.append(pair[1])
    if not lows:
        return None, None
    return min(lows), max(highs)


def _safe_slug(query: str, index: int) -> str:
    text = re.sub(r'[<>:"/\\|?*]', "", (query or "").strip()) or "job"
    text = re.sub(r"\s+", "-", text)[:40]
    return f"{index:02d}-{text}"


def form_from_rules_dict(raw: dict) -> dict[str, Any]:
    job = raw.get("job") or {}
    boss = raw.get("boss_filters") or {}
    coarse = raw.get("coarse_screen") or {}
    download = raw.get("download") or {}
    score = raw.get("score") or {}
    edu = _as_list(boss.get("education") or coarse.get("education_min"))
    exp = _as_list(boss.get("experience"))
    return {
        "jobs": [{"query": str(job.get("query") or ""), "jd": str(job.get("jd") or "")}],
        "education": edu or ["本科"],
        "experience": exp or ["3-5年"],
        "school_tier": [
            TIER_FORM_ALIASES.get(t, t)
            for t in _as_list(coarse.get("school_tier_min"))
        ],
        "boss_keywords": _as_list(boss.get("keywords")),
        "keywords_any": _as_list(coarse.get("keywords_any")),
        "keywords_exclude": _as_list(coarse.get("keywords_exclude")),
        "years_min": coarse.get("years_min") if coarse.get("years_min") not in (None, "") else 3,
        "years_max": coarse.get("years_max") if coarse.get("years_max") not in (None, "") else 10,
        "list_count": download.get("list_count") or 40,
        "max_details": download.get("max_details") or 10,
        "greet_threshold": _int_or_default(score.get("greet_threshold"), 70),
        "greet_max": max(0, _int_or_default(score.get("greet_max"), 10)),
        "score_profile": normalize_profile_id(score.get("profile") or score.get("score_profile")),
        "tech_stacks": normalize_tech_stacks(score.get("tech_stacks") or score.get("tech_stack")),
    }


def load_form(output_root: Optional[str] = None) -> dict[str, Any]:
    bundle = bundle_file(output_root)
    if bundle.is_file():
        try:
            data = json.loads(bundle.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("jobs"):
                return data
        except Exception:
            pass
    path = rules_file(output_root)
    if path.is_file():
        try:
            return form_from_rules_dict(load_rules(str(path)).to_dict())
        except Exception:
            pass
    return copy.deepcopy(EMPTY_FORM)


def extract_jobs(raw: dict) -> list[dict]:
    jobs = raw.get("jobs")
    if isinstance(jobs, list) and jobs:
        out = []
        for item in jobs:
            if isinstance(item, dict):
                out.append({
                    "query": str(item.get("query") or "").strip(),
                    "jd": str(item.get("jd") or ""),
                })
            elif isinstance(item, str) and item.strip():
                out.append({"query": item.strip(), "jd": ""})
        if out and not any(j.get("query") for j in out):
            job = raw.get("job") or {}
            fallback = str(job.get("query") or raw.get("query") or "").strip()
            if fallback:
                out[0]["query"] = fallback
                if not str(out[0].get("jd") or "").strip():
                    out[0]["jd"] = str(job.get("jd") or raw.get("jd") or "")
        return out or [{"query": "", "jd": ""}]
    job = raw.get("job") or {}
    query = str(job.get("query") or raw.get("query") or "").strip()
    jd = str(job.get("jd") or raw.get("jd") or "")
    return [{"query": query, "jd": jd}]


def rules_payload_for_job(form: dict, job: dict) -> dict:
    education = _as_list(form.get("education"))
    experience = _as_list(form.get("experience"))
    edu = _lowest_education(education)
    years_min = form.get("years_min")
    years_max = form.get("years_max")
    exp_lo, exp_hi = _years_from_experience(experience)
    if years_min in (None, ""):
        years_min = exp_lo
    if years_max in (None, ""):
        years_max = exp_hi
    boss_exp = experience[0] if len(experience) == 1 else map_years_to_boss_experience(
        int(years_min) if years_min not in (None, "") else None,
        int(years_max) if years_max not in (None, "") else None,
    )
    keywords = _as_list(form.get("boss_keywords"))
    any_kw = _as_list(form.get("keywords_any"))
    exclude = _as_list(form.get("keywords_exclude"))
    return {
        "job": {"query": job.get("query") or "", "jd": job.get("jd") or ""},
        "boss_filters": {
            "education": edu or "",
            "experience": boss_exp or "",
            "keywords": " ".join(keywords),
            "age": "",
            "salary": "",
        },
        "coarse_screen": {
            "education_min": edu or "",
            "years_min": years_min,
            "years_max": years_max,
            "keywords_any": any_kw or keywords,
            "keywords_all": [],
            "keywords_exclude": exclude,
            "school_tier_min": _lowest_school_tier(_as_list(form.get("school_tier"))) or "",
        },
        "download": {
            "list_count": form.get("list_count") or 40,
            "max_details": form.get("max_details") or 10,
        },
        "score": {
            "greet_threshold": _int_or_default(form.get("greet_threshold"), 70),
            "greet_max": max(0, _int_or_default(form.get("greet_max"), 10)),
            "profile": normalize_profile_id(form.get("score_profile")),
            "tech_stacks": normalize_tech_stacks(form.get("tech_stacks")),
        },
    }


def build_agent_prompt(
    jobs: list[dict],
    greet_threshold: int = 70,
    greet_max: int = 10,
    score_profile: str = "tech",
    tech_stacks: Optional[list] = None,
) -> str:
    profile = get_profile(score_profile)
    pct = profile.weights_pct
    weight_line = (
        f"学历 {pct['edu']}% / 经验 {pct['exp']}% / 技能 {pct['skill']}% "
        f"/ 项目 {pct['proj']}% / 专业 {pct['major']}%"
    )
    stacks = normalize_tech_stacks(tech_stacks)
    auto_greet = int(greet_max) > 0
    lines = [
        "请按这些规则开始 BOSS 推荐牛人筛选。",
    ]
    if auto_greet:
        lines.append(
            "报告完成后把建议打招呼排行榜给用户看，接着调用 "
            f"boss-hr greet --threshold {int(greet_threshold)} --max {int(greet_max)}。"
        )
        lines.append("不要超过 --max，不要招呼低于阈值的人。")
    else:
        lines.append(
            "报告完成后把建议打招呼排行榜给用户看。"
            "最多打招呼人数为 0，不要调用 boss-hr greet，不要自动打招呼。"
        )
    lines.extend([
        "",
        f"评分标准：{profile.label}。总分权重：{weight_line}。",
        f"LLM 评经验、技能、项目、专业时：{profile.llm_guide}",
        "学历由系统按学校表打分，不要自己改 edu。",
    ])
    if profile.id == "tech":
        if stacks:
            lines.append(
                "本岗位核心技术栈：" + "、".join(stacks) + "。"
                "技能分必须对照这些栈的覆盖与使用深度，不要只看关键词。"
                "核心技术栈严重不匹配则技能分不得打高。"
            )
        else:
            lines.append("本岗位未勾选核心技术栈，技能分按 JD 提取 Must-have。")
    lines.append("")
    if len(jobs) == 1:
        item = jobs[0]
        query = item["query"]
        path = item["rules_path"]
        lines.append(f"规则文件：{path}")
        lines.append(f"岗位：{query}")
        lines.append("")
        lines.append(
            f"用 boss-hr start \"{query}\" --rules \"{path}\"。"
            f"若返回 waiting_user_login，让我在专用浏览器扫码后再重试同一条 start。"
            f"ready_to_fetch 后用返回的 job_name / encrypt_job_id / run_id 跑 "
            + (
                "fetch（同一 --rules）→ score 循环到 scoring_complete → report。"
                "不要 greet。"
                if int(greet_max) <= 0 else
                "fetch（同一 --rules）→ score 循环到 scoring_complete → report → greet。"
            )
        )
        return "\n".join(lines)

    lines.append("下面有多个岗位。每个岗位单独 start 一次新任务，不要混用 run_id。")
    lines.append("")
    for i, item in enumerate(jobs, 1):
        lines.append(f"{i}. 岗位：{item['query']}")
        lines.append(f"   规则文件：{item['rules_path']}")
    lines.append("")
    lines.append(
        "对每个岗位依次：boss-hr start \"<岗位>\" --rules \"<该岗位规则文件>\"；"
        "waiting_user_login 则让我扫码后重试同一条 start；"
        "ready_to_fetch 后用该次返回的 job_name / encrypt_job_id / run_id 跑 "
        + (
            "fetch（同一 --rules）→ score 循环 → report。不要 greet。做完一个再做下一个。"
            if int(greet_max) <= 0 else
            "fetch（同一 --rules）→ score 循环 → report → greet。做完一个再做下一个。"
        )
    )
    return "\n".join(lines)


def save_config(raw: dict, output_root: Optional[str] = None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("请求体必须是 JSON 对象")
    if "jobs" not in raw and "education" not in raw:
        converted = form_from_rules_dict(raw)
        converted["jobs"] = extract_jobs(raw)
        raw = converted
    jobs = extract_jobs(raw)
    named = [j for j in jobs if j.get("query")]
    fallback = str(raw.get("query") or "").strip()
    if not named and fallback:
        named = [{"query": fallback, "jd": str(raw.get("jd") or "")}]
    if not named:
        raise ValueError("请至少填写一个岗位名称、jobId 或 encryptJobId")

    dest_dir = config_dir(output_root)
    dest_dir.mkdir(parents=True, exist_ok=True)
    jobs_dir = dest_dir / "jobs"
    if jobs_dir.is_dir():
        for old in jobs_dir.glob("*/rules.json"):
            try:
                old.unlink()
            except OSError:
                pass

    saved: list[dict] = []
    for i, job in enumerate(named, 1):
        payload = rules_payload_for_job(raw, job)
        rules = rules_from_dict(payload)
        if len(named) == 1:
            dest = rules_file(output_root)
        else:
            folder = jobs_dir / _safe_slug(job["query"], i)
            folder.mkdir(parents=True, exist_ok=True)
            dest = folder / RULES_FILENAME
        save_rules(rules, str(dest))
        saved.append({"query": rules.job_query, "rules_path": str(dest), "jd": rules.jd})

    if len(named) > 1:
        save_rules(rules_from_dict(rules_payload_for_job(raw, named[0])), str(rules_file(output_root)))

    form = {
        "jobs": named,
        "education": _as_list(raw.get("education")),
        "experience": _as_list(raw.get("experience")),
        "school_tier": _as_list(raw.get("school_tier")),
        "boss_keywords": _as_list(raw.get("boss_keywords")),
        "keywords_any": _as_list(raw.get("keywords_any")),
        "keywords_exclude": _as_list(raw.get("keywords_exclude")),
        "years_min": raw.get("years_min"),
        "years_max": raw.get("years_max"),
        "list_count": raw.get("list_count") or 40,
        "max_details": raw.get("max_details") or 10,
        "greet_threshold": _int_or_default(raw.get("greet_threshold"), 70),
        "greet_max": max(0, _int_or_default(raw.get("greet_max"), 10)),
        "score_profile": normalize_profile_id(raw.get("score_profile")),
        "tech_stacks": normalize_tech_stacks(raw.get("tech_stacks")),
    }
    bundle_file(output_root).write_text(
        json.dumps(form, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    prompt = build_agent_prompt(
        saved,
        greet_threshold=form["greet_threshold"],
        greet_max=form["greet_max"],
        score_profile=form["score_profile"],
        tech_stacks=form["tech_stacks"],
    )
    prompt_file(output_root).write_text(prompt, encoding="utf-8")
    return {
        "ok": True,
        "rules_path": saved[0]["rules_path"],
        "jobs": saved,
        "prompt": prompt,
        "job_query": saved[0]["query"],
        "job_count": len(saved),
        "list_count": form["list_count"],
        "max_details": form["max_details"],
        "greet_threshold": form["greet_threshold"],
        "greet_max": form["greet_max"],
        "score_profile": form["score_profile"],
        "tech_stacks": form["tech_stacks"],
    }


class ConfigHandler(BaseHTTPRequestHandler):
    server_version = "BossHrConfig/1.0"
    output_root: str = OUTPUT_ROOT

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[config-ui] " + (fmt % args) + "\n")

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(code, raw, "application/json; charset=utf-8")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            if not INDEX_HTML.is_file():
                self._json(500, {"ok": False, "error": "找不到 index.html"})
                return
            self._send(200, INDEX_HTML.read_bytes(), "text/html; charset=utf-8")
            return
        if parsed.path == "/api/state":
            form = load_form(self.output_root)
            path = rules_file(self.output_root)
            self._json(200, {
                "ok": True,
                "form": form,
                "rules_path": str(path),
                "saved": path.is_file() or bundle_file(self.output_root).is_file(),
            })
            return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/save":
            self._json(404, {"ok": False, "error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > 2_000_000:
            self._json(413, {"ok": False, "error": "内容过大"})
            return
        raw_bytes = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json(400, {"ok": False, "error": "JSON 无法解析"})
            return
        try:
            result = save_config(payload, self.output_root)
        except ValueError as e:
            self._json(400, {"ok": False, "error": str(e)})
            return
        except Exception as e:
            self._json(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})
            return
        self._json(200, result)


def make_server(host: str, port: int, output_root: Optional[str] = None
                ) -> ThreadingHTTPServer:
    handler = ConfigHandler
    handler.output_root = output_root or OUTPUT_ROOT
    return ThreadingHTTPServer((host, port), handler)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="BOSS HR 本地筛选配置页")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args(argv)
    if not INDEX_HTML.is_file():
        sys.stderr.write(f"找不到配置页：{INDEX_HTML}\n")
        return 1
    try:
        httpd = make_server(args.host, args.port)
    except OSError as e:
        sys.stderr.write(f"端口 {args.port} 无法监听：{e}\n")
        return 1
    url = f"http://{args.host}:{httpd.server_address[1]}/"
    sys.stderr.write(f"配置页已启动：{url}\n")
    sys.stderr.write("填完点「交给 Agent」，把提示词贴进 Cursor 对话即可。Ctrl+C 结束。\n")
    if not args.no_open:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\n已关闭配置页。\n")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
