# -*- coding: utf-8 -*-
"""筛选规则：加载 JSON、映射 BOSS 筛选器、对推荐卡片做粗筛。

规则文件示例见 examples/rules.json。
不依赖 patchright；fetch / list 在连上浏览器后再调用 recommend_filters。
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from score_profiles import normalize_profile_id, normalize_tech_stacks


DEGREE_RANK = {
    "不限": 0,
    "高中": 1,
    "中专": 1,
    "中技": 1,
    "大专": 2,
    "专科": 2,
    "本科": 3,
    "学士": 3,
    "硕士": 4,
    "研究生": 4,
    "博士": 5,
    "博士后": 6,
}

TIER_MIN_SCORE = {
    "C9": 100,
    "985": 92,
    "211": 85,
    "双一流": 77,
    "一本公办": 71,
    "二本公办": 62,
    "民办本科": 53,
    "民办": 53,
}

BOSS_EXPERIENCE_OPTIONS = (
    "在校/应届",
    "1年以内",
    "1-3年",
    "3-5年",
    "5-10年",
    "10年以上",
)

BOSS_EDUCATION_OPTIONS = ("大专", "本科", "硕士", "博士")


@dataclass
class ScreeningRules:
    job_query: str = ""
    jd: str = ""
    boss_education: Optional[str] = None
    boss_experience: Optional[str] = None
    boss_keywords: str = ""
    boss_age: Optional[str] = None
    boss_salary: Optional[str] = None
    education_min: Optional[str] = None
    years_min: Optional[int] = None
    years_max: Optional[int] = None
    keywords_any: list[str] = field(default_factory=list)
    keywords_all: list[str] = field(default_factory=list)
    keywords_exclude: list[str] = field(default_factory=list)
    school_tier_min: Optional[str] = None
    list_count: int = 40
    max_details: int = 10
    greet_threshold: int = 70
    greet_max: int = 10
    score_profile: str = "tech"
    tech_stacks: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "job": {"query": self.job_query, "jd": self.jd},
            "boss_filters": {
                "education": self.boss_education,
                "experience": self.boss_experience,
                "keywords": self.boss_keywords,
                "age": self.boss_age,
                "salary": self.boss_salary,
            },
            "coarse_screen": {
                "education_min": self.education_min,
                "years_min": self.years_min,
                "years_max": self.years_max,
                "keywords_any": self.keywords_any,
                "keywords_all": self.keywords_all,
                "keywords_exclude": self.keywords_exclude,
                "school_tier_min": self.school_tier_min,
            },
            "download": {
                "list_count": self.list_count,
                "max_details": self.max_details,
            },
            "score": {
                "greet_threshold": self.greet_threshold,
                "greet_max": self.greet_max,
                "profile": self.score_profile,
                "tech_stacks": list(self.tech_stacks),
            },
        }


def _as_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    m = re.search(r"-?\d+", str(value))
    return int(m.group(0)) if m else None


def _as_str_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        parts = re.split(r"[,，、\s]+", value)
        return [p.strip() for p in parts if p.strip()]
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return [str(value).strip()]


def map_years_to_boss_experience(years_min: Optional[int],
                                 years_max: Optional[int]) -> Optional[str]:
    """把年限区间映射到 BOSS 推荐页常见的经验档。"""
    if years_min is None and years_max is None:
        return None
    lo = 0 if years_min is None else int(years_min)
    hi = 99 if years_max is None else int(years_max)
    if hi <= 0:
        return "在校/应届"
    if hi <= 1 and lo <= 1:
        return "1年以内"
    if lo >= 10:
        return "10年以上"
    if lo >= 5 or (lo >= 4 and hi >= 10):
        return "5-10年"
    if lo >= 3 or (lo >= 2 and hi >= 5):
        return "3-5年"
    return "1-3年"


def normalize_education(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip()
    for name, rank in sorted(DEGREE_RANK.items(), key=lambda kv: -len(kv[0])):
        if name in text:
            if name in ("不限",):
                return None
            if name in ("专科",):
                return "大专"
            if name in ("学士",):
                return "本科"
            if name in ("研究生",):
                return "硕士"
            if name in BOSS_EDUCATION_OPTIONS or name in DEGREE_RANK:
                if name in BOSS_EDUCATION_OPTIONS:
                    return name
                return name
    return text


def load_rules(path: str) -> ScreeningRules:
    if not path or not os.path.isfile(path):
        raise FileNotFoundError(f"规则文件不存在：{path}")
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ValueError("规则文件必须是 JSON 对象")
    return rules_from_dict(raw)


def rules_from_dict(raw: dict) -> ScreeningRules:
    job = raw.get("job") or {}
    boss = raw.get("boss_filters") or {}
    coarse = raw.get("coarse_screen") or {}
    download = raw.get("download") or {}
    score = raw.get("score") or {}

    years_min = _as_int(coarse.get("years_min"))
    years_max = _as_int(coarse.get("years_max"))
    education_min = normalize_education(coarse.get("education_min") or boss.get("education"))
    boss_education = normalize_education(boss.get("education") or coarse.get("education_min"))
    boss_experience = boss.get("experience") or map_years_to_boss_experience(years_min, years_max)
    if boss_experience and boss_experience not in BOSS_EXPERIENCE_OPTIONS:
        boss_experience = map_years_to_boss_experience(years_min, years_max)

    list_count = _as_int(download.get("list_count")) or 40
    max_details = _as_int(download.get("max_details")) or 10
    greet_threshold = _as_int(score.get("greet_threshold")) or 70
    greet_max = _as_int(score.get("greet_max") if score.get("greet_max") is not None else score.get("max"))
    if greet_max is None:
        greet_max = 10
    else:
        greet_max = max(0, greet_max)
    score_profile = normalize_profile_id(score.get("profile") or score.get("score_profile"))
    tech_stacks = normalize_tech_stacks(score.get("tech_stacks") or score.get("tech_stack"))

    return ScreeningRules(
        job_query=str(job.get("query") or "").strip(),
        jd=str(job.get("jd") or "").strip(),
        boss_education=boss_education,
        boss_experience=boss_experience,
        boss_keywords=str(boss.get("keywords") or "").strip(),
        boss_age=str(boss.get("age") or "").strip() or None,
        boss_salary=str(boss.get("salary") or "").strip() or None,
        education_min=education_min,
        years_min=years_min,
        years_max=years_max,
        keywords_any=_as_str_list(coarse.get("keywords_any") or boss.get("keywords")),
        keywords_all=_as_str_list(coarse.get("keywords_all")),
        keywords_exclude=_as_str_list(coarse.get("keywords_exclude")),
        school_tier_min=(str(coarse.get("school_tier_min")).strip()
                         if coarse.get("school_tier_min") else None),
        list_count=max(1, list_count),
        max_details=max(1, max_details),
        greet_threshold=greet_threshold,
        greet_max=greet_max,
        score_profile=score_profile,
        tech_stacks=tech_stacks,
        raw=raw,
    )


def save_rules(rules: ScreeningRules, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rules.to_dict(), f, ensure_ascii=False, indent=2)


def _walk_strings(obj: Any, acc: list[str]) -> None:
    if obj is None:
        return
    if isinstance(obj, str):
        if obj.strip():
            acc.append(obj.strip())
        return
    if isinstance(obj, dict):
        for v in obj.values():
            _walk_strings(v, acc)
        return
    if isinstance(obj, (list, tuple)):
        for v in obj:
            _walk_strings(v, acc)


def card_blob(geek: dict) -> str:
    parts: list[str] = []
    _walk_strings(geek, parts)
    return " ".join(parts).lower()


def extract_degree_text(geek: dict) -> str:
    gc = geek.get("geekCard") or {}
    for src in (gc, geek):
        for key in ("geekDegree", "degreeName", "degree", "eduLevel", "highestDegree"):
            v = src.get(key)
            if v:
                return str(v)
    return ""


def extract_years(geek: dict) -> Optional[float]:
    gc = geek.get("geekCard") or {}
    for src in (gc, geek):
        for key in ("geekWorkYear", "workYear", "workYearDesc", "work_years", "year"):
            v = src.get(key)
            if v is None or v == "":
                continue
            if isinstance(v, (int, float)):
                return float(v)
            text = str(v)
            if any(x in text for x in ("应届", "在校", "实习")):
                return 0.0
            m = re.search(r"(\d+(?:\.\d+)?)", text)
            if m:
                return float(m.group(1))
    return None


def extract_school_name(geek: dict) -> str:
    gc = geek.get("geekCard") or {}
    for src in (gc, geek):
        for key in ("school", "geekSchool", "schoolName"):
            v = src.get(key)
            if v:
                return str(v).split("/")[0].strip()
    edu = geek.get("education") or gc.get("education") or []
    if isinstance(edu, list) and edu:
        first = edu[0] if isinstance(edu[0], dict) else {}
        return str(first.get("school") or "").split("/")[0].strip()
    return ""


def degree_rank(text: str) -> Optional[int]:
    if not text:
        return None
    best = None
    for name, rank in DEGREE_RANK.items():
        if name in text:
            if best is None or rank > best:
                best = rank
    return best


def _school_tier_score(school: str) -> Optional[int]:
    if not school:
        return None
    try:
        from school_tier import lookup
    except ImportError:
        scripts = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "resume-screener", "scripts",
        )
        import sys
        sys.path.insert(0, os.path.abspath(scripts))
        try:
            from school_tier import lookup
        except ImportError:
            return None
    info = lookup(school) or {}
    score = info.get("score")
    return int(score) if isinstance(score, (int, float)) else None


def coarse_screen_one(geek: dict, rules: ScreeningRules) -> dict:
    """返回 {pass: bool, reasons: [str]}。卡片上看不到的字段不否决。"""
    reasons: list[str] = []
    blob = card_blob(geek)

    degree_text = extract_degree_text(geek)
    got_rank = degree_rank(degree_text)
    need_rank = degree_rank(rules.education_min or "")
    if need_rank is not None and got_rank is not None and got_rank < need_rank:
        reasons.append(f"学历不足：{degree_text or '未知'} < {rules.education_min}")

    years = extract_years(geek)
    if years is not None:
        if rules.years_min is not None and years < rules.years_min:
            reasons.append(f"年限不足：{years} < {rules.years_min}")
        if rules.years_max is not None and years > rules.years_max:
            reasons.append(f"年限超出：{years} > {rules.years_max}")

    if rules.keywords_exclude:
        hit = [k for k in rules.keywords_exclude if k.lower() in blob]
        if hit:
            reasons.append("命中排除词：" + "、".join(hit))

    if rules.keywords_all:
        missing = [k for k in rules.keywords_all if k.lower() not in blob]
        if missing:
            reasons.append("缺少必选关键词：" + "、".join(missing))

    # keywords_any：卡片上完全看不到任何关键词时不否决（信息太薄）
    if rules.keywords_any:
        visible_any = [k for k in rules.keywords_any if k.lower() in blob]
        # 只有卡片明显在讲别的方向、且一个关键词都没有时，仍然放过
        # （JD 细匹配放到详情）。这里仅在「出现了排除性岗位词且无任何 any」时不额外否决。
        _ = visible_any

    if rules.school_tier_min:
        school = extract_school_name(geek)
        need = TIER_MIN_SCORE.get(rules.school_tier_min, None)
        if need is not None and school:
            got = _school_tier_score(school)
            if got is not None and got < need:
                reasons.append(
                    f"院校档次不足：{school} < {rules.school_tier_min}"
                )

    return {"pass": not reasons, "reasons": reasons}


def coarse_screen_list(geeks: list, rules: ScreeningRules) -> dict:
    passed: list = []
    rejected: list = []
    for g in geeks:
        if not isinstance(g, dict):
            continue
        result = coarse_screen_one(g, rules)
        item = {
            "encryptGeekId": g.get("encryptGeekId") or g.get("uid") or "",
            "name": (g.get("geekCard") or {}).get("geekName") or g.get("name") or "",
            "reasons": result["reasons"],
            "raw": g,
        }
        if result["pass"]:
            passed.append(g)
        else:
            rejected.append(item)
    return {
        "passed": passed,
        "rejected": rejected,
        "passed_count": len(passed),
        "rejected_count": len(rejected),
        "listed_count": len(geeks),
    }


def parse_geek_info_payload(data: dict, *, geek_id: str = "",
                            job_id: str = "") -> dict:
    """把 BOSS view/geek/info JSON 收成评分用简历结构。"""
    if not isinstance(data, dict):
        return {"ok": False, "error": "empty"}
    if data.get("code") not in (0, None) and not data.get("zpData"):
        return {"ok": False, "error": str(data.get("message") or "unknown")}
    zp = data.get("zpData") or data
    if zp.get("blockDialog") and zp["blockDialog"].get("title"):
        return {"ok": False, "error": zp["blockDialog"]["title"], "limit": True}
    d = zp.get("geekDetailInfo") or zp
    b = d.get("geekBaseInfo") or {}
    return {
        "ok": True,
        "name": b.get("name") or "",
        "age": b.get("ageDesc") or "",
        "degree": b.get("degreeCategory") or "",
        "work_years": b.get("workYearDesc") or "",
        "expectation": d.get("anonymousGeekExpect") or d.get("geekExpect") or None,
        "work_experience": [
            {
                "company": w.get("company") or "",
                "position": w.get("positionName") or "",
                "department": w.get("department") or "",
                "start": w.get("startDate") or "",
                "end": w.get("endDate") or "",
                "duration": w.get("workYearDesc") or "",
                "responsibility": w.get("responsibility") or "",
                "performance": w.get("performance") or "",
                "keywords": w.get("tagList") or w.get("keywords") or [],
            }
            for w in (d.get("geekWorkExpList") or [])
        ],
        "project_experience": [
            {
                "name": p.get("projName") or p.get("name") or "",
                "role": p.get("projRole") or p.get("role") or "",
                "start": p.get("startDate") or "",
                "end": p.get("endDate") or "",
                "duration": p.get("projYearDesc") or "",
                "description": p.get("projDesc") or p.get("description") or "",
                "achievement": p.get("projAchieve") or p.get("achievement") or "",
            }
            for p in (d.get("geekProjExpList") or [])
        ],
        "education": [
            {
                "school": e.get("school") or "",
                "major": e.get("major") or "",
                "degree": e.get("degreeName") or "",
                "start": e.get("startDate") or "",
                "end": e.get("endDate") or "",
            }
            for e in (d.get("geekEduExpList") or [])
        ],
        "certifications": [
            c.get("certName") or c.get("name") or ""
            for c in (d.get("geekCertificationList") or [])
        ],
        "skills": d.get("professionalSkill") or "",
        "active_status": b.get("activeTimeDesc") or "",
        "user_desc": d.get("geekDesc") or b.get("userDesc") or "",
    }
