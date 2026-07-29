# -*- coding: utf-8 -*-
"""跨 Step run_id 编排测试（不连真实 CDP）

测试目标：
- bind_or_create 不传 run_id 时跟走 current_run.json 的 active run
- 显式传 run_id 时覆盖，且不丢 steps_done 历史
- mark_done('greet') 不 finish，回头招呼仍能用同一 run
- finish() 标记 finished=true，下次 bind_or_create 起新 run

不验证：
- 真实 patchright CDP 连接（需要浏览器，手测）
- 真实 BOSS 点击招呼（手测）

不依赖 pytest（可独立 python 运行，pytest 也可发现）

注：本文件原有 3 个 auto_pipeline 相关测试已于 2026-07-29 删除 ——
auto_pipeline.py 是某次更新中自动生成的多余编排层，从未进过 git，
已随 boss-hr-auto/scripts/ 一并移除。全流程改由智能体按 SKILL.md 逐步调子脚本。
"""
import json
import os
import sys
import tempfile

# 临时把 toolkit 根目录加进 path
TOOLKIT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(TOOLKIT_ROOT, 'shared'))


def _print(msg):
    print(f'[test] {msg}')


def test_orchestrator_follows_active_run():
    """Step 5 不传 --run-id 时，跟走前面 Step 留下的 current_run"""
    from run_orchestrator import RunOrchestrator

    with tempfile.TemporaryDirectory() as tmpdir:
        job_name = '测试PipelineJob'
        os.environ['BOSS_HR_OUTPUT_DIR'] = tmpdir

        # Step 1 建立 active run
        orch = RunOrchestrator(job_name)
        run_a = orch.bind_or_create(job_id='fake-job-1')
        assert orch._load_current().get('run_id') == run_a, \
            f'Step 1 应留 current_run={run_a}'

        # Step 5 (auto_greet) 不传 --run-id → 应跟走 run_a
        run_greet = orch.bind_or_create(None)
        assert run_greet == run_a, (
            f'auto_greet 应跟走 active run_id={run_a}, 实际={run_greet}'
        )

        _print(f'[PASS] bind_or_create 跟走 Step 1 留下的 active run: {run_greet}')


def test_orchestrator_explicit_run_id_overrides():
    """显式传 --run-id 时覆盖 current_run（开新一轮，steps_done 重置）"""
    from run_orchestrator import RunOrchestrator

    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ['BOSS_HR_OUTPUT_DIR'] = tmpdir

        orch = RunOrchestrator('测试ExplicitJob')
        run_a = orch.bind_or_create()
        orch.mark_done('jd')
        orch.mark_done('report')

        # 用户显式传了一个不同的 run_id
        run_explicit = '2026-07-28_120000'
        result = orch.bind_or_create(run_explicit)

        assert result == run_explicit, f'显式 run_id 应优先: {run_explicit}'
        info = orch._load_current()
        assert info.get('run_id') == run_explicit, 'current_run 应更新为显式 run_id'
        # 切到新 run_id = 开新一轮，不继承旧 run 的步骤记录
        # （若继承，会让人误以为新 run 已跑过 jd/report）
        assert info.get('steps_done') == [], '显式切 run 应重置 steps_done'
        _print(f'[PASS] 显式 run_id 覆盖并重置 steps_done: {result}')


def test_mark_done_greet_keeps_run_active():
    """mark_done('greet') 不应主动 finish() — 让回头招呼仍能继续用同 run"""
    from run_orchestrator import RunOrchestrator

    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ['BOSS_HR_OUTPUT_DIR'] = tmpdir

        orch = RunOrchestrator('测试MarkDoneJob')
        run_a = orch.bind_or_create()
        orch.mark_done('jd')
        orch.mark_done('report')
        orch.mark_done('greet')  # Step 5 标记，不 finish

        info = orch._load_current()
        assert info.get('run_id') == run_a
        assert 'greet' in info.get('steps_done', [])
        assert not info.get('finished'), "mark_done('greet') 不应标记 finished"

        # 关键：回头再招呼时仍跟走同一个 run
        assert orch.bind_or_create(None) == run_a, '未 finish 的 run 应可继续沿用'
        _print(f"[PASS] mark_done('greet') 保留 active run: {run_a}")


