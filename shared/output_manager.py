#!/usr/bin/env python3
"""
文件路径管理工具
所有 skill 必须使用此工具获取文件路径，确保输出结构统一
"""

import os

# 输出根目录
OUTPUT_ROOT = os.path.expanduser('~/Desktop/boss-hr-output')

class JobOutputManager:
    """岗位输出管理器 - 所有 skill 共用"""

    def __init__(self, job_name):
        """
        Args:
            job_name: 岗位名称（如"车架工程师"）
        """
        self.job_name = job_name
        self.job_dir = os.path.join(OUTPUT_ROOT, job_name)
        self.process_dir = os.path.join(self.job_dir, 'process')

        # 自动创建文件夹
        os.makedirs(self.job_dir, exist_ok=True)
        os.makedirs(self.process_dir, exist_ok=True)

    # 最终报告路径
    @property
    def report_path(self):
        return os.path.join(self.job_dir, f'{self.job_name}_简历筛选报告.html')

    # 过程文件路径
    @property
    def jd_path(self):
        return os.path.join(self.process_dir, 'job_detail.json')

    @property
    def recommend_geek_ids_path(self):
        return os.path.join(self.process_dir, 'recommend_geek_ids.json')

    @property
    def resumes_path(self):
        return os.path.join(self.process_dir, 'test_resumes.json')

    @property
    def screening_results_path(self):
        return os.path.join(self.process_dir, 'screening_results.json')

    def get_process_path(self, filename):
        """获取 process 文件夹中的文件路径"""
        return os.path.join(self.process_dir, filename)

    def cleanup_temp_scripts(self):
        """清理临时 Python 脚本（任务结束后调用）"""
        temp_scripts = [
            'generate_report.py',
            'generate_report_corrected.py',
            'generate_report_v2.py',
            'generate_report_v2.py'
        ]
        desktop = os.path.expanduser('~/Desktop')
        for script in temp_scripts:
            path = os.path.join(desktop, script)
            if os.path.exists(path):
                os.remove(path)
                print(f'已删除临时脚本：{script}')


# 使用示例
if __name__ == '__main__':
    # 示例：车架工程师岗位
    output = JobOutputManager('车架工程师')

    print(f'岗位文件夹：{output.job_dir}')
    print(f'过程文件夹：{output.process_dir}')
    print(f'报告路径：{output.report_path}')
    print(f'JD 路径：{output.jd_path}')
    print(f'简历路径：{output.resumes_path}')
