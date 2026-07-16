# boss-hr-agent-toolkit 文件管理规范

## 📁 统一输出结构

所有 skill 产生的文件必须遵循以下结构：

```
~/Desktop/boss-hr-output/                    # 所有输出放这里
└── <岗位名>/                                  # 按岗位名建子文件夹
    ├── <岗位名>_简历筛选报告.html              # 最终 HTML 报告
    └── process/                               # 过程文件（留痕查阅）
        ├── job_detail.json                    # JD 数据
        ├── recommend_geek_ids.json            # 候选人 ID 列表
        ├── test_resumes.json                  # 完整简历数据
        ├── screening_results.json             # 评分结果
        └── failed_resumes.json                # 失败列表
```

## 🚨 重要规则

### 1. 禁止在桌面散落文件
- ❌ 错误：`~/Desktop/test_resumes.json`
- ✅ 正确：`~/Desktop/boss-hr-output/车架工程师/process/test_resumes.json`

### 2. HTML 报告放岗位文件夹根目录
- ❌ 错误：`~/Desktop/boss-hr-output/车架工程师/process/报告.html`
- ✅ 正确：`~/Desktop/boss-hr-output/车架工程师/车架工程师_简历筛选报告.html`

### 3. 中间数据放 process/ 子文件夹
- 所有 JSON 数据文件
- 所有临时日志文件
- 所有中间计算结果

### 4. 临时 Python 脚本任务结束后删除
- ❌ 错误：任务完成后 `generate_report.py` 还留在桌面
- ✅ 正确：调用 `output.cleanup_temp_scripts()` 清理

### 5. 复用 skill 内已有的 Python 脚本
- ❌ 错误：智能体重新写一个 `generate_report.py`
- ✅ 正确：使用 skill 的 `scripts/` 文件夹中已有的脚本

### 6. 岗位文件夹不存在时自动创建
- 不要询问用户，直接创建
- 使用 `os.makedirs(JOB_DIR, exist_ok=True)`

## 🔧 使用方法

### 在 Python 脚本中

```python
import sys
import os

# 添加 shared 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))
from output_manager import JobOutputManager

# 初始化输出管理器
output = JobOutputManager('车架工程师')

# 获取文件路径
print(output.report_path)           # HTML 报告路径
print(output.jd_path)               # JD 数据路径
print(output.resumes_path)          # 简历数据路径
print(output.recommend_geek_ids_path)  # 候选人 ID 路径

# 保存数据
with open(output.resumes_path, 'w', encoding='utf-8') as f:
    json.dump(resumes, f, ensure_ascii=False, indent=2)

# 任务结束后清理临时脚本
output.cleanup_temp_scripts()
```

### 在 Skill 文档中

所有 skill 的 SKILL.md 必须包含：

```markdown
### 输出文件

本 skill 产生的文件：
- `<岗位名>_xxx.html` → `~/Desktop/boss-hr-output/<岗位名>/`
- `xxx.json` → `~/Desktop/boss-hr-output/<岗位名>/process/`

使用 `output_manager.py` 获取文件路径，不要硬编码路径。
```

##  已有 Python 脚本清单

以下脚本位于各 skill 的 `scripts/` 文件夹中，**必须复用，禁止重复造轮子**：

### boss-recommend-downloader/scripts/
- `recommend_list.py` — 获取推荐牛人候选人列表
- `recommend_download.py` — 批量获取完整简历
- `run_all.py` — 一键运行全流程

### shared/
- `output_manager.py` — 统一文件路径管理（所有 skill 共用）

## 🧹 清理桌面散落文件

如果桌面已经有散落文件，运行以下命令清理：

```python
import os

desktop = os.path.expanduser('~/Desktop')
temp_files = [
    'generate_report.py',
    'generate_report_corrected.py',
    'generate_report_v2.py',
    'job_detail.json',
    'recommend_geek_ids.json',
    'screening_results.json',
    'screening_results_corrected.json',
    'test_resumes.json',
    'schools.txt',
    'resume_preview.txt',
    'boss_api_data.json',
    'boss_recommend_page.png'
]

for f in temp_files:
    path = os.path.join(desktop, f)
    if os.path.exists(path):
        os.remove(path)
        print(f'已删除：{f}')
```

## 📖 示例：完整工作流

```bash
# 1. 创建岗位文件夹（自动）
# 2. 获取 JD → 保存到 process/job_detail.json
# 3. 获取候选人列表 → 保存到 process/recommend_geek_ids.json
# 4. 下载完整简历 → 保存到 process/test_resumes.json
# 5. 评分 → 保存到 process/screening_results.json
# 6. 生成报告 → 保存到 <岗位名>_简历筛选报告.html
# 7. 清理临时脚本 → 删除 generate_report.py 等
```

最终交付给用户的只有一个 HTML 报告，其他都是留痕查阅的过程文件。
