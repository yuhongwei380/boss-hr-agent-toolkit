#!/usr/bin/env python3
"""
推荐牛人候选人列表获取脚本
Step 1: 通过浏览器滚动拦截 API 获取候选人 ID 列表

使用统一输出路径：~/Desktop/boss-hr-output/<岗位名>/process/
"""

import sys
import os

# 添加 shared 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from output_manager import JobOutputManager

from patchright.sync_api import sync_playwright
import time
import json
import random
import argparse

def get_recommend_candidates(job_name='车架工程师', max_candidates=None):
    """
    获取推荐牛人候选人列表

    Args:
        job_name: 岗位名称（用于确定输出路径）
        max_candidates: 最大获取数量（None 为全部）
    """
    # 初始化输出管理器
    output = JobOutputManager(job_name)

    all_geeks = []
    seen_ids = set()

    def on_response(resp):
        """拦截 geek/list API 响应"""
        url = resp.url
        if 'geek/list' in url:
            try:
                data = resp.json()
                for g in data.get('zpData', {}).get('geekList', []):
                    gid = g.get('encryptGeekId', '')
                    if gid and gid not in seen_ids:
                        seen_ids.add(gid)
                        all_geeks.append(g)
            except:
                pass

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp('http://localhost:9222')
        ctx = browser.contexts[0]
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()

        pg.on('response', on_response)

        print('打开推荐牛人页面...')
        pg.goto('https://www.zhipin.com/web/chat/recommend',
                wait_until='networkidle', timeout=60000)
        time.sleep(5)

        # 找到 iframe
        iframe = pg.query_selector('iframe')
        if not iframe:
            print('错误：未找到 iframe')
            return

        frame = iframe.content_frame()

        # 持续滚动直到没有新数据
        no_new_count = 0

        while no_new_count < 5:
            # 检查是否达到最大数量
            if max_candidates and len(all_geeks) >= max_candidates:
                break

            prev = len(all_geeks)

            # 在 iframe 内滚动
            frame.evaluate('window.scrollBy(0, 1500)')

            # 随机延迟 3-6 秒（模拟真人滚动速度）
            delay = random.uniform(3, 6)
            time.sleep(delay)

            if len(all_geeks) == prev:
                no_new_count += 1
            else:
                no_new_count = 0

            print(f'{len(all_geeks)} 位候选人 (连续无新增：{no_new_count}/5)')

        print(f'\n总共获取：{len(all_geeks)} 位候选人')

        # 保存到 process 文件夹
        output_path = output.recommend_geek_ids_path
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(all_geeks, f, ensure_ascii=False, indent=2)

        print(f'已保存到：{output_path}')

        return all_geeks


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='获取推荐牛人候选人列表')
    parser.add_argument('--job-name', default='车架工程师', help='岗位名称')
    parser.add_argument('--max', type=int, default=None, help='最大获取数量')

    args = parser.parse_args()
    get_recommend_candidates(args.job_name, args.max)
