#!/usr/bin/env python3
"""
推荐牛人简历下载脚本（patchright + fetch 版本）
通过浏览器 fetch 调 BOSS API，使用真实 Edge TLS 指纹，不依赖 CLI。

用法:
  python recommend_download.py --job-name 车架工程师 --batch 1
  python recommend_download.py --job-name 车架工程师  # 下载全部
"""

import sys
import os
import json
import time
import random
import argparse
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
import fix_encoding  # noqa: E402  # 强制 Windows UTF-8 stdout
from output_manager import JobOutputManager

from patchright.sync_api import sync_playwright
from human_interaction import human_browse_context

FETCH_JS = """async (params) => {
    try {
        const url = '/wapi/zpjob/view/geek/info?encryptGeekId=' + params.geek_id
            + '&encryptJobId=' + params.job_id
            + '&securityId=' + encodeURIComponent(params.sec_id);
        const resp = await fetch(url, {credentials: 'include'});
        const data = await resp.json();
        if (data.code !== 0 || !data.zpData) {
            return {ok: false, error: data.message || 'unknown'};
        }
        const zp = data.zpData;
        if (zp.blockDialog && zp.blockDialog.title) {
            return {ok: false, error: zp.blockDialog.title};
        }
        const d = zp.geekDetailInfo || {};
        const b = d.geekBaseInfo || {};
        return {
            ok: true,
            name: b.name || '',
            age: b.ageDesc || '',
            degree: b.degreeCategory || '',
            work_years: b.workYearDesc || '',
            expectation: d.anonymousGeekExpect || d.geekExpect || null,
            work_experience: (d.geekWorkExpList || []).map(w => ({
                company: w.company || '',
                position: w.positionName || '',
                department: w.department || '',
                start: w.startDate || '',
                end: w.endDate || '',
                duration: w.workYearDesc || '',
                responsibility: w.responsibility || '',
                performance: w.performance || '',
                keywords: w.tagList || w.keywords || []
            })),
            project_experience: (d.geekProjExpList || []).map(p => ({
                name: p.projName || p.name || '',
                role: p.projRole || p.role || '',
                start: p.startDate || '',
                end: p.endDate || '',
                duration: p.projYearDesc || '',
                description: p.projDesc || p.description || '',
                achievement: p.projAchieve || p.achievement || ''
            })),
            education: (d.geekEduExpList || []).map(e => ({
                school: e.school || '',
                major: e.major || '',
                degree: e.degreeName || '',
                start: e.startDate || '',
                end: e.endDate || ''
            })),
            certifications: (d.geekCertificationList || []).map(c => c.certName || c.name || ''),
            skills: d.professionalSkill || '',
            active_status: b.activeTimeDesc || ''
        };
    } catch(e) {
        return {ok: false, error: e.message};
    }
}"""


