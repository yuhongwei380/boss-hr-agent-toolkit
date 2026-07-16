#!/usr/bin/env python3
"""
推荐牛人简历批量下载脚本
Step 2: 使用 CLI 批量获取完整简历

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
                     max_count=None):
    """
    批量获取完整简历

    Args:
        job_name: 岗位名称
        input_geek_ids: 候选人列表文件路径（为 None 时使用默认路径）
        max_count: 最大获取数量
    """
    # 初始化输出管理器
    output = JobOutputManager(job_name)

    # 读取候选人列表
    if input_geek_ids is None:
        input_geek_ids = output.recommend_geek_ids_path

    with open(input_geek_ids, 'r', encoding='utf-8') as f:
        geek_list = json.load(f)

    # 尝试从第一个候选人获取 jobId
    job_id = geek_list[0].get('geekCard', {}).get('encJobId', '') if geek_list else ''
    if not job_id:
        print('错误：无法从数据中获取 job_id')
        return

    print(f'岗位：{job_name}')
    print(f'岗位 ID: {job_id}')
    print(f'候选人总数：{len(geek_list)}')
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

        # 随机延迟 5-20 秒（模拟真人看简历的时间）
        delay = random.uniform(5, 20)

        elapsed = (datetime.now() - start_time).total_seconds() / 60
        print(f'[{elapsed:.1f}分钟] #{i + 1}: {name}...', end=' ', flush=True)

        # 调用 CLI 获取简历
        cmd = [
            'boss.exe', '--role', 'recruiter', '--platform', 'zhipin',
            '--cdp-url', 'http://localhost:9222',
            'hr', 'resume', geek_id,
            '--security-id', security_id,
            '--job-id', job_id
        ]

        result = subprocess.run(cmd, capture_output=True)
        stdout = result.stdout.decode('utf-8', errors='ignore')

        try:
            resp = json.loads(stdout)
            if resp.get('ok'):
                data = resp.get('data', {})
                zpdata = data.get('zpData', {}) if isinstance(data, dict) else {}
                block = zpdata.get('blockDialog', {}) if isinstance(zpdata, dict) else {}

                # 检查是否触发每日上限
                if block.get('title') and '上限' in block.get('title', ''):
                    print(f'已达上限：{block.get("title")}')
                    hit_limit = True
                    break
                elif data.get('basic'):
                    # 提取完整简历
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
        except:
            print('解析错误')
            failed.append({'index': i + 1, 'name': name, 'reason': 'parse error'})

        # 随机延迟
        if not hit_limit and i < len(geek_list) - 1:
            time.sleep(delay)

    # 统计结果
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds() / 60

    print(f'\n{"=" * 40}')
    print(f'结束时间：{end_time.strftime("%H:%M:%S")}')
    print(f'总耗时：{duration:.1f} 分钟')
    print(f'成功：{len(resumes)} 份简历')
    print(f'失败：{len(failed)} 份')
    print(f'触发每日上限：{"是" if hit_limit else "否"}')

    # 保存到 process 文件夹
    with open(output.resumes_path, 'w', encoding='utf-8') as f:
        json.dump(resumes, f, ensure_ascii=False, indent=2)

    failed_path = output.get_process_path('failed_resumes.json')
    with open(failed_path, 'w', encoding='utf-8') as f:
        json.dump(failed, f, ensure_ascii=False, indent=2)

    print(f'\n成功简历已保存到：{output.resumes_path}')
    print(f'失败列表已保存到：{failed_path}')

    return resumes, failed


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='批量获取推荐牛人完整简历')
    parser.add_argument('--job-name', default='车架工程师', help='岗位名称')
    parser.add_argument('--input', default=None, help='候选人列表文件（默认使用 process 文件夹）')
    parser.add_argument('--max', type=int, default=None, help='最大获取数量')

    args = parser.parse_args()
    download_resumes(args.job_name, args.input, args.max)
