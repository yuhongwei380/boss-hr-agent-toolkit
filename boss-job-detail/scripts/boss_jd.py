"""Get BOSS job detail (JD) via CDP browser.

Usage: 
  python boss_jd.py <encryptJobId|jobId|职位名> [--job-name <name>]

Output: <job-name>/process/job_detail.json
"""
import json, sys, subprocess, time, os, re, argparse
from pathlib import Path
from patchright.sync_api import sync_playwright

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
import fix_encoding  # noqa: E402  # 强制 Windows UTF-8 stdout
from output_manager import JobOutputManager

CDP_URL = "http://localhost:9222"

_BOSS_ENV = {**os.environ, "PYTHONHOME": "", "PYTHONIOENCODING": "utf-8"}


def _safe_name(name: str) -> str:
    """清洗岗位名为合法目录名"""
    return re.sub(r'[\\/:*?"<>|\s]+', '-', name).strip('-') or 'job'


def resolve_encrypt_id(query):
    result = subprocess.run(
        ["boss", "--role", "recruiter", "--cdp-url", CDP_URL, "hr", "jobs", "list"],
        capture_output=True, timeout=15, env=_BOSS_ENV
    )
    data = json.loads(result.stdout.decode("utf-8"))
    exact = partial = None
    for job in data.get("data", []):
        name = job.get("jobName", "")
        eid = job.get("encryptJobId", "")
        jid = str(job.get("jobId", ""))
        if query == eid or query == jid:
            return eid, name
        if query == name:
            exact = (eid, name)
        elif query in name and not partial:
            partial = (eid, name)
    return exact or partial or (None, None)


def fetch_jd(encrypt_job_id):
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)

        pages = browser.contexts[0].pages if browser.contexts else []
        page = pages[0] if pages else browser.contexts[0].new_page()

        target = f"https://www.zhipin.com/web/chat/job/edit?encryptId={encrypt_job_id}&jobCreateSource=0&enterSource=6"
        # BOSS 该页是 iframe + 长轮询（IM 心跳），networkidle 常等不到 → 只等 DOM ready
        page.goto(target, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass  # 长轮询导致 networkidle 永不触发，属正常

        body_text = ""
        form_vals = []

        try:
            iframe = page.wait_for_selector("iframe", timeout=15000)
            frame = iframe.content_frame()
            frame.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception as e:
            print(f"  iframe wait: {e}")

        # Extract from iframe
        iframe_el = page.query_selector("iframe")
        if iframe_el:
            frame = iframe_el.content_frame()
            if frame:
                body_text = frame.evaluate("document.body.innerText")

                # Retry if loading
                if not body_text or "正在加载" in body_text:
                    time.sleep(3)
                    body_text = frame.evaluate("document.body.innerText")

                # Get all form values
                form_vals = frame.evaluate("""(() => {
                    const r = [];
                    document.querySelectorAll('input:not([type=hidden]), textarea, [contenteditable]').forEach(el => {
                        const v = el.value || el.innerText || '';
                        if (v && v.length > 3 && v !== '保存') r.push(v);
                    });
                    return r;
                })()""")

        if not body_text:
            body_text = page.evaluate("document.body.innerText")

        browser.close()
        return {"bodyText": body_text, "formValues": form_vals}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Get BOSS job detail (JD) via CDP')
    parser.add_argument('query', help='encryptJobId | jobId | 职位名')
    parser.add_argument('--job-name', default=None,
                        help='工作区目录名（默认自动用 jobName 清洗为合法目录名）')
    parser.add_argument('--run-id', default=None,
                        help='本次 run ID（默认自动生成；同一 run 内的所有产物落同一 runs/<run_id>/）')
    parser.add_argument('--force', action='store_true',
                        help='强制覆盖已有 run（同 run 内补写 job_detail.json 用）')
    args = parser.parse_args()

    eid, name = resolve_encrypt_id(args.query)
    if not eid:
        print(f"Job not found: {args.query}")
        sys.exit(1)

    print(f"Found: {name} ({eid})")
    raw = fetch_jd(eid)

    job_name = args.job_name or _safe_name(name)

    # 默认走 orchestrator，让 Step 2/3/4 自动绑定同一 run_id
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
    from run_orchestrator import RunOrchestrator
    orch = RunOrchestrator(job_name)
    run_id = orch.bind_or_create(args.run_id, job_id=eid, force=getattr(args, 'force', False))

    output = JobOutputManager(job_name, run_id=run_id)
    output.ensure_run_dir()
    print(f"run_id: {run_id}（orchestrator 绑定）")

    # 异常护栏：脚本崩溃时若没写出 job_detail.json，自动清空 run_dir
    import atexit
    _SAVED = False

    def _auto_prune():
        if not _SAVED and output.prune_if_empty():
            print(f'⚠️  本次 run 未产生 job_detail.json，已清理: {output.run_dir}')

    atexit.register(_auto_prune)

    save_data = {
        "jobName": name,
        "encryptJobId": eid,
        "bodyText": raw.get("bodyText", ""),
        "formValues": raw.get("formValues", []),
        "_meta": {
            "run_id": output.run_id,
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
    }
    out_path = Path(output.jd_path)
    out_path.write_text(json.dumps(save_data, ensure_ascii=False, indent=2), encoding="utf-8")
    _SAVED = True  # 成功落盘，保留 run
    orch.mark_done('jd', run_id=run_id)  # 标记 jd 步骤完成，下游可跟走
    print(f"Saved to {out_path}")
    print(f"run_id: {output.run_id}")
    print("OK")
