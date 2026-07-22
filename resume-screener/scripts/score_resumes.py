# -*- coding: utf-8 -*-
"""简历评分统一方案（融合 v1.0 框架 + v2.0 LLM 主导）

设计核心：
  - LLM 主导：4 维度（exp/skill/proj/major）由 LLM 真实分析完整简历
  - 脚本辅助：1 维度（edu/学校档次）由 school_tier 查表
  - 公式：5 维度 weighted 求和 = total（按 SKILL.md 权重）
  - 通用：不限岗位
  - 可复现：公式 + 权重 + tier 阈值明确

工作流：
  1. LLM agent 读 test_resumes.json + JD
  2. LLM 真实分析每份简历，评 4 维度（exp/skill/proj/major）
  3. 对每份简历，agent 调 validate_score(score) 收尾
     - 自动用 school_tier 查 edu
     - 自动重算 weighted + total
     - 自动判定 tier
  4. agent 写 _llm_scores.json（4 维度 + signals + gaps + advice）
  5. python score_resumes.py --input _llm_scores.json --output screening_results.json
  6. python generate_html_report.py --input screening_results.json --output report.html

输入 schema（agent 提供，4 维度）：
  [
    {
      "name": str,
      "school_name": str,         # 纯校名（给 school_tier）
      "school": str,              # 报告展示用
      "work_years": str,
      "match_type": str,
      "dims": {
        "exp": 0-100,             # LLM 评
        "skill": 0-100,           # LLM 评
        "proj": 0-100,            # LLM 评
        "major": 0-100            # LLM 评
        # edu 会被自动覆盖
      },
      "signals": [...],            # 兼容旧 schema
      "gaps": [...],               # 兼容旧 schema
      "highlights": [...],         # 新 schema
      "concerns": [...],           # 新 schema
      "advice": str
    }
  ]

输出 schema（screening_results.json）：
  {
    "job_name": str,
    "meta": {
      "title": str, "subtitle": str,
      "job": { "name", "company", "location", "salary", "experience_required", "degree_required" },
      "type_judgment": { "type", "reason" },
      "core_requirements": [str, ...]
    },
    "summary": { "total", "recommend", "pending", "reject" },
    "dimension_labels": [str, ...],
    "candidates": [
      {
        "rank", "name", "tier", "total",
        "school", "work_years", "current_role",
        "hard_pass", "hard_reason",
        "dimensions": [{"pct", "weighted", "weight", "reason"}],
        "highlights": [...],
        "concerns": [...]
      }
    ],
    "actions": {
      "recommend": [{"name", "score", "background", "action"}],
      "pending": [{"name", "score", "strengths", "action"}],
      "reject": [{"name", "score", "concerns"}]
    }
  }
"""
import json
import os
import sys
import io
import argparse
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from school_tier import lookup as school_lookup

# === 5 维度权重（2026-07-21 调整：工作经验 30%→25%，专业匹配 5%→10%）===
WEIGHTS = {"edu": 0.25, "exp": 0.25, "skill": 0.25, "proj": 0.15, "major": 0.10}
WEIGHTS_PCT = {"edu": 25, "exp": 25, "skill": 25, "proj": 15, "major": 10}

# === 维度中文标签（顺序与 WEIGHTS 一致，供报告展示）===
DIM_LABELS = ["学历", "工作经验", "技能", "项目", "专业"]

# === Tier 阈值（SKILL.md 硬性规定）===
TIER_THRESHOLDS = {"推荐": 70, "待定": 60, "不推荐": 0}


# ============================================================
# 核心工具函数（agent 直接 import 调用）
# ============================================================

def calc_tier(total: float) -> str:
    """根据 total 判定 tier"""
    if total >= TIER_THRESHOLDS["推荐"]:
        return "推荐"
    if total >= TIER_THRESHOLDS["待定"]:
        return "待定"
    return "不推荐"


def calc_weighted(dims: dict) -> dict:
    """5 维度 weighted 计算（按 SKILL.md 公式）"""
    return {k: round(dims[k] * WEIGHTS[k], 2) for k in WEIGHTS}


def calc_total(weighted: dict) -> float:
    """5 维度 weighted 求和 = total"""
    return round(sum(weighted.values()), 1)


def _extract_school_name(score: dict) -> str:
    """从 score 智能提取纯校名（不依赖 LLM 守规矩）

    优先级：
    1. school_name 字段（如果非空）
    2. school 字段按常见分隔符拆分（取第一段）

    支持格式：
      - "辽宁工业大学"                       → "辽宁工业大学"
      - "江西理工大学/人工智能/本科"           → "江西理工大学"
      - "辽宁工业大学 · 车辆工程 · 本科"      → "辽宁工业大学"
      - "辽宁工业大学（车辆工程）"            → "辽宁工业大学"
      - "辽宁工业大学(车辆工程)"             → "辽宁工业大学"
    """
    school = score.get("school_name", "").strip()
    if school:
        return school
    school = score.get("school", "").strip()
    if not school:
        return ""
    # 鲁棒拆分：遇到 / · （ ( 中任一个就停
    import re
    m = re.match(r"^([^/·（(]+)", school)
    return m.group(1).strip() if m else school


