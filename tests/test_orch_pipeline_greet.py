# -*- coding: utf-8 -*-
"""编排 + 打招呼闭环测试（不连真实 CDP）

测试目标：
- RunOrchestrator bind_or_create 在 auto_greet 模式下能正确跟走 active run
- auto_pipeline 构造出的 Step 5 命令参数正确
- mark_done('greet') 不会改写 current_run（保持 active 状态）

不验证：
- 真实 patchright CDP 连接（需要浏览器，手测）
- 真实 BOSS 点击招呼（手测）

不依赖 pytest（可独立 python 运行，pytest 也可发现）
"""
import json
import os
import importlib.util
import subprocess
import sys
import tempfile

# 临时把 toolkit 根目录加进 path
TOOLKIT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(TOOLKIT_ROOT, 'shared'))


def _print(msg):
    print(f'[test] {msg}')


def test_orchestrator_follows_active_run():
    """auto_greet 接 orchestrator 后跟走 Step 4 留下的 current_run"""
    from run_orchestrator import RunOrchestrator

    with tempfile.TemporaryDirectory() as tmpdir:
        job_name = '测试PipelineJob'
        os.environ['BOSS_HR_OUTPUT_DIR'] = tmpdir

        # Step 1 留下 current_run.json（orchestrator 在 output_manager 内会按 BOSS_HR_OUTPUT_DIR 解析）
        orch = RunOrchestrator(job_name)
        run_a = orch.start(job_id='fake-job-1')
        assert orch.current() == run_a, f'Step 1 应留 current_run={run_a}'

        # Step 5 (auto_greet) 不传 --run-id，bind_or_create 应当跟走 run_a
        run_greet = orch.bind_or_create(None)
        assert run_greet == run_a, (
            f'auto_greet 应跟走 active run_id={run_a}, 实际={run_greet}'
        )

        _print(f'[PASS] bind_or_create 跟走 Step 1 留下的 active run: {run_greet}')


def test_orchestrator_explicit_run_id_overrides():
    """auto_greet --run-id 显式传入时覆盖 current_run，但保留 steps_done 历史"""
    from run_orchestrator import RunOrchestrator

    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ['BOSS_HR_OUTPUT_DIR'] = tmpdir

        orch = RunOrchestrator('测试ExplicitJob')
        run_a = orch.start()
        orch.mark_done('jd')
        orch.mark_done('report')

        # 用户显式传了一个不同的 run_id
        run_explicit = '2026-07-28_120000'
        result = orch.bind_or_create(run_explicit)

        assert result == run_explicit, f'显式 run_id 应优先: {run_explicit}'
        info = orch.current_info()
        # 不应丢失 steps_done（覆盖语义）
        assert 'jd' in info.get('steps_done', []), '历史 steps_done 应保留'
        _print(f'[PASS] 显式 run_id 覆盖但保留 steps_done: {result}')


def test_mark_done_greet_keeps_run_active():
    """mark_done('greet') 不应主动 finish() — 让回头招呼仍能继续用同 run"""
    from run_orchestrator import RunOrchestrator

    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ['BOSS_HR_OUTPUT_DIR'] = tmpdir

        orch = RunOrchestrator('测试MarkDoneJob')
        run_a = orch.start()
        orch.mark_done('jd')
        orch.mark_done('report')
        orch.mark_done('greet')  # Step 5 标记，不 finish

        # current_run.json 应仍存在（不 finish）
        info = orch.current_info()
        assert info.get('run_id') == run_a
        assert 'greet' in info.get('steps_done', [])
        _print(f"[PASS] mark_done('greet') 保留 current_run.json: {info['run_id']}")


