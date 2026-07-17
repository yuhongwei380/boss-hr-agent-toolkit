#!/usr/bin/env python3
"""
推荐牛人简历批量下载脚本（支持分批）
Step 2: 使用 CLI 批量获取完整简历

分批模式：
  --batch 1  下载 batch_1_ids.json 中的候选人，保存到 batch_1_resumes.json
  --batch 2  下载 batch_2_ids.json 中的候选人，保存到 batch_2_resumes.json
  每批结果同时追加到 test_resumes.json（累计所有已下载简历）

使用统一输出路径：~/Desktop/boss-hr-output/<岗位名>/process/
"""

import sys
import os

# 添加 shared 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from output_manager import JobOutputManager

import json
import subprocess
import time
import random
import argparse
from datetime import datetime


def download_resumes(job_name='车架工程师',
                     input_geek_ids=None,
                     max_count=None,
                     batch_number=None):
    """
    批量获取完整简历

    Args:
        job_name:      岗位名称
        input_geek_ids: 候选人列表文件路径（为 None 时使用默认路径或分批文件）
        max_count:     最大获取数量
        batch_number:  分批模式，第几批（从 1 开始）
    """
    output = JobOutputManager(job_name)

    # 确定输入文件
    if batch_number:
        input_path = output.get_process_path(f'batch_{batch_number}_ids.json')
        if not os.path.exists(input_path):
            print(f'错误：批次文件不存在：{input_path}')
            print(f'请先运行 recommend_list.py --batch {batch_number} 获取候选人列表')
            return [], []
    elif input_geek_ids:
        input_path = input_geek_ids
    else:
        input_path = output.recommend_geek_ids_path

    with open(input_path, 'r', encoding='utf-8') as f:
        geek_list = json.load(f)

    if not geek_list:
        print('候选人列表为空')
        return [], []

    # 从第一个候选人获取 jobId（优先 encryptJobId，兜底 jobId）
    gc = geek_list[0].get('geekCard', {}) if geek_list else {}
    job_id = gc.get('encryptJobId', '') or str(gc.get('jobId', ''))
    if not job_id:
        print('错误：无法从数据中获取 job_id')
        return [], []

    if batch_number:
        print(f'[分批模式] 第 {batch_number} 批')
    print(f'岗位：{job_name}')
    print(f'岗位 ID: {job_id}')
    print(f'本批候选人：{len(geek_list)} 人')
    if max_count:
        print(f'最大获取：{max_count}')

    resumes = []
    failed = []
    hit_limit = False
    start_time = datetime.now()
    print(f'\n开始时间：{start_time.strftime("%H:%M:%S")}\n')

    for i, g in enumerate(geek_list):
        if max_count and len(resumes) + len(failed) >= max_count:
            break

        geek_id = g.get('encryptGeekId', '')
        geek_card = g.get('geekCard', {})
        security_id = geek_card.get('securityId', '') if isinstance(geek_card, dict) else ''
        name = geek_card.get('geekName', '') if isinstance(geek_card, dict) else ''

        if not geek_id or not security_id:
            failed.append({'index': i + 1, 'name': name or 'Unknown', 'reason': 'no IDs'})
            continue

        delay = random.uniform(5, 20)
        elapsed = (datetime.now() - start_time).total_seconds() / 60
        print(f'[{elapsed:.1f}分钟] #{i + 1}: {name}...', end=' ', flush=True)

        cmd = [
            'boss.exe', '--role', 'recruiter', '--platform', 'zhipin',
            '--cdp-url', 'http://localhost:9222',
            'hr', 'resume', geek_id,
            '--security-id', security_id,
            '--job-id', job_id
        ]

        env = {**os.environ, 'PYTHONHOME': '', 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'}
        result = subprocess.run(cmd, capture_output=True, env=env)

        try:
            resp = json.loads(result.stdout)
            if resp.get('ok'):
                data = resp.get('data', {})
                zpdata = data.get('zpData', {}) if isinstance(data, dict) else {}
                block = zpData.get('blockDialog', {}) if isinstance(zpData, dict) else {}

                if block.get('title') and '上限' in block.get('title', ''):
                    print(f'已达上限：{block.get("title")}')
                    hit_limit = True
                    break
                elif data.get('basic'):
                    resumes.append({
                        'name': data.get('basic', {}).get('name', name),
                        'age': data.get('basic', {}).get('age'),
                        'degree': data.get('basic', {}).get('degree'),
                        'work_years': data.get('basic', {}).get('work_years'),
                        'expectation': data.get('expectation'),
                        'work_experience': data.get('work_experience', []),
                        'project_experience': data.get('project_experience', []),
                        'education': data.get('education', []),
                        'certifications': data.get('certifications', [])
                    })
                    print('OK')
                else:
                    print('数据为空')
                    failed.append({'index': i + 1, 'name': name, 'reason': 'empty'})
            else:
                err = resp.get('error', {}).get('message', '')
                print(f'失败：{err[:40]}')
                failed.append({'index': i + 1, 'name': name, 'reason': err[:50]})
        except Exception:
            raw = result.stdout[:100].decode('utf-8', errors='replace') if result.stdout else ''
            print(f'解析错误 ({raw})')
            failed.append({'index': i + 1, 'name': name, 'reason': 'parse error'})

        if not hit_limit and i < len(geek_list) - 1:
            time.sleep(delay)

    # 统计
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds() / 60

    print(f'\n{"=" * 40}')
    print(f'结束时间：{end_time.strftime("%H:%M:%S")}')
    print(f'总耗时：{duration:.1f} 分钟')
    print(f'成功：{len(resumes)} 份简历')
    print(f'失败：{len(failed)} 份')
    print(f'触发每日上限：{"是" if hit_limit else "否"}')

    if batch_number:
        # 分批模式：保存到 batch_N_resumes.json + 追加到 test_resumes.json
        batch_resumes_path = output.get_process_path(f'batch_{batch_number}_resumes.json')
        with open(batch_resumes_path, 'w', encoding='utf-8') as f:
            json.dump(resumes, f, ensure_ascii=False, indent=2)
        print(f'\n本批简历已保存到：{batch_resumes_path}')

        # 追加到累计文件
        cumulative_path = output.resumes_path
        existing_resumes = []
        if os.path.exists(cumulative_path):
            with open(cumulative_path, 'r', encoding='utf-8') as f:
                existing_resumes = json.load(f)

        existing_names = {r.get('name', '') for r in existing_resumes}
        for r in resumes:
            if r.get('name', '') not in existing_names:
                existing_resumes.append(r)
                existing_names.add(r.get('name', ''))

        with open(cumulative_path, 'w', encoding='utf-8') as f:
            json.dump(existing_resumes, f, ensure_ascii=False, indent=2)
        print(f'累计 {len(existing_resumes)} 份简历已保存到：{cumulative_path}')

        # 保存失败列表
        failed_path = output.get_process_path(f'batch_{batch_number}_failed.json')
        with open(failed_path, 'w', encoding='utf-8') as f:
            json.dump(failed, f, ensure_ascii=False, indent=2)
    else:
        # 普通模式
        with open(output.resumes_path, 'w', encoding='utf-8') as f:
            json.dump(resumes, f, ensure_ascii=False, indent=2)
        print(f'\n成功简历已保存到：{output.resumes_path}')

        failed_path = output.get_process_path('failed_resumes.json')
        with open(failed_path, 'w', encoding='utf-8') as f:
            json.dump(failed, f, ensure_ascii=False, indent=2)
        print(f'失败列表已保存到：{failed_path}')

    return resumes, failed


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='批量获取推荐牛人完整简历（支持分批）')
    parser.add_argument('--job-name', default='车架工程师', help='岗位名称')
    parser.add_argument('--input', default=None, help='候选人列表文件（默认使用 process 文件夹）')
    parser.add_argument('--max', type=int, default=None, help='最大获取数量')
    parser.add_argument('--batch', type=int, default=None, help='分批模式：第几批（从1开始）')

    args = parser.parse_args()
    download_resumes(args.job_name, args.input, args.max, args.batch)
