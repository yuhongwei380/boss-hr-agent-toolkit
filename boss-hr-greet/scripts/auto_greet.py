#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
boss-hr-greet：高分候选人自动打招呼脚本（patchright DOM 路线 · element.click）

工作流：
  1) 读 screening_results.json（最新 run）+ candidate_pool.json，按 score 阈值挑出高分名单
  2) 连上 BOSS 推荐牛人页（已登录态），定位 iframe
  3) 滚 list 每屏停下，扫当前"打招呼"按钮
  4) 对每个高分名字（注意 name 清理"刚刚活跃"等尾巴）：
       - 用 li:has-text(name) 找到对应候选人卡片
       - 在卡片内 locator("button.btn-greet:has-text('打招呼')") 精确定位按钮
       - 用 patchright locator 拟人 click
       - 等 2 秒，按钮 text 应变"继续沟通"（验证成功）
       - 扫 iframe 看有没有"已向牛人发送招呼"对话框 → 点"知道了"
  5) 落 runs/<run_id>/process/greet_log.json + run_log.txt

为什么用 locator 而不是裸坐标：
  - BOSS list 每个候选人渲染 5 列副本（横向布局），同一 (name, doc_y) 有多个按钮
  - 用 li:has-text(name) 限定到唯一候选人卡片 → 按钮 locator 唯一
  - 真实坐标由 patchright 自己算，不用维护 doc_y/doc_x

为什么不用 force click：
  - force click 会绕过遮挡检测，可能命中错误的按钮副本
  - patchright locator 默认 click 会等元素可见+稳定，更稳
"""
import sys, os, json, time, random, argparse, atexit
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
import fix_encoding  # noqa: E402
from output_manager import JobOutputManager
from job_resume_store import JobResumeStore
from run_orchestrator import RunOrchestrator

from patchright.sync_api import sync_playwright
from human_interaction import human_move

DEFAULT_JOB = "线控底盘制动、转向工程师"
GREET_TEXT = "打招呼"
GREETED_TEXT = "继续沟通"
DIALOG_CLOSE_TEXT = "知道了"
DIALOG_TITLE = "已向牛人发送招呼"


# ============== 工具函数 ==============

def log(out, msg):
    """打印 + 写 run_log"""
    ts = time.strftime('%H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line, flush=True)
    with open(out.run_log_path, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def load_high_score_candidates(job_dir, run_id, score_threshold, only_names=None):
    """从指定 run 的 process/screening_results.json 读高分候选。

    2026-07-30 重构：
      - run_id 必填（数据边界）
      - 不再扫 runs/*/ 找"最新" —— 那是智能体偷懒入口
      - 找不到 screening_results.json → 高分列表为空，由调用方决定

    --only-names 模式：如果名单里的人在 screening_results 里找不到，会回退到
    state/candidate_pool.json 兜底（仅用于打招呼定位，不要求评分）。
    """
    if not run_id:
        raise ValueError("load_high_score_candidates 必须显式传 run_id，禁止扫 runs/*/")
    run_dir = os.path.join(job_dir, 'runs', run_id)
    screen_path = os.path.join(run_dir, 'process', 'screening_results.json')

    high = []
    if os.path.exists(screen_path):
        screen = json.load(open(screen_path, encoding='utf-8'))
        cands = screen.get('candidates') or []
        for c in cands:
            score = c.get('total', 0)
            if score < score_threshold:
                continue
            high.append({
                'name': c.get('name', ''),
                'score': score,
                'tier': c.get('tier', ''),
                'school': c.get('school', ''),
                'work_years': c.get('work_years', ''),
                'current_role': c.get('current_role', ''),
            })

    # ★ --only-names 模式兜底：screening 里没的人，从 candidate_pool.json 补
    if only_names:
        only_set = {n.strip() for n in only_names}
        before = len(high)
        high = [h for h in high if h['name'].strip() in only_set]
        existing_names = {h['name'].strip() for h in high}
        missing = [n for n in only_set if n not in existing_names]
        # missing 非空就从 pool 补（即使 before=0 也要补，否则 --only-names 模式完全失效）
        if missing:
            pool_path = os.path.join(job_dir, 'state', 'candidate_pool.json')
            if os.path.exists(pool_path):
                pool = json.load(open(pool_path, encoding='utf-8')).get('items', {})
                name_to_item = {}
                for k, item in pool.items():
                    n = item.get('name', '').strip()
                    if n:
                        name_to_item[n] = item
                for n in missing:
                    item = name_to_item.get(n)
                    if item:
                        high.append({
                            'name': n,
                            'score': 0,
                            'tier': 'from-pool',
                            'school': item.get('school_name', '') or item.get('school', ''),
                            'work_years': item.get('work_years', ''),
                            'current_role': item.get('current_role', '') or item.get('expectPosition', ''),
                            'encrypt_geek_id': item.get('encrypt_geek_id', ''),
                            'from_pool_only': True,
                        })
        print(f'按 --only-names 过滤：{before} → {len(high)} 人')

    # 从 candidate_pool.json 反查 encrypt_geek_id（给高分列表里没 geek_id 的补）
    pool_path = os.path.join(job_dir, 'state', 'candidate_pool.json')
    name_to_id = {}
    if os.path.exists(pool_path):
        pool = json.load(open(pool_path, encoding='utf-8')).get('items', {})
        for k, item in pool.items():
            n = item.get('name', '').strip()
            if n:
                name_to_id[n] = item.get('encrypt_geek_id', '')

    for h in high:
        if not h.get('encrypt_geek_id'):
            h['encrypt_geek_id'] = name_to_id.get(h['name'].strip(), '')

    return high