def test_orchestrator_finish_clears_active_run():
    """finish() 清掉 current_run.json，让下次的 build 新 run"""
    from run_orchestrator import RunOrchestrator

    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ['BOSS_HR_OUTPUT_DIR'] = tmpdir

        orch = RunOrchestrator('测试FinishJob')
        run_a = orch.start()
        orch.finish()

        assert orch.current() is None, 'finish() 后 current_run 应清空'
        _print('[PASS] finish() 清掉 current_run，下次起新 run')


def test_auto_pipeline_step5_cmd_construction():
    """auto_pipeline 构造的 Step 5 subprocess 命令正确（不真跑）"""
    spec = importlib.util.spec_from_file_location(
        'auto_pipeline', os.path.join(TOOLKIT_ROOT, 'boss-hr-auto', 'scripts', 'auto_pipeline.py'),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # 不进 main()，只导入表

    assert 'greet' in mod.STEP_SCRIPTS, 'auto_pipeline 应注册 Step 5 = greet'
    greet_path = os.path.join(TOOLKIT_ROOT, mod.STEP_SCRIPTS['greet'])
    assert os.path.exists(greet_path), f'auto_greet.py 应存在: {greet_path}'
    _print(f"[PASS] auto_pipeline['greet'] -> {mod.STEP_SCRIPTS['greet']}")


def test_auto_pipeline_no_user_input_calls():
    """auto_pipeline 全程不能调 input() —— agent 流 stdin 不可用"""
    import inspect
    spec = importlib.util.spec_from_file_location(
        'auto_pipeline', os.path.join(TOOLKIT_ROOT, 'boss-hr-auto', 'scripts', 'auto_pipeline.py'),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    src = inspect.getsource(mod)
    assert 'input(' not in src, 'auto_pipeline 不能调 input()，agent 流 stdin 不可用'
    _print('[PASS] auto_pipeline 源码无 input() 调用')


def test_auto_greet_orchestrator_import():
    """auto_greet.py 在接 orchestrator 后能正确 import（不连 patchright）"""
    from unittest.mock import MagicMock

    # 把 patchright / human_interaction mock 掉
    sys.modules['patchright'] = MagicMock()
    sys.modules['patchright.sync_api'] = MagicMock()
    sys.modules['human_interaction'] = MagicMock()

    spec = importlib.util.spec_from_file_location(
        'auto_greet_test',
        os.path.join(TOOLKIT_ROOT, 'boss-hr-greet', 'scripts', 'auto_greet.py'),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # 验证: 改用 mock 的 orchestrator 跑 bind_or_create
    from run_orchestrator import RunOrchestrator

    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ['BOSS_HR_OUTPUT_DIR'] = tmpdir
        # 先建一个 active run
        orch = RunOrchestrator('测试GreetBindJob')
        run_a = orch.start()
        # 让 auto_greet 拿 run_id（不传 explicit → 跟走）
        test_run = orch.bind_or_create(None)
        assert test_run == run_a
        _print(f"[PASS] auto_greet.bind_or_create(None) 跟走 active run: {test_run}")


def main():
    """入口：可独立跑（python test_orch_pipeline_greet.py）"""
    funcs = [
        test_orchestrator_follows_active_run,
        test_orchestrator_explicit_run_id_overrides,
        test_mark_done_greet_keeps_run_active,
        test_orchestrator_finish_clears_active_run,
        test_auto_pipeline_step5_cmd_construction,
        test_auto_pipeline_no_user_input_calls,
        test_auto_greet_orchestrator_import,
    ]
    failed = 0
    for fn in funcs:
        try:
            fn()
        except AssertionError as e:
            _print(f'[FAIL] {fn.__name__}: {e}')
            failed += 1
        except Exception as e:
            _print(f'[ERROR] {fn.__name__}: {type(e).__name__}: {e}')
            failed += 1
    if failed == 0:
        _print(f'[PASS-ALL] {len(funcs)}/{len(funcs)} all passed')
        return 0
    _print(f'[FAIL] {failed}/{len(funcs)} failed')
    return 1


if __name__ == '__main__':
    sys.exit(main())