def test_orchestrator_finish_clears_active_run():
    """finish() 标记 finished=true，下次 bind_or_create 起新 run"""
    import time
    from run_orchestrator import RunOrchestrator

    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ['BOSS_HR_OUTPUT_DIR'] = tmpdir

        orch = RunOrchestrator('测试FinishJob')
        run_a = orch.bind_or_create()
        orch.mark_done('jd')
        orch.finish()

        # 新语义：不删文件，只标 finished=true（保留留痕）
        info = orch._load_current()
        assert info.get('finished') is True, 'finish() 应标记 finished=true'

        # run_id 按秒生成，同秒内会撞出相同 ID —— 跨秒后再验证
        time.sleep(1.1)
        run_b = orch.bind_or_create(None)
        assert run_b != run_a, f'finish 后应起新 run，实际仍是 {run_a}'
        _print(f'[PASS] finish() 后起新 run: {run_a} → {run_b}')


def test_scored_state_dedup_roundtrip():
    """评分去重：mark_scored 后 is_scored 应为 True，且按 geek_id 而非姓名"""
    import output_manager
    from job_resume_store import JobResumeStore

    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ['BOSS_HR_OUTPUT_DIR'] = tmpdir
        # OUTPUT_ROOT 是模块级常量，import 时已固化 —— 必须 patch 模块属性，
        # 否则前面测试先 import 后，这里改 env 无效（会写到真实目录）
        _saved_root = output_manager.OUTPUT_ROOT
        output_manager.OUTPUT_ROOT = tmpdir
        try:
            store = JobResumeStore('测试ScoredJob', encrypt_job_id='job-1')
            assert tmpdir in store.state_dir, \
                f'测试隔离失败，state_dir 落在 {store.state_dir}'
            assert not store.is_scored('job-1', 'geek-A'), '初始应未评分'

            store.mark_scored('job-1', 'geek-A', name='张三', total=72.5,
                              tier='推荐', run_id='run-1')
            assert store.is_scored('job-1', 'geek-A'), 'mark_scored 后应已评分'

            rec = store.get_score_record('job-1', 'geek-A')
            assert rec['total'] == 72.5 and rec['tier'] == '推荐'
            assert rec['first_run_id'] == 'run-1'

            # 同名不同 ID 的候选人不应被误判为已评分（重名不误杀）
            assert not store.is_scored('job-1', 'geek-B'), '不同 geek_id 应独立计算'

            # 重复评分：保留首次 run_id，累加 times
            store.mark_scored('job-1', 'geek-A', name='张三', total=80.0,
                              tier='推荐', run_id='run-2')
            rec2 = store.get_score_record('job-1', 'geek-A')
            assert rec2['first_run_id'] == 'run-1', '首次 run_id 应保留'
            assert rec2['last_run_id'] == 'run-2'
            assert rec2['times'] == 2
            _print('[PASS] scored_state 去重按 geek_id，重名不误杀')
        finally:
            output_manager.OUTPUT_ROOT = _saved_root


def main():
    """入口：可独立跑（python test_orch_pipeline_greet.py）

    注意：pytest 下由 conftest.py 的 autouse fixture 做输出隔离；
    独立运行时没有 fixture，这里手工 patch OUTPUT_ROOT，
    否则会在用户真实的 ~/Desktop/boss-hr-output/ 留下测试文件夹。
    """
    import output_manager

    funcs = [
        test_orchestrator_follows_active_run,
        test_orchestrator_explicit_run_id_overrides,
        test_mark_done_greet_keeps_run_active,
        test_orchestrator_finish_clears_active_run,
        test_scored_state_dedup_roundtrip,
    ]
    failed = 0
    with tempfile.TemporaryDirectory() as sandbox:
        _saved = output_manager.OUTPUT_ROOT
        output_manager.OUTPUT_ROOT = sandbox
        os.environ['BOSS_HR_OUTPUT_DIR'] = sandbox
        try:
            for fn in funcs:
                try:
                    fn()
                except AssertionError as e:
                    _print(f'[FAIL] {fn.__name__}: {e}')
                    failed += 1
                except Exception as e:
                    _print(f'[ERROR] {fn.__name__}: {type(e).__name__}: {e}')
                    failed += 1
        finally:
            output_manager.OUTPUT_ROOT = _saved
    if failed == 0:
        _print(f'[PASS-ALL] {len(funcs)}/{len(funcs)} all passed')
        return 0
    _print(f'[FAIL] {failed}/{len(funcs)} failed')
    return 1


if __name__ == '__main__':
    sys.exit(main())