def validate_score(score: dict) -> dict:
    """LLM 评分收尾（统一方案的核心）

    1. 用 school_tier 强制校准 edu（无论 LLM 是否评了 edu）
       - 自动从 school_name 或 school 提取纯校名（不依赖 LLM 拆字段）
    2. 重算 weighted + total（按公式）
    3. 判定 tier

    输入：5 维度（edu 可被忽略）或 4 维度的 LLM 评分
    输出：5 维度评分 + tier（edu 来自 school_tier）
    """
    school = _extract_school_name(score)
    if school:
        info = school_lookup(school)
        if info["score"] is not None:
            score["dims"]["edu"] = info["score"]
            score["dims_edu_reason"] = f"{info['tier']}（school_tier 查询：{school}）"
        else:
            score["dims_edu_reason"] = f"缺失（{school} 不在学校表）"
    else:
        score["dims_edu_reason"] = "缺失（无学校名）"

    score["weighted"] = calc_weighted(score["dims"])
    score["total"] = calc_total(score["weighted"])
    score["tier"] = calc_tier(score["total"])
    return score


# ============================================================
# Schema 转换
# ============================================================

def candidate_to_report(c: dict, rank: int) -> dict:
    """把 1 份评分（list 形式）转成报告 candidates[] 形式"""
    dims = c["dims"]
    weighted = c["weighted"]
    return {
        "rank": rank,
        "name": c["name"],
        "tier": c["tier"],
        "total": c["total"],
        "hard_pass": c.get("hard_pass", True),
        "hard_reason": c.get("hard_reason"),
        "school": c.get("school", c.get("school_name", "")),
        "work_years": c.get("work_years", ""),
        "current_role": c.get("match_type", ""),
        "dimensions": [
            {
                "pct": dims[k],
                "weighted": weighted[k],
                "weight": WEIGHTS_PCT[k],
                "reason": c.get(f"dims_{k}_reason", "")
            }
            for k in ["edu", "exp", "skill", "proj", "major"]
        ],
        "highlights": c.get("highlights", c.get("signals", [])),
        "concerns": c.get("concerns", c.get("gaps", [])),
    }


def build_actions(candidates: list) -> dict:
    """从 candidates 生成 actions 三段式"""
    recommend, pending, reject = [], [], []
    for c in candidates:
        item = {"name": c["name"], "score": c["total"]}
        signals = c.get("highlights", c.get("signals", []))
        gaps = c.get("concerns", c.get("gaps", []))
        if c["tier"] == "推荐":
            item["background"] = "、".join(signals[:3]) if signals else "—"
            item["action"] = c.get("advice", "")
            recommend.append(item)
        elif c["tier"] == "待定":
            item["strengths"] = "、".join(signals[:3]) if signals else "—"
            item["action"] = c.get("advice", "")
            pending.append(item)
        else:
            item["concerns"] = "、".join(gaps[:2]) if gaps else "—"
            reject.append(item)
    return {"recommend": recommend, "pending": pending, "reject": reject}


def build_meta(job_name: str, job_info: dict = None) -> dict:
    """构造报告 meta（agent 可重写）"""
    job = job_info or {}
    return {
        "title": f"{job_name} · 简历筛选报告",
        "subtitle": "LLM 主导评分 + school_tier 学历分档校准",
        "job": {
            "name": job_name,
            "company": job.get("company", ""),
            "location": job.get("location", ""),
            "salary": job.get("salary", ""),
            "experience_required": job.get("experience_required", ""),
            "degree_required": job.get("degree_required", ""),
        },
        "type_judgment": job.get("type_judgment", {
            "type": "技术岗",
            "reason": "JD 明确要求结构设计 + 仿真 + 工艺核心技术能力"
        }),
        "core_requirements": job.get("core_requirements", []),
    }


# ============================================================
# CLI 入口
# ============================================================

def main():
    ap = argparse.ArgumentParser(description="简历评分统一方案（LLM 4 维度 + school_tier 校准）")
    ap.add_argument("--input", required=True, help="LLM 评分 JSON（4 维度）")
    ap.add_argument("--output", required=True, help="标准化后的 screening_results.json（5 维度 + tier）")
    ap.add_argument("--job-name", default="工程师", help="岗位名")
    ap.add_argument("--job-info", default=None, help="JD 完整信息 JSON 字符串（可选）")
    args = ap.parse_args()

    data = json.load(open(args.input, encoding="utf-8"))
    if not isinstance(data, list):
        print("错误：输入 JSON 必须是候选人数组")
        return

    # 对每份评分收尾（强制用 school_tier 校准 edu + 重算 total + 判定 tier）
    for c in data:
        validate_score(c)

    # 按 total 倒序
    data.sort(key=lambda x: -x["total"])

    # 统计
    summary = {
        "total": len(data),
        "recommend": sum(1 for c in data if c["tier"] == "推荐"),
        "pending": sum(1 for c in data if c["tier"] == "待定"),
        "reject": sum(1 for c in data if c["tier"] == "不推荐"),
    }

    # 转 candidates 格式
    candidates = [candidate_to_report(c, i + 1) for i, c in enumerate(data)]
    actions = build_actions(candidates)

    # 解析 job_info（可选）
    job_info = json.loads(args.job_info) if args.job_info else {}

    # 组装 screening_results.json
    output = {
        "job_name": args.job_name,
        "meta": build_meta(args.job_name, job_info),
        "summary": summary,
        "dimension_labels": DIM_LABELS,
        "candidates": candidates,
        "actions": actions,
    }

    Path(args.output).write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"✓ 处理 {len(data)} 份评分")
    print(f"  推荐 {summary['recommend']} / 待定 {summary['pending']} / 不推荐 {summary['reject']}")
    print(f"  输出: {args.output}")


if __name__ == "__main__":
    # win32 控制台中文编码保障（避免 GBK 乱码）；放 __main__ 内确保被 import 时不触发
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    main()