def download_resumes(job_name, batch_number=None, max_count=None):
    output = JobOutputManager(job_name)

    # 读取候选人列表
    if batch_number:
        input_path = output.get_process_path(f'batch_{batch_number}_ids.json')
    else:
        input_path = output.recommend_geek_ids_path

    if not os.path.exists(input_path):
        print(f'错误：文件不存在：{input_path}')
        return [], []

    with open(input_path, 'r', encoding='utf-8') as f:
        geek_list = json.load(f)

    if not geek_list:
        print('候选人列表为空')
        return [], []

    gc0 = geek_list[0].get('geekCard', {})
    job_id = gc0.get('encryptJobId', '') or str(gc0.get('jobId', ''))

    if batch_number:
        print(f'[分批模式] 第 {batch_number} 批')
    print(f'岗位：{job_name}')
    print(f'岗位 ID：{job_id}')
    print(f'候选人：{len(geek_list)} 人')
    if max_count:
        print(f'最大下载：{max_count}')

    resumes = []
    failed = []
    start_time = datetime.now()
    print(f'\n开始时间：{start_time.strftime("%H:%M:%S")}\n')

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp('http://localhost:9222')
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # 确保在 BOSS 域名下（有 cookie）
        if 'zhipin.com' not in page.url:
            print('导航到 BOSS 直聘...')
            page.goto('https://www.zhipin.com/web/chat/recommend',
                       wait_until='domcontentloaded', timeout=20000)
            time.sleep(3)

        # 获取推荐列表 iframe(用于方案A:fetch 前制造拟人浏览上下文)
        try:
            iframe = page.query_selector('iframe')
            iframe_box = iframe.bounding_box() if iframe else None
        except Exception:
            iframe_box = None

        for i, g in enumerate(geek_list):
            if max_count and len(resumes) + len(failed) >= max_count:
                break

            geek_id = g.get('encryptGeekId', '')
            gcard = g.get('geekCard', {})
            sec_id = gcard.get('securityId', '')
            name = gcard.get('geekName', '')

            if not geek_id or not sec_id:
                failed.append({'name': name or 'Unknown', 'reason': '缺少 ID'})
                continue

            elapsed = (datetime.now() - start_time).total_seconds() / 60
            print(f'[{elapsed:.1f}分钟] #{i + 1}: {name}...', end=' ', flush=True)

            # 改法2(方案A):fetch 前补拟人浏览上下文(鼠标移动+小幅滚动,不点击、
            # 不点开简历,因此不会重复消耗"查看简历"配额,也不会因定位不到卡片而失败)
            try:
                human_browse_context(page, iframe_box)
            except Exception as e:
                print(f'  [上下文] 跳过:{str(e)[:40]}')

            # 用浏览器 fetch 调 API（真实 Edge 指纹）
            try:
                result = page.evaluate(FETCH_JS, {
                    'geek_id': geek_id,
                    'job_id': job_id,
                    'sec_id': sec_id
                })

                if result.get('ok'):
                    resumes.append(result)
                    print('OK')
                else:
                    err = result.get('error', 'unknown')
                    print(f'失败：{err[:50]}')
                    failed.append({'name': name, 'reason': err[:80]})
                    # 如果触发额度上限，停止
                    if '上限' in err:
                        print('已达查看上限，停止下载')
                        break
            except Exception as e:
                print(f'异常：{str(e)[:50]}')
                failed.append({'name': name, 'reason': str(e)[:80]})

            # 随机延迟 5-15 秒（模拟真人浏览节奏）
            if i < len(geek_list) - 1:
                delay = random.uniform(5, 15)
                time.sleep(delay)

    # 统计
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds() / 60

    print(f'\n{"=" * 40}')
    print(f'结束时间：{end_time.strftime("%H:%M:%S")}')
    print(f'总耗时：{duration:.1f} 分钟')
    print(f'成功：{len(resumes)} 份简历')
    print(f'失败：{len(failed)} 份')

    # 保存
    if batch_number:
        batch_path = output.get_process_path(f'batch_{batch_number}_resumes.json')
        with open(batch_path, 'w', encoding='utf-8') as f:
            json.dump(resumes, f, ensure_ascii=False, indent=2)
        print(f'\n本批简历：{batch_path}')

        # 追加到累计文件
        cum_path = output.resumes_path
        existing = []
        if os.path.exists(cum_path):
            with open(cum_path, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        existing_names = {r.get('name', '') for r in existing}
        for r in resumes:
            if r.get('name', '') not in existing_names:
                existing.append(r)
                existing_names.add(r.get('name', ''))
        with open(cum_path, 'w', encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        print(f'累计 {len(existing)} 份：{cum_path}')

        failed_path = output.get_process_path(f'batch_{batch_number}_failed.json')
    else:
        with open(output.resumes_path, 'w', encoding='utf-8') as f:
            json.dump(resumes, f, ensure_ascii=False, indent=2)
        print(f'\n简历已保存：{output.resumes_path}')
        failed_path = output.get_process_path('failed_resumes.json')

    with open(failed_path, 'w', encoding='utf-8') as f:
        json.dump(failed, f, ensure_ascii=False, indent=2)
    print(f'失败列表：{failed_path}')

    return resumes, failed


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='推荐牛人简历下载（patchright + fetch）')
    parser.add_argument('--job-name', default='车架工程师', help='岗位名称')
    parser.add_argument('--batch', type=int, default=None, help='分批：第几批')
    parser.add_argument('--max', type=int, default=None, help='最大下载数')

    args = parser.parse_args()
    download_resumes(args.job_name, args.batch, args.max)