def load_positions(job_dir):
    """读 state/geek_positions.json（候选人 → doc_y/doc_x 映射）"""
    pos_path = os.path.join(job_dir, 'state', 'geek_positions.json')
    if not os.path.exists(pos_path):
        return {}
    data = json.load(open(pos_path, encoding='utf-8'))
    return data.get('positions', {})


def save_positions(job_dir, positions):
    """落 state/geek_positions.json"""
    pos_path = os.path.join(job_dir, 'state', 'geek_positions.json')
    payload = {
        'job': '线控底盘制动、转向工程师',
        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'count': len(positions),
        'positions': positions,
    }
    with open(pos_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return pos_path


# ============== iframe 操作（locator 版）==============

def scroll_iframe_to(frame, target_y):
    """iframe 内瞬时滚动"""
    frame.evaluate(f"(y) => window.scrollTo({{top: y, behavior: 'instant'}})", target_y)
    time.sleep(random.uniform(0.3, 0.6))


def count_greet_buttons(frame):
    """扫 iframe 内 btn-greet 按钮数（不去重，BOSS 横向渲染多列）"""
    return frame.locator('button.btn-greet').count()


def scan_and_record_positions(frame, scroll_first=True):
    """一次性扫描整个 iframe DOM，记所有候选人 doc_y（绝对坐标）。

    关键设计：
      - BOSS list 懒加载到 DOM 后，getBoundingClientRect() 返回视口相对坐标
        加 scrollY/scrollX 才能得到稳定"绝对文档坐标"
      - 先滚到底再滚回顶：触发懒加载 + 取稳定坐标
      - 一次 evaluate 扫全所有 li.card-item → 比分屏扫快、准
    返回 {name: {doc_y, doc_x, width, height, btn_text}}
    """
    if scroll_first:
        # 先滚到底触发懒加载（让所有 li.card-item 进入 DOM）
        frame.evaluate(r'() => window.scrollTo({top: document.documentElement.scrollHeight, behavior: "instant"})')
        time.sleep(1.5)
        # 再滚回顶，取稳定绝对坐标
        frame.evaluate(r'() => window.scrollTo({top: 0, behavior: "instant"})')
        time.sleep(0.8)

    result = frame.evaluate(r"""() => {
        const out = {};
        const seen = new Set();
        const btns = document.querySelectorAll('button.btn-greet');
        for (const b of btns) {
            const t = (b.textContent || '').trim();
            // 只接受"打招呼"按钮（"继续沟通"说明已招呼过）
            if (t !== '打招呼') continue;
            const card = b.closest('li.card-item');
            if (!card) continue;
            let nameEl = card.querySelector('[class*="name"]');
            if (!nameEl) nameEl = card.querySelector('h3, h4');
            const name = nameEl ? (nameEl.textContent || '').trim() : '';
            const clean = name.replace(/\s*(刚刚活跃|今日活跃|3日内活跃|本周活跃|2周内活跃|本月活跃)\s*$/, '').trim();
            if (!clean || seen.has(clean)) continue;
            seen.add(clean);
            const rect = b.getBoundingClientRect();
            // ★ 转成绝对 doc 坐标：rect.top + window.scrollY
            out[clean] = {
                doc_y: Math.round(rect.top + window.scrollY),
                doc_x: Math.round(rect.left + window.scrollX),
                width: Math.round(rect.width),
                height: Math.round(rect.height),
                btn_text: t,
            };
        }
        return out;
    }""")
    return result or {}


def scroll_iframe_smooth(frame, target_y):
    """iframe 内平滑滚动（避免瞬时跳触发反爬）"""
    frame.evaluate(
        """(y) => window.scrollTo({top: y, behavior: 'smooth'})""",
        target_y,
    )
    # 平滑滚动需较长时间等动画完成
    time.sleep(random.uniform(0.8, 1.2))


def greet_one_by_position(page, frame, iframe_box, name, pos, dry_run=False, iframe=None):
    """按 doc_y 直接 scrollTo + click（不走 locator 反复跳）。

    关键：list 滚到底后稳定，但每次招呼完一个人 BOSS 会从底部移除，
    引起 list 整体"上移"。如果从上往下招呼，doc_y 会失效；
    倒序招呼时已招呼的人在底部，中部以上的人 doc_y 不受影响。
    """
    doc_y = pos['doc_y']
    doc_x = pos.get('doc_x', 0)

    # 0) 招呼前预检：page 顶层 + iframe 内有没有 modal/drawer/overlay（之前残留的候选人详情页）
    #    存在就尝试关掉（按 Esc 或点关闭按钮），否则 click 会被挡住
    def _scan_blockers(target_frame):
        return target_frame.evaluate(r"""() => {
            const out = [];
            // 1) 简历详情（BOSS 推荐页点 li 卡非 btn 区域会打开 .resume-detail-wrap drawer）
            for (const sel of ['.resume-detail-wrap', '.geek-resume', '[class*="resume-detail"]',
                               '[class*="ResumeDetail"]', '[class*="geek-detail"]']) {
                const els = document.querySelectorAll(sel);
                for (const e of els) {
                    const r = e.getBoundingClientRect();
                    if (r.width > 200 && r.height > 200) {
                        const cs = getComputedStyle(e);
                        if (cs.display !== 'none' && cs.visibility !== 'hidden') {
                            out.push({sel: sel, cls: e.className.toString().slice(0, 50),
                                    w: r.width, h: r.height, z: cs.zIndex,
                                    text: (e.innerText||'').slice(0,60).replace(/\s+/g,' ')});
                        }
                    }
                }
            }
            // 2) 通用 modal/dialog
            for (const sel of ['[class*="modal"]', '[class*="drawer"]', '[class*="dialog"]',
                               '[class*="mask"]', '[class*="overlay"]']) {
                const els = document.querySelectorAll(sel);
                for (const e of els) {
                    const r = e.getBoundingClientRect();
                    if (r.width > 300 && r.height > 200) {
                        const cs = getComputedStyle(e);
                        if (cs.display !== 'none' && cs.visibility !== 'hidden') {
                            out.push({sel: sel, cls: e.className.toString().slice(0, 50),
                                    w: r.width, h: r.height, z: cs.zIndex,
                                    text: (e.innerText||'').slice(0,60).replace(/\s+/g,' ')});
                        }
                    }
                }
            }
            return out;
        }""")

    def _try_close_blockers(target_frame):
        """尝试关掉检测到的所有阻挡层。返回是否关掉了。"""
        # 1) 按 Esc
        try:
            page.keyboard.press('Escape')
            time.sleep(0.4)
        except Exception:
            pass
        # 2) iframe 内找 close 按钮
        try:
            closed = target_frame.evaluate(r"""() => {
                let closed_any = false;
                // 简历详情 drawer 的关闭按钮
                for (const sel of ['.resume-detail-wrap .close', '.resume-detail-wrap [class*="close"]',
                                   '.geek-resume .close', '[class*="resume-detail"] [class*="close"]',
                                   '[class*="detail"] [class*="close"]',
                                   '[class*="close"]', '[aria-label="close"]',
                                   '[class*="cancel"]', 'button.close']) {
                    const els = document.querySelectorAll(sel);
                    for (const e of els) {
                        if (e.offsetWidth > 0 && e.offsetHeight > 0) {
                            e.click();
                            closed_any = true;
                            break;
                        }
                    }
                    if (closed_any) break;
                }
                return closed_any;
            }""")
            if closed:
                time.sleep(0.5)
                return True
        except Exception:
            pass
        return False

    try:
        # 检查 page 顶层
        page_blockers = _scan_blockers(page)
        # 检查 iframe 内
        frame_blockers = _scan_blockers(frame) if frame else []
        blockers = page_blockers + frame_blockers
        if blockers:
            print(f'  [WARN] 发现 {len(blockers)} 个阻挡层', flush=True)
            for b in blockers[:3]:
                print(f'    - sel={b.get("sel")} cls={b.get("cls")} {b.get("w")}x{b.get("h")} z={b.get("z")} text={b.get("text")[:40]!r}', flush=True)
            closed = _try_close_blockers(frame)
            if not closed:
                closed = _try_close_blockers(page)
            if closed:
                print('  [WARN] 已尝试关闭阻挡层', flush=True)
                time.sleep(0.5)
            else:
                print('  [WARN] 没找到关闭按钮，请手动关掉', flush=True)
    except Exception as e:
        print(f'  [WARN] 预检 modal 异常: {e}', flush=True)

    # 1) 滚到候选人位置（视口顶部留 100px 余量让按钮完全可见）
    viewport_h = frame.evaluate("() => window.innerHeight")
    target_y = max(0, doc_y - 100)
    scroll_iframe_smooth(frame, target_y)
    time.sleep(0.3)

    # 2) 重新找 btn：必须 name 精确匹配 + doc_y 在容差内
    # BOSS list 实际是单列纵向（所有 li_card_item 都在 dx≈174），不靠 dx 锁定
    # 关键：返回的是 button 元素索引，click 时直接用 locator 索引拿 button click
    # （不要用 page.mouse.click 算坐标 — list 视觉布局会让坐标落到 li 区域）
    btn_info = frame.evaluate(r"""(args) => {
        const name = args.name;
        const target_dy = args.target_dy;
        const dy_tol = 220;  // doc_y 容差 ±220px（list 动态变更时允许较大飘移，约 1 个 li 高度）
        const lis = document.querySelectorAll('li.card-item');
        let best_li = null;
        let best_li_idx = -1;
        let best_dy_diff = Infinity;
        // 先按 name 完全匹配找最近的 li
        for (let i = 0; i < lis.length; i++) {
            const li = lis[i];
            const nameEl = li.querySelector('[class*="name"]');
            const li_name = nameEl ? (nameEl.textContent || '').trim() : '';
            const clean = li_name.replace(/\s*(刚刚活跃|今日活跃|3日内活跃|本周活跃|2周内活跃|本月活跃)\s*$/, '').trim();
            if (clean !== name) continue;
            const btn = li.querySelector('button.btn-greet');
            if (!btn) continue;
            const btnText = (btn.textContent || '').trim();
            if (btnText !== '打招呼') continue;
            const r = li.getBoundingClientRect();
            const li_dy = r.top + window.scrollY;
            const dy_diff = Math.abs(li_dy - target_dy);
            if (dy_diff < best_dy_diff) {
                best_dy_diff = dy_diff;
                best_li = li;
                best_li_idx = i;
            }
        }
        if (!best_li) {
            return {found: false, reason: `name=${name} 不在 list 上（已招呼 / 被排除）`};
        }
        if (best_dy_diff > dy_tol) {
            return {found: false, reason: `name=${name} 找到但 dy_diff=${Math.round(best_dy_diff)} > ${dy_tol}（list 状态变化大，跳过避免点错人）`};
        }
        const btn = best_li.querySelector('button.btn-greet');
        const r = btn.getBoundingClientRect();
        const allBtns = document.querySelectorAll('button.btn-greet');
        let btn_idx = -1;
        for (let i = 0; i < allBtns.length; i++) {
            if (allBtns[i] === btn) { btn_idx = i; break; }
        }
        return {
            found: true,
            x: r.left, y: r.top, w: r.width, h: r.height,
            li_idx: best_li_idx,
            btn_idx: btn_idx,
            btn_text: (btn.textContent || '').trim(),
            dy_diff: best_dy_diff,
        };
    }""", {'name': name, 'target_dy': doc_y})

    if not btn_info.get('found'):
        return {'name': name, 'found': False, 'status': 'not_found',
                'reason': btn_info.get('reason', '找不到 li 或 btn')}

    box = {'x': btn_info['x'], 'y': btn_info['y'],
           'width': btn_info['w'], 'height': btn_info['h']}
    if box['width'] == 0:
        return {'name': name, 'found': False, 'status': 'not_found', 'reason': '按钮不在视口'}

    # Debug
    _dbg_scrollY = frame.evaluate("() => window.scrollY")
    _cur_box_dbg = iframe.bounding_box() if iframe else iframe_box
    _dbg_px = _cur_box_dbg['x'] + box['x'] + box['width']/2
    _dbg_py = _cur_box_dbg['y'] + box['y'] + box['height']/2
    print(f'  [DBG] {name} scrollY={_dbg_scrollY} target_dy={doc_y} dy_diff={btn_info.get("dy_diff")} btn=({box["x"]:.0f},{box["y"]:.0f}) btn_idx={btn_info.get("btn_idx")} iframe=({_cur_box_dbg["x"]:.0f},{_cur_box_dbg["y"]:.0f}) page=({_dbg_px:.0f},{_dbg_py:.0f})', flush=True)

    if dry_run:
        return {
            'name': name, 'found': True, 'doc_x': box['x'], 'doc_y': box['y'],
            'btn_idx': btn_info.get('btn_idx'),
            'target_scroll_y': target_y, 'dry_run': True,
        }

    # 3) 关键修复：用 element handle 直接 click，不再 page.mouse.click 算坐标
    #    原因：list 视觉布局让 btn 中心 page 坐标可能落在 li card-item 边缘外
    #    → page.mouse.click 命中 li 的某个父 div → 打开简历详情
    #    用 frame.locator('li.card-item').nth(li_idx).locator('button.btn-greet')
    #    让 patchright 走 element 自带 hit-test 流程，绝对点 button 自己
    li_idx = btn_info.get('li_idx', -1)
    btn_idx = btn_info.get('btn_idx', -1)
    if li_idx < 0 or btn_idx < 0:
        return {'name': name, 'found': False, 'status': 'not_found', 'reason': 'btn 索引无效'}

    # 3.1) 拟人 hover（先到 btn 区域，模拟人眼看到再点）
    try:
        human_move(page, (_dbg_px, _dbg_py))
        time.sleep(random.uniform(0.3, 0.5))
    except Exception:
        pass

    # 3.2) 直接 evaluate click li 内的 button（不走 patchright locator，避免 button 数量大超时）
    #    evaluate click 走 button DOM 自己的 .click() 事件流，触发 BOSS Vue 的 click handler
    #    不走 page.mouse.click 算坐标，所以不会命中 li 区域而非 btn
    btn_text_before = frame.evaluate(r"""(idx) => {
        const all = document.querySelectorAll('button.btn-greet');
        if (all[idx]) return (all[idx].textContent || '').trim();
        return null;
    }""", btn_idx)
    print(f'  [CLICK] evaluate click li_idx={li_idx} btn_idx={btn_idx} btn_text_before={btn_text_before!r}', flush=True)
    clicked = frame.evaluate(r"""(idx) => {
        const all = document.querySelectorAll('button.btn-greet');
        if (all[idx] && (all[idx].textContent||'').trim() === '打招呼') {
            all[idx].click();
            return true;
        }
        return false;
    }""", btn_idx)
    if not clicked:
        return {'name': name, 'found': False, 'status': 'not_found',
                'reason': f'btn_idx={btn_idx} 不存在或 text 不是"打招呼"（之前：{btn_text_before!r}）'}
    time.sleep(4.0)  # 等 BOSS 后端处理 + dialog 弹出 + button 文本更新

    # 4) 验证 + 关弹窗（沿用 greet_one 的逻辑）
    # 关键：招呼成功后 button class 从 "btn btn-greet" 变成 "btn btn-continue btn-outline"
    # text 从 "打招呼" 变成 "继续沟通" — 用 [class*="btn-continue"] 选择器锁定
    verified = False
    try:
        scan_result = frame.evaluate(r"""(args) => {
            const name = args.name;
            // 候选选择器：btn-continue（成功招呼后的 class）+ btn-greet（待招呼）
            const btns = document.querySelectorAll('button[class*="btn-continue"], button.btn-greet');
            for (const b of btns) {
                const t = (b.textContent || '').trim();
                if (!t.includes('继续') && !t.includes('沟通') && t !== '打招呼') continue;
                if (t === '打招呼') continue;  // 跳过还没招呼的
                let card = b.closest('li');
                if (!card) card = b.closest('[class*="card"]');
                if (!card) continue;
                const cardText = (card.innerText || '').replace(/\s+/g, '');
                if (cardText.includes(name)) return {found: true, btn_text: t, btn_class: b.className};
            }
            return {found: false};
        }""", {'name': name.replace(' ', '').strip()})
        if scan_result and scan_result.get('found'):
            verified = True
    except Exception:
        pass

    dialog_closed = False
    try:
        # 扫 page + 所有嵌套 frame 找"知道了"按钮
        # 关键：Boss "已向牛人发送招呼" dialog 跟 BOSS list 在同一个 iframe[0] 里
        # 用 evaluate 直接调 button.click()（不通过 patchright locator，避免 button>=468 时超时）
        target_frame = None
        for f in page.frames:
            try:
                found = f.evaluate(r"""() => {
                    const btns = document.querySelectorAll('button');
                    for (let i = 0; i < btns.length; i++) {
                        const t = (btns[i].textContent || '').trim();
                        if ((t === '知道了' || t === '我知道了') && btns[i].offsetWidth > 0 && btns[i].offsetHeight > 0) {
                            btns[i].click();
                            return t;
                        }
                    }
                    return null;
                }""")
                if found:
                    target_frame = f
                    dialog_closed = True
                    print(f'  [DIALOG] 已 click "{found}" via evaluate', flush=True)
                    time.sleep(1.0)
                    break
            except Exception:
                continue
    except Exception as e:
        print(f'  [WARN] 关 dialog 失败: {e}', flush=True)

    return {
        'name': name,
        'found': True,
        'clicked': True,
        'verified': verified,
        'dialog_closed': dialog_closed,
        'status': 'greeted' if verified else 'clicked_unverified',
    }


# ============== 主流程 ==============

def auto_greet(job_name=DEFAULT_JOB, score_threshold=70, max_count=10,
               run_id=None, only_names=None, dry_run=False, scroll_max=60,
               scan_only=False, skip_scan=False, encrypt_job_id=None):
    """打招呼主流程。

    关键设计（按用户的"不刷新 list 稳定"前提）：
      1) 不滚回顶、不刷新页面，复用 BOSS 当前 DOM
      2) 全量扫描：滚一遍 list 把每个候选人的 doc_y 记到 state/geek_positions.json
      3) 倒序招呼：从最底往上招乎（BOSS 动态换卡只影响底部，已招呼的人在底部）
      4) 每次招呼按 doc_y 直接 scrollTo + click（不走 locator 反复跳）

    模式：
      scan_only=True        只扫描记位置，不打招呼
      skip_scan=True        跳过扫描，用 state/geek_positions.json 已有位置直接打招呼
      默认                  先扫描，再用新位置打招呼
    """
    # 路径解析：直接交给 JobOutputManager 处理（统一 OUTPUT_ROOT 含义）。
    # 2026-07-28 修复：之前手拼路径时错把 BOSS_HR_OUTPUT_DIR 当 job_dir，
    #   导致 greet_log 落到 boss-hr-output/runs/<run>/process/。
    from output_manager import resolve_encrypt_job_id
    encrypt_job_id = resolve_encrypt_job_id(encrypt_job_id)
    if not encrypt_job_id:
        raise ValueError("缺少 encrypt_job_id。\n  传 --encrypt-job-id，或设置 env BOSS_HR_ENCRYPT_JOB_ID")
    output = JobOutputManager(job_name, encrypt_job_id=encrypt_job_id, run_id=run_id, lazy=True)

    # ★ 2026-07-30 重构：run_id 是数据边界，--run-id 必填。
    #   不再"扫 runs/*/ 找最新" —— 那是智能体偷懒入口。
    from run_orchestrator import RunOrchestrator
    orch = RunOrchestrator(job_name, encrypt_job_id=encrypt_job_id)
    run_id = orch.bind_existing_run(run_id)
    output.run_id = run_id

    # 异常护栏：脚本若异常退出且没写 greet_log.json，自动清 run_dir
    _SAVED = False

    def _auto_prune():
        if not _SAVED and output.prune_if_empty():
            log(output, f'⚠️  本次 run 未产生 greet_log.json，已清理: {output.run_dir}')

    atexit.register(_auto_prune)

    output.ensure_run_dir()
    run_id = output.run_id

    log(output, f'=== boss-hr-greet 启动 run_id={run_id} ===')
    log(output, f'岗位：{job_name} | 阈值：{score_threshold} | 上限：{max_count} | dry_run={dry_run}')
    log(output, f'模式：scan_only={scan_only} skip_scan={skip_scan}')

    high = load_high_score_candidates(output.job_dir, run_id, score_threshold, only_names)
    if not high and not only_names:
        # 默认模式（按 score 筛）无结果才退出
        log(output, '没有高分候选人，结束')
        return
    if not high and only_names:
        # --only-names 模式：screening 里没找到、pool 也没补上
        # → 用 stub 项继续往下走（扫描阶段如果 list 上真有人，可以补位置）
        log(output, '--only-names 给的名字在 screening/pool 都查不到，构造 stub 继续扫描')
        high = [{'name': n.strip(), 'score': 0, 'tier': 'manual',
                 'school': '', 'work_years': '', 'current_role': '',
                 'from_pool_only': True, 'from_stub': True} for n in only_names]

    # --only-names 模式下保留用户给定顺序，否则按 score 降序
    if not only_names:
        high.sort(key=lambda x: -x['score'])
    if len(high) > max_count:
        log(output, f'高分 {len(high)} > max_count {max_count}，取前 {max_count}')
        high = high[:max_count]

    log(output, f'目标 {len(high)} 人（基于 run_id={run_id}）')
    for i, h in enumerate(high, 1):
        log(output, f'  #{i}: {h["name"]:8s} score={h["score"]:.1f} tier={h["tier"]:4s}')

    greet_log = []

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp('http://localhost:9222')
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        if 'recommend' not in page.url:
            log(output, f'当前页面不是 recommend 页（{page.url[:80]}），goto 切换')
            page.goto('https://www.zhipin.com/web/chat/recommend',
                       wait_until='domcontentloaded', timeout=30000)
            time.sleep(5)
        else:
            log(output, f'复用已有 recommend 页（不刷新）: {page.url[:80]}')

        iframe = page.wait_for_selector('iframe', timeout=15000)
        frame = iframe.content_frame()
        iframe_box = iframe.bounding_box()
        log(output, f'iframe 定位 ({iframe_box["width"]:.0f}x{iframe_box["height"]:.0f})')

        # ★ Step 1: 一次性扫描整个 list DOM（先滚到底触发懒加载 → 再滚回顶取绝对坐标）
        positions = {}
        if not skip_scan:
            log(output, '开始扫描 list（一次性 evaluate 扫全）...')
            positions = scan_and_record_positions(frame, scroll_first=True)
            log(output, f'  扫描到 {len(positions)} 个候选人（去重后）')
            # 落盘
            save_positions(output.job_dir, positions)
            log(output, f'  位置已落盘：state/geek_positions.json（{len(positions)} 人）')
        else:
            positions = load_positions(output.job_dir)
            log(output, f'复用已有位置：{len(positions)} 人')

        if scan_only:
            log(output, '--scan-only 模式，跳过打招呼')
            for h in high:
                pos = positions.get(h['name'])
                greet_log.append({
                    **h,
                    'found': pos is not None,
                    'doc_y': pos['doc_y'] if pos else None,
                    'doc_x': pos.get('doc_x') if pos else None,
                    'status': 'scanned' if pos else 'not_found',
                    'reason': '' if pos else '未在当前 list 出现',
                })
        else:
            # ★ Step 2: 按 doc_y 倒序招呼（避免 BOSS 动态换卡影响已招呼位置）
            high_with_pos = []
            for h in high:
                pos = positions.get(h['name'])
                if pos:
                    high_with_pos.append((h, pos))
            high_with_pos.sort(key=lambda x: -x[1]['doc_y'])  # doc_y 倒序

            log(output, f'实际可招呼 {len(high_with_pos)} 人（list 中存在的）')
            for i, (h, pos) in enumerate(high_with_pos, 1):
                log(output, f'  [倒序 #{i}] {h["name"]} doc_y={pos["doc_y"]}')

            # 招呼每个候选人
            for i, (h, pos) in enumerate(high_with_pos, 1):
                name = h['name']
                log(output, f'\n--- 招呼 [{i}/{len(high_with_pos)}]: {name} doc_y={pos["doc_y"]} ---')
                result = greet_one_by_position(page, frame, iframe_box, name, pos, dry_run=dry_run)
                result.update(h)  # 合并 score/tier/school
                greet_log.append(result)

                if dry_run:
                    log(output, f'    [DRY-RUN] 找到 target_scroll_y={result.get("target_scroll_y", 0):.0f}')
                elif result.get('verified'):
                    log(output, f'    ✓ {name} 已打招呼（按钮变"继续沟通"）')
                else:
                    log(output, f'    ⚠ {name} 点击了但验证失败')

                # 节流 3-6 秒
                wait = random.uniform(3, 6)
                log(output, f'    ⏸ 节流 {wait:.1f}s')
                time.sleep(wait)

                # 实时落盘
                with open(output.get_process_path('greet_log.json'), 'w', encoding='utf-8') as f:
                    json.dump({
                        'job': job_name,
                        'run_id': run_id,
                        'score_threshold': score_threshold,
                        'started_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'mode': 'scan_and_greet_reverse',
                        'positions_count': len(positions),
                        'results': greet_log,
                    }, f, ensure_ascii=False, indent=2)

            # 没找到的
            found_names = {h['name'] for h, _ in high_with_pos}
            for h in high:
                if h['name'] not in found_names:
                    greet_log.append({
                        **h, 'found': False, 'verified': False,
                        'status': 'not_found',
                        'reason': '扫描全程未在 list 出现（可能已招呼 / 被 BOSS 排除）',
                    })

    # 最终落盘
    summary = {
        'greeted': sum(1 for r in greet_log if r.get('status') == 'greeted'),
        'clicked_unverified': sum(1 for r in greet_log if r.get('status') == 'clicked_unverified'),
        'not_found': sum(1 for r in greet_log if r.get('status') == 'not_found'),
        'dry_run': sum(1 for r in greet_log if r.get('status') == 'dry_run'),
        'scanned': sum(1 for r in greet_log if r.get('status') == 'scanned'),
        'total': len(greet_log),
    }
    log(output, f'\n=== 完成：greeted={summary["greeted"]} unverified={summary["clicked_unverified"]} not_found={summary["not_found"]} ===')

    with open(output.get_process_path('greet_log.json'), 'w', encoding='utf-8') as f:
        json.dump({
            'job': job_name,
            'run_id': run_id,
            'score_threshold': score_threshold,
            'started_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'mode': 'scan_and_greet_reverse',
            'positions_count': len(positions),
            'summary': summary,
            'results': greet_log,
        }, f, ensure_ascii=False, indent=2)
    log(output, f'日志 → {output.get_process_path("greet_log.json")}')

    # 标记 greet 步骤完成（让后续补招呼仍能跟走同一 run_id）
    # 不主动 finish()：greeting 是 run 的"延展"，报告已生成后再补招也合理
    _SAVED = True  # 招呼日志已落盘，run 保留
    try:
        orch.mark_done('greet', run_id=run_id)
    except Exception as e:
        log(output, f'⚠️  mark_done 失败（不影响招呼结果）: {e}')

    # 是否自动 finish()
    # 2026-07-29 改进：默认招呼成功后自动 finish()，下次跑自动开新 run。
    # 显式 --no-finish 可保留「回头补招呼同一 run」能力。
    greeted_count = summary.get('greeted', 0)
    auto_finished = False
    if args.no_finish:
        log(output, '')
        log(output, '━' * 60)
        log(output, 'A 流程 5 步全部完成。本次 run 仍标记为「未 finish」，')
        log(output, '意味着下次跑 greet 会沿用此 run（用于回头补招呼）。')
        log(output, '')
        log(output, '要开新 run？执行：')
        log(output, f'    python -X utf8 -c "import sys;sys.path.insert(0,\'shared\');from run_orchestrator import RunOrchestrator;RunOrchestrator(\'{job_name}\').finish()"')
        log(output, '━' * 60)
    elif greeted_count > 0 and not args.dry_run:
        # 真招呼且至少招呼成功 1 人 → 自动 finish()
        try:
            orch.finish()
            auto_finished = True
            log(output, '')
            log(output, '━' * 60)
            log(output, f'✅ A 流程 5 步全部完成，已自动 finish()。')
            log(output, f'招呼成功 {greeted_count} 人，下次跑会自动开新 run。')
            log(output, '━' * 60)
        except Exception as e:
            log(output, f'⚠️  自动 finish() 失败（不影响招呼结果）: {e}')
            log(output, f'    可手动执行: RunOrchestrator(\'{job_name}\').finish()')
    elif args.dry_run:
        log(output, '')
        log(output, '━' * 60)
        log(output, '⏸  DRY-RUN 模式未发送招呼，未 finish()（保留回头招呼能力）。')
        log(output, '━' * 60)
    else:
        log(output, '')
        log(output, '━' * 60)
        log(output, f'⏸  本轮招呼成功 0 人，未 finish()。')
        log(output, f'    如确认本轮结束，手动: RunOrchestrator(\'{job_name}\').finish()')
        log(output, '━' * 60)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='高分候选人回头打招呼（位置表 + 倒序版 / 一键式）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
三种调用姿势：
  1) 默认（一键：自动扫描 + 招呼）
     python auto_greet.py --only-names 张三,李四

  2) 仅扫描（不下发，用于调试/刷新位置表）
     python auto_greet.py --only-names 张三 --scan-only

  3) 用已有位置表直接招呼（list 没变，省一次扫描）
     python auto_greet.py --only-names 张三 --skip-scan
