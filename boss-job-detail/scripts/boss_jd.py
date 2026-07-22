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
        page.goto(target, wait_until="networkidle", timeout=30000)

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
    args = parser.parse_args()

    eid, name = resolve_encrypt_id(args.query)
    if not eid:
        print(f"Job not found: {args.query}")
        sys.exit(1)

    print(f"Found: {name} ({eid})")
    raw = fetch_jd(eid)

    job_name = args.job_name or _safe_name(name)
    output = JobOutputManager(job_name)

    save_data = {
        "jobName": name,
        "encryptJobId": eid,
        "bodyText": raw.get("bodyText", ""),
        "formValues": raw.get("formValues", []),
    }
    out_path = Path(output.jd_path)
    out_path.write_text(json.dumps(save_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved to {out_path}")
    print("OK")
