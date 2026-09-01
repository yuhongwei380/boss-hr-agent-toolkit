# -*- coding: utf-8 -*-
"""推荐牛人页：点「推荐」Tab + 能映射到的 BOSS 筛选器。

原则：点得到就点，点不到记 skipped 并继续。禁止为了点筛选项猜坐标。
必须用 page.mouse.click（拟人），不用 element.click()。
"""
from __future__ import annotations

import random
import time

from human_interaction import human_move, human_move_and_click


RECOMMEND_URL = "https://www.zhipin.com/web/chat/recommend"


def _iframe_and_frame(page):
    iframe = None
    for _ in range(15):
        try:
            iframe = page.query_selector("iframe")
            if iframe:
                break
        except Exception:
            pass
        time.sleep(1)
    if not iframe:
        return None, None, None
    frame = iframe.content_frame()
    box = iframe.bounding_box()
    return iframe, frame, box


def ensure_recommend_page(page) -> None:
    url = page.url or ""
    if "zhipin.com/web/chat/recommend" not in url:
        page.goto(RECOMMEND_URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)


def _click_text(page, frame, iframe_box, text, *, exact=True, timeout=2500) -> bool:
    """在 iframe 内按可见文本拟人点击。"""
    if frame is None:
        return False
    try:
        loc = frame.get_by_text(text, exact=exact)
        if loc.count() == 0:
            return False
        target = loc.first
        box = target.bounding_box()
        if not box:
            try:
                target.scroll_into_view_if_needed(timeout=timeout)
            except Exception:
                pass
            box = target.bounding_box()
        if not box:
            return False
        ox = iframe_box["x"] if iframe_box else 0
        oy = iframe_box["y"] if iframe_box else 0
        pt = (
            ox + box["x"] + box["width"] * random.uniform(0.3, 0.7),
            oy + box["y"] + box["height"] * random.uniform(0.3, 0.7),
        )
        human_move(page, pt)
        time.sleep(random.uniform(0.08, 0.2))
        page.mouse.click(pt[0], pt[1])
        time.sleep(random.uniform(0.4, 0.9))
        return True
    except Exception:
        return False


def click_recommend_tab(page, frame, iframe_box) -> bool:
    """点「推荐」Tab。失败返回 False，不抛。"""
    for label in ("推荐", "推荐牛人"):
        if _click_text(page, frame, iframe_box, label, exact=True):
            time.sleep(1.2)
            return True
    # 宽松：class 含 tab
    try:
        if human_move_and_click(
            page,
            'div[class*="tab"]:has-text("推荐"), li[class*="tab"]:has-text("推荐")',
            frame=frame,
            iframe_box=iframe_box,
            timeout=2500,
        ):
            time.sleep(1.2)
            return True
    except Exception:
        pass
    return False


def _open_filter_and_pick(page, frame, iframe_box, filter_label, option_text) -> bool:
    if not _click_text(page, frame, iframe_box, filter_label, exact=True):
        if not _click_text(page, frame, iframe_box, filter_label, exact=False):
            return False
    time.sleep(0.4)
    if _click_text(page, frame, iframe_box, option_text, exact=True):
        time.sleep(0.8)
        return True
    return _click_text(page, frame, iframe_box, option_text, exact=False)


def _fill_keyword_search(page, frame, iframe_box, keywords: str) -> bool:
    if not keywords or frame is None:
        return False
    selectors = [
        'input[placeholder*="关键词"]',
        'input[placeholder*="搜索"]',
        'input[type="search"]',
        'input[class*="search"]',
    ]
    for sel in selectors:
        try:
            el = frame.query_selector(sel)
            if not el:
                continue
            box = el.bounding_box()
            if not box:
                continue
            ox = iframe_box["x"] if iframe_box else 0
            oy = iframe_box["y"] if iframe_box else 0
            pt = (ox + box["x"] + box["width"] * 0.5, oy + box["y"] + box["height"] * 0.5)
            human_move(page, pt)
            page.mouse.click(pt[0], pt[1])
            time.sleep(0.2)
            try:
                el.fill("")
                el.type(keywords, delay=random.randint(40, 90))
            except Exception:
                page.keyboard.type(keywords, delay=random.randint(40, 90))
            page.keyboard.press("Enter")
            time.sleep(1.2)
            return True
        except Exception:
            continue
    return False


