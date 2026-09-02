# -*- coding: utf-8 -*-
"""岗位类型对应的评分权重。

5 个维度不变（edu / exp / skill / proj / major），按类型换权重和打分口径。
学历仍由 school_tier 查表；LLM 只评经验、技能、项目、专业。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

DIM_KEYS = ("edu", "exp", "skill", "proj", "major")
DEFAULT_PROFILE = "tech"

# 技术岗核心技术栈清单（配置页多选；对照 jishu.md 应用研发 / 内核拆分）
TECH_STACK_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "语言 / 运行时",
        (
            "C++",
            "Java",
            "Python",
            "JavaScript / TypeScript",
            "Node.js",
            "Go",
            "Spark",
        ),
    ),
    (
        "前端",
        ("React", "Vue"),
    ),
    (
        "数据 / 系统",
        (
            "SQL / 常见数据库",
            "图数据库",
            "数据库内核",
            "Query Engine / Optimizer",
            "Storage Engine",
            "分布式系统",
            "分布式数据库",
        ),
    ),
    (
        "领域 / AI",
        (
            "图计算 / 图算法",
            "知识图谱",
            "性能优化",
            "风控 / 反欺诈",
            "AI 应用开发",
            "AI Agent",
            "AI Coding",
        ),
    ),
)
TECH_STACKS: tuple[str, ...] = tuple(
    item for _, items in TECH_STACK_GROUPS for item in items
)
_STACK_BY_LOWER = {name.lower(): name for name in TECH_STACKS}
_STACK_ALIASES = {
    "js": "JavaScript / TypeScript",
    "ts": "JavaScript / TypeScript",
    "javascript": "JavaScript / TypeScript",
    "typescript": "JavaScript / TypeScript",
    "node": "Node.js",
    "nodejs": "Node.js",
    "cpp": "C++",
    "c++": "C++",
    "sql": "SQL / 常见数据库",
    "常见数据库": "SQL / 常见数据库",
    "query engine": "Query Engine / Optimizer",
    "optimizer": "Query Engine / Optimizer",
    "查询优化器": "Query Engine / Optimizer",
    "storage": "Storage Engine",
    "图计算": "图计算 / 图算法",
    "图算法": "图计算 / 图算法",
    "风控": "风控 / 反欺诈",
    "反欺诈": "风控 / 反欺诈",
    "反洗钱": "风控 / 反欺诈",
    "ai": "AI 应用开发",
    "ai coding": "AI Coding",
}


def normalize_tech_stacks(value: Any) -> list[str]:
    """把表单/规则里的技术栈规范成清单中的名字，去重、丢掉未知项。"""
    if not value:
        return []
    if isinstance(value, str):
        raw = [p.strip() for p in re.split(r"[,，、]+", value) if p.strip()]
    elif isinstance(value, (list, tuple)):
        raw = [str(x).strip() for x in value if str(x).strip()]
    else:
        raw = [str(value).strip()]
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        name = _STACK_BY_LOWER.get(item.lower()) or _STACK_ALIASES.get(item.lower())
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out

_ALIASES = {
    "tech": "tech",
    "技术": "tech",
    "技术类": "tech",
    "技术岗": "tech",
    "技术类岗位": "tech",
    "sales": "sales",
    "销售": "sales",
    "销售类": "sales",
    "销售岗": "sales",
    "销售类岗位": "sales",
    "intern": "intern",
    "实习": "intern",
    "实习生": "intern",
    "实习岗": "intern",
    "实习生岗位": "intern",
}


@dataclass(frozen=True)
class ScoreProfile:
    id: str
    label: str
    summary: str
    weights: dict[str, float]
    recommend: int
    pending: int
    dim_help: dict[str, str]
    llm_guide: str

    @property
    def weights_pct(self) -> dict[str, int]:
        return {k: int(round(self.weights[k] * 100)) for k in DIM_KEYS}

    @property
    def thresholds(self) -> dict[str, int]:
        return {"推荐": self.recommend, "待定": self.pending, "不推荐": 0}


PROFILES: dict[str, ScoreProfile] = {
    "tech": ScoreProfile(
        id="tech",
        label="技术类岗位",
        summary="学校、经验和硬技能并重，项目看是不是主力。",
        weights={"edu": 0.25, "exp": 0.25, "skill": 0.25, "proj": 0.15, "major": 0.10},
        recommend=70,
        pending=60,
        dim_help={
            "edu": "系统查表：C9 100、985 92、211 85、双一流 77、一本公办 71。硕士/博士另有加成。",
            "exp": "年限够不够、活跟这个岗对不对口、能不能独立扛一块。",
            "skill": "对照勾选的核心技术栈，看覆盖和实际使用深度，不要只看关键词。",
            "proj": "项目跟本岗相关吗、难不难、Ta 是主力还是打杂。",
            "major": "大学专业是否对口。",
        },
        llm_guide=(
            "按技术岗口径评经验、技能、项目、专业。"
            "经验看年限与岗位对口深度；"
            "技能对照规则里勾选的核心技术栈（没有勾选则按 JD 提取），"
            "看覆盖与使用深度（S 能独立设计优化，A 完整项目，B 常规使用，"
            "C 了解，D 仅提及），不要只看关键词；核心技术栈严重不匹配则技能分不得打高；"
            "项目看相关度、难度、是否主力；专业看工科/对口专业。"
        ),
    ),
    "sales": ScoreProfile(
        id="sales",
        label="销售类岗位",
        summary="更看业绩、客户和行业经验，学校档次权重较低。",
        weights={"edu": 0.10, "exp": 0.35, "skill": 0.25, "proj": 0.20, "major": 0.10},
        recommend=70,
        pending=60,
        dim_help={
            "edu": "学校仍按系统查表，但只占 10%。二本但能打仗的，不要被学校压死。",
            "exp": "销售年限、行业是否对口、有没有稳定业绩（成交额、quota、客户量）。",
            "skill": "客户开发、谈判、资源、CRM 等 JD 要求覆盖了多少。",
            "proj": "成交案例、大客户、渠道开拓。把这些当「项目」来看。",
            "major": "不卡死营销专业；相关行业背景也可以。",
        },
        llm_guide=(
            "按销售岗口径评经验、技能、项目、专业。"
            "经验看销售年限、行业与业绩（成交、quota、客户），不要只看总工龄；"
            "技能看客户开发、谈判、资源、CRM 等 JD 要求；"
            "项目把成交案例、大客户、渠道开拓当项目经历；"
            "专业不卡死营销专业。学校一般但业绩硬的，经验/项目分要打上去。"
        ),
    ),
    "intern": ScoreProfile(
        id="intern",
        label="实习生岗位",
        summary="更看学校、专业和课设/实习项目，不要用职场年限卡应届。",
        weights={"edu": 0.30, "exp": 0.10, "skill": 0.20, "proj": 0.20, "major": 0.20},
        recommend=70,
        pending=60,
        dim_help={
            "edu": "学校档次仍按系统查表；实习生招人时学校权重更高。",
            "exp": "把实习、课设、竞赛当经验。不要因为应届或 0 年工龄打到不及格。",
            "skill": "看课程、工具和基础，不拿 5 年职场标准卡人。",
            "proj": "课设、实习项目、竞赛都可以，看相关度和本人贡献。",
            "major": "专业对口更重要，权重更高。",
        },
        llm_guide=(
            "按实习生口径评经验、技能、项目、专业。"
            "经验把实习、课程设计、竞赛算进去，不要因为应届/0 年压到不及格；"
            "技能看课程与工具基础，不按资深职场标准；"
            "项目看课设、实习项目、竞赛的相关度与贡献；"
            "专业对口更重要。学校档次由系统查表，不要自己改 edu。"
        ),
    ),
}


def normalize_profile_id(value: Optional[str]) -> str:
    if value is None or str(value).strip() == "":
        return DEFAULT_PROFILE
    text = str(value).strip().lower()
    if text in PROFILES:
        return text
    return _ALIASES.get(str(value).strip(), DEFAULT_PROFILE)


def get_profile(value: Optional[str] = None) -> ScoreProfile:
    return PROFILES[normalize_profile_id(value)]


def assert_profiles_valid() -> None:
    for profile in PROFILES.values():
        if set(profile.weights) != set(DIM_KEYS):
            raise ValueError(f"{profile.id} 权重维度不完整")
        total = sum(profile.weights.values())
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"{profile.id} 权重之和为 {total}，必须为 1.0")
        if sum(profile.weights_pct.values()) != 100:
            raise ValueError(f"{profile.id} 百分比之和不是 100")