""",
    )
    parser.add_argument('--job-name', default=DEFAULT_JOB)
    parser.add_argument('--encrypt-job-id', default=None,
                        help='BOSS encryptJobId（推荐；新设计目录名依此定位；亦可走 env BOSS_HR_ENCRYPT_JOB_ID）')
    parser.add_argument('--threshold', type=float, default=70.0,
                        help='score 阈值（>= 阈值的候选人会被招呼；与 --only-names 互斥，--only-names 优先）')
    parser.add_argument('--max', type=int, default=10)
    parser.add_argument('--run-id', required=True,
                        help='【必填】run_id 是数据边界。新任务先跑 boss_jd.py 创建 run；不传直接报错。')
    parser.add_argument('--only-names', default=None,
                        help='逗号分隔，直接指定要打招呼的名字（精准点名模式）')
    parser.add_argument('--dry-run', action='store_true',
                        help='干跑：只定位不 click')
    parser.add_argument('--scroll-max', type=int, default=60,
                        help='扫描时最多滚多少屏（防止 list 不收敛）')
    parser.add_argument('--scan-only', action='store_true',
                        help='只扫描记位置到 geek_positions.json，不打招呼')
    parser.add_argument('--skip-scan', action='store_true',
                        help='跳过扫描，直接用已有 geek_positions.json 招呼（list 状态未变时可省 2s）')
    parser.add_argument('--no-finish', action='store_true',
                        help='招呼跑完后不自动 finish()，保留「回头补招呼同一 run」能力（默认招呼成功后自动 finish）')
    args = parser.parse_args()

    # 互斥校验：--scan-only 与 --skip-scan 不能同时给
    if args.scan_only and args.skip_scan:
        parser.error('--scan-only 和 --skip-scan 互斥，只能二选一')

    only_names = args.only_names.split(',') if args.only_names else None
    if only_names:
        # 精准点名模式：忽略 --threshold / --max
        score_threshold = 0
        max_count = len(only_names)
    else:
        score_threshold = args.threshold
        max_count = args.max

    auto_greet(
        job_name=args.job_name,
        score_threshold=score_threshold,
        max_count=max_count,
        run_id=args.run_id,
        only_names=only_names,
        dry_run=args.dry_run,
        scroll_max=args.scroll_max,
        scan_only=args.scan_only,
        skip_scan=args.skip_scan,
        encrypt_job_id=args.encrypt_job_id,
    )