def apply_recommend_filters(page, rules) -> dict:
    """在当前 page 上点推荐 Tab 并应用能映射的筛选器。

    rules: shared.screening_rules.ScreeningRules
    返回 applied_filters 结构（写入 process/applied_filters.json）。
    """
    log = {
        "tab_clicked": False,
        "applied": [],
        "skipped": [],
        "errors": [],
    }
    ensure_recommend_page(page)
    _iframe, frame, iframe_box = _iframe_and_frame(page)
    if frame is None:
        log["errors"].append("未找到推荐页 iframe")
        return log

    log["tab_clicked"] = click_recommend_tab(page, frame, iframe_box)
    if not log["tab_clicked"]:
        log["skipped"].append({"filter": "tab", "reason": "未找到「推荐」Tab，继续用当前列表"})

    if getattr(rules, "boss_keywords", ""):
        if _fill_keyword_search(page, frame, iframe_box, rules.boss_keywords):
            log["applied"].append({"filter": "keywords", "value": rules.boss_keywords})
        else:
            log["skipped"].append({"filter": "keywords", "value": rules.boss_keywords,
                                   "reason": "未找到关键词搜索框"})

    if getattr(rules, "boss_education", None):
        if _open_filter_and_pick(page, frame, iframe_box, "学历", rules.boss_education):
            log["applied"].append({"filter": "education", "value": rules.boss_education})
        else:
            log["skipped"].append({"filter": "education", "value": rules.boss_education,
                                   "reason": "未找到学历筛选器或选项"})

    if getattr(rules, "boss_experience", None):
        picked = False
        for label in ("经验", "工作经验", "工作年限"):
            if _open_filter_and_pick(page, frame, iframe_box, label, rules.boss_experience):
                log["applied"].append({"filter": "experience", "value": rules.boss_experience})
                picked = True
                break
        if not picked:
            log["skipped"].append({"filter": "experience", "value": rules.boss_experience,
                                   "reason": "未找到经验筛选器或选项"})

    if getattr(rules, "boss_age", None):
        if _open_filter_and_pick(page, frame, iframe_box, "年龄", rules.boss_age):
            log["applied"].append({"filter": "age", "value": rules.boss_age})
        else:
            log["skipped"].append({"filter": "age", "value": rules.boss_age,
                                   "reason": "未找到年龄筛选器或选项"})

    if getattr(rules, "boss_salary", None):
        if _open_filter_and_pick(page, frame, iframe_box, "薪资", rules.boss_salary):
            log["applied"].append({"filter": "salary", "value": rules.boss_salary})
        else:
            log["skipped"].append({"filter": "salary", "value": rules.boss_salary,
                                   "reason": "未找到薪资筛选器或选项"})

    time.sleep(1.5)
    return log


def click_card_by_geek_id(page, frame, iframe_box, geek_id: str) -> bool:
    """拟人点击列表卡片（不是打招呼按钮）。"""
    if not geek_id or frame is None:
        return False
    box = None
    try:
        box = frame.evaluate(
            """(gid) => {
                const cards = document.querySelectorAll(
                    'li.card-item, li[class*="card"], div[class*="card-item"]'
                );
                for (const card of cards) {
                    let id = card.getAttribute('data-geek')
                          || card.getAttribute('data-geekid')
                          || card.getAttribute('data-geek-id')
                          || '';
                    if (!id) {
                        const tagged = card.querySelector(
                            '[data-geek], [data-geekid], [data-geek-id]'
                        );
                        if (tagged) {
                            id = tagged.getAttribute('data-geek')
                              || tagged.getAttribute('data-geekid')
                              || tagged.getAttribute('data-geek-id')
                              || '';
                        }
                    }
                    if (!id) {
                        const anchors = card.querySelectorAll('a[href]');
                        for (const a of anchors) {
                            const href = a.getAttribute('href') || '';
                            const m = href.match(/[?&](?:geekId|encryptGeekId)=([^&]+)/);
                            if (m) { id = decodeURIComponent(m[1]); break; }
                        }
                    }
                    if (id && id === gid) {
                        const r = card.getBoundingClientRect();
                        return {x: r.x, y: r.y, w: r.width, h: r.height};
                    }
                }
                return null;
            }""",
            geek_id,
        )
    except Exception:
        box = None
    if not box:
        return False
    try:
        frame.evaluate(
            "(y) => window.scrollTo({top: y, behavior: 'instant'})",
            max(0, int(box["y"] + (frame.evaluate("() => window.scrollY") or 0) - 120)),
        )
    except Exception:
        pass
    time.sleep(0.3)
    ox = iframe_box["x"] if iframe_box else 0
    oy = iframe_box["y"] if iframe_box else 0
    pt = (
        ox + box["x"] + min(box["w"], 280) * random.uniform(0.25, 0.45),
        oy + box["y"] + min(box["h"], 80) * random.uniform(0.25, 0.5),
    )
    human_move(page, pt)
    time.sleep(random.uniform(0.08, 0.2))
    page.mouse.click(pt[0], pt[1])
    time.sleep(random.uniform(1.2, 2.2))
    return True


def extract_open_panel_text(frame) -> str:
    if frame is None:
        return ""
    try:
        text = frame.evaluate(
            """() => {
                const selectors = [
                    '.resume-detail', '.geek-detail', '.detail-container',
                    '[class*="resume-content"]', '[class*="geek-info"]',
                    '[class*="detail-wrap"]'
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el && (el.innerText || '').trim().length > 40) {
                        return el.innerText.trim().slice(0, 20000);
                    }
                }
                return '';
            }"""
        )
        return (text or "").strip()
    except Exception:
        return ""
