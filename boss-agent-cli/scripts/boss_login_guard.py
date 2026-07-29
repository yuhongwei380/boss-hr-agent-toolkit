#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BOSS 直聘登录守卫（login guard）— 登录状态机 + 强信号验收。

五个子命令：

  check            检查凭证状态（不改动任何东西）。可用 --purpose 分级。
  open-login       确保 CDP 浏览器运行，并打开 BOSS 登录页（等用户扫码）。
  open-login-force 强制重新登录：清 session.enc + 清浏览器 BOSS Cookie + 打开登录页。
                   用于"上次登录是假阳性 / CLI 显示已登录但用户没扫码"的场景。
  extract          执行 `boss login --cdp` 提取凭证并复检（degraded 时自动重试一次）。
  ensure-stoken    访问 www.zhipin.com 触发 __zp_stoken__ 注入，然后再 extract。
                   用于浏览器里有 stoken 但 session.enc 缺 stoken 的场景。

退出码（所有子命令一致）：
  0  ready            basic 三条验收通过 / resume 三条验收通过，stoken 缺失仅告警
  2  degraded         CLI 视角凭证不完整（仅 CLI 命令依赖 stoken 时提示）
  3  not_logged_in    未登录 → 运行 open-login，用户扫码后再 extract
  4  cdp_unreachable  CDP 不可用 / CLI 异常 → 运行 open-login（会自动拉起浏览器）

验收标准（强信号，按用途分级）：

  --purpose basic (默认，Step 1 JD 提取 / Step 0 登录验证)：
    1. `boss status --live`：logged_in=true 且 live=true
    2. `hr jobs list` 返回 ok=true
    （stoken 缺失不阻塞 basic 用途）

  --purpose resume (Step 2 简历下载 — 历史概念)：
    1 + 2（stoken 缺失只告警，不阻断）
    说明：hr-auto 全流程走 patchright 直连 CDP 浏览器（用浏览器 wt2/zp_at/bst），
    实际并不依赖 boss CLI 的 stoken。Stoken 补丁脚本仍保留为 `ensure-stoken` /
    `patch_stoken.py`，需要用 boss CLI 命令（非本工具包）时手动触发。

典型流程（由 agent 编排）：
  python boss_login_guard.py check                     # Step 0/1 用 basic
  → ready? 继续后续任务
  → degraded? python boss_login_guard.py ensure-stoken # 优先试无扫码修复
  → not_logged_in / cdp_unreachable?
      python boss_login_guard.py open-login-force      # 强制清旧 session 再扫
      （agent 明确告知用户：请扫码登录）
      用户确认已扫码后：
      python boss_login_guard.py extract
  → extract 仍非 ready：停止流程，向用户报告缺失项，禁止带病继续。

  Step 2 简历下载前：
  python boss_login_guard.py check --purpose resume    # 必须 full

输出：stdout 仅 JSON（UTF-8），供 agent 解析。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# Windows 上强制 stdout/stderr 使用 UTF-8，避免中文输出被 GBK 编码
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

CDP_URL = "http://localhost:9222"
LOGIN_URL = "https://www.zhipin.com/web/user/?ka=header-login"

EXIT_READY = 0
EXIT_DEGRADED = 2
EXIT_NOT_LOGGED_IN = 3
EXIT_UNREACHABLE = 4

_VERDICT_EXIT = {
    "ready": EXIT_READY,
    "degraded": EXIT_DEGRADED,
    "not_logged_in": EXIT_NOT_LOGGED_IN,
    "cdp_unreachable": EXIT_UNREACHABLE,
    "cli_error": EXIT_UNREACHABLE,
}

BROWSER_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]

_CREATE_FLAGS = 0
if os.name == "nt":
    _CREATE_FLAGS = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

_BOSS_BIN: str | None = None


# ---------------------------------------------------------------------------
# boss CLI invocation
# ---------------------------------------------------------------------------

def _run_boss(args: list[str], timeout: int = 45) -> tuple[dict, str]:
    """Run boss CLI (recruiter/zhipin/CDP fixed) and return (parsed_json, raw).

    ⚠️ Windows 上 BOSS CLI stdout 是 GBK 编码，必须按 GBK 解码，否则中文全部乱码。
    """
    global _BOSS_BIN
    cmd = [
        _BOSS_BIN or "boss",
        "--role", "recruiter",
        "--platform", "zhipin",
        "--cdp-url", CDP_URL,
    ] + args
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("PYTHONHOME", None)  # Windows 上 PYTHONHOME 冲突会让 CLI 起不来
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env)
    except FileNotFoundError:
        fallback = str(Path.home() / "bin" / "boss.cmd")
        if not _BOSS_BIN and Path(fallback).exists():
            _BOSS_BIN = fallback
            return _run_boss(args, timeout=timeout)
        return {}, ""
    except subprocess.TimeoutExpired:
        return {}, ""
    # Windows CLI 输出是 GBK；先按 GBK 解，失败再回退 UTF-8
    for enc in ("gbk", "utf-8"):
        try:
            raw = r.stdout.decode(enc, "strict").strip()
            break
        except UnicodeDecodeError:
            continue
    else:
        raw = r.stdout.decode("utf-8", "ignore").strip()
    if not raw:
        return {}, ""
    try:
        return json.loads(raw), raw
    except json.JSONDecodeError:
        return {}, raw


# ---------------------------------------------------------------------------
# Assessment (strong-signal acceptance)
# ---------------------------------------------------------------------------

def _assess(purpose: str = "basic") -> dict:
    """Evaluate current credential state. Returns a dict with `verdict`.

    purpose:
      - "basic"  : 只要求 logged_in + live + hr jobs list ok（Step 1 JD 提取够用）
      - "resume" : 额外要求 auth_state == "full"（含 __zp_stoken__，Step 2 简历下载需要）
    """
    resp, raw = _run_boss(["status", "--live"])
    if not raw:
        return {
            "verdict": "cdp_unreachable",
            "evidence": "boss status --live 无输出（CDP 未启动或 CLI 异常）",
            "next_action": "运行 open-login 拉起浏览器并打开登录页",
        }
    if not resp:
        return {
            "verdict": "cli_error",
            "evidence": f"status 输出无法解析为 JSON: {raw[:200]}",
            "next_action": "检查 boss CLI 安装后重试",
        }

    data = resp.get("data") or {}
    logged_in = bool(data.get("logged_in"))
    checks = {c.get("name"): c.get("status") for c in (data.get("checks") or [])}

    out = {
        "purpose": purpose,
        "logged_in": logged_in,
        "live": bool(data.get("live")),
        "user_name": data.get("user_name") or "",
        "auth_state": data.get("auth_state") or "missing",
        "wt2_present": checks.get("wt2_presence") == "ok",
        "stoken_present": checks.get("stoken_presence") == "ok",
    }

    if not logged_in:
        out["verdict"] = "not_logged_in"
        out["next_action"] = "运行 open-login-force 清旧 session 并打开登录页，用户扫码后运行 extract"
        return out

    # 强信号 3：真实数据探针（证明凭证实际可用，而非仅有本地文件）
    jobs_resp, _ = _run_boss(["hr", "jobs", "list"])
    jobs_ok = bool(jobs_resp.get("ok"))
    jdata = jobs_resp.get("data")
    if isinstance(jdata, list):
        jobs_count = len(jdata)
    elif isinstance(jdata, dict):
        jobs_count = len(jdata.get("result") or jdata.get("jobs") or [])
    else:
        jobs_count = 0
    out["jobs_probe_ok"] = jobs_ok
    out["jobs_count"] = jobs_count

    # 收集缺失项
    missing = []
    if not out["wt2_present"]:
        missing.append("wt2")
    if not out["stoken_present"]:
        missing.append("__zp_stoken__")
    if missing:
        out["missing"] = missing

    # 数据探针失败：basic/resume 都不算 ready
    if not jobs_ok:
        out["verdict"] = "degraded"
        out["missing"] = (out.get("missing") or []) + ["jobs_probe_failed"]
        out["next_action"] = "数据探针失败，运行 extract 或检查浏览器登录态"
        return out

    # basic 用途：logged_in + live + jobs_ok 即 ready，stoken 缺失仅警告
    if purpose == "basic":
        if out["logged_in"] and out["live"] and jobs_ok:
            out["verdict"] = "ready"
            out["next_action"] = "none"
            if not out["stoken_present"]:
                out["warning"] = (
                    "basic 用途就绪，但缺 __zp_stoken__。"
                    "简历下载前请运行: python boss_login_guard.py ensure-stoken"
                )
            return out
        out["verdict"] = "degraded"
        out["next_action"] = "运行 extract"
        return out

    # resume 用途：CLI 视角历史要求 auth_state=full + stoken 必须在场
    # 2026-07-28 改动：hr-auto 全流程用 patchright 直连 CDP 浏览器，
    #   API 调用走浏览器 wt2/zp_at/bst，不依赖 CLI 的 stoken。
    #   把"stoken 必须"从硬阻断降级为告警，避免误中断 CDP 直连流程。
    #   底层 patch_stoken.py / ensure-stoken 命令仍保留，用户可手动调用。
    if out["auth_state"] not in ("full", "complete"):
        # CLI 视角证书不完整 → verdict 仍按 CLI 视角判 degraded，
        # 但用户走 hr-auto 时由编排脚本根据 purpose 解读 warning。
        out["verdict"] = "degraded"
        out["warning"] = (
            "CLI 视角缺 stoken（auth_state=partial），但 hr-auto 走 CDP"
            "直连不受影响。需要 CLI 命令时手动跑 ensure-stoken。"
        )
        out["next_action"] = (
            "CLI 视角凭证不完整，但 CDP 直连路径不受影响。"
            "若坚持用 boss CLI 命令（非本工具包）请先 open-login。"
        )
        return out

    out["verdict"] = "ready"
    out["next_action"] = "none"
    if not out["stoken_present"]:
        out["warning"] = (
            "resume 用途（CLI 视角）缺 __zp_stoken__，但 hr-auto 流程走 CDP 浏览器"
            "直连，不依赖此 cookie。继续运行即可。需要 CLI 命令时请手动运行"
            " python boss_login_guard.py ensure-stoken"
        )
    return out


# ---------------------------------------------------------------------------
# CDP browser helpers
# ---------------------------------------------------------------------------

def _cdp_alive() -> bool:
    try:
        with urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _launch_browser() -> bool:
    """Launch Edge/Chrome with CDP flags and wait for the port. Returns success."""
    exe = next((p for p in BROWSER_CANDIDATES if Path(p).exists()), None)
    if not exe:
        return False
    profile = Path.home() / ".workbuddy" / "chrome-profiles" / "boss-cdp"
    subprocess.Popen(
        [
            exe,
            "--remote-debugging-port=9222",
            f"--user-data-dir={profile}",
            "--remote-allow-origins=*",
            LOGIN_URL,
        ],
        creationflags=_CREATE_FLAGS,
        close_fds=True,
    )
    for _ in range(20):
        if _cdp_alive():
            return True
        time.sleep(1)
    return False


def _open_login_tab() -> bool:
    """Open the BOSS login page in a new tab via CDP HTTP endpoint."""
    url = f"{CDP_URL}/json/new?{urllib.parse.urlencode({'url': LOGIN_URL})}"
    # Chrome >= 111 requires PUT; older versions accept GET.
    for method in ("PUT", "GET"):
        try:
            req = urllib.request.Request(url, method=method)
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status == 200
        except Exception:
            continue
    return False


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_check(purpose: str = "basic") -> int:
    a = _assess(purpose=purpose)
    verdict = a.get("verdict", "cli_error")
    out = {"ok": verdict == "ready", **a}
    if verdict == "ready":
        out["message"] = (
            f"登录态满足 {purpose} 用途（用户: {a.get('user_name') or 'unknown'}，"
            f"auth_state={a.get('auth_state')}，数据探针通过）。"
        )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return _VERDICT_EXIT.get(verdict, EXIT_UNREACHABLE)


def cmd_open_login_force() -> int:
    """强制重新登录：清 session.enc + 清浏览器 BOSS Cookie + 打开登录页。

    用于修复"CLI 假阳性登录"：上次 login --cdp 因旧 session.enc 残留而误判已登录，
    实际用户并未扫码。
    """
    actions = []

    # 1. 清 CLI 本地 session
    auth_dir = Path.home() / ".boss-agent" / "auth"
    session_file = auth_dir / "session.enc"
    if session_file.exists():
        try:
            session_file.unlink()
            actions.append(f"deleted {session_file}")
        except Exception as e:
            actions.append(f"failed to delete {session_file}: {e}")
    else:
        actions.append("session.enc not present (already clean)")

    # 2. 清浏览器侧 BOSS Cookie（用 CDP Network.clearBrowserCookies）
    if _cdp_alive():
        try:
            import websocket  # type: ignore
            with urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=3) as r:
                ws_url = json.loads(r.read().decode("utf-8"))["webSocketDebuggerUrl"]
            ws = websocket.create_connection(ws_url, timeout=5)
            ws.send(json.dumps({"id": 1, "method": "Network.clearBrowserCookies"}))
            ws.recv()
            ws.close()
            actions.append("browser cookies cleared via CDP")
        except ImportError:
            # websocket-client 未装：提示用户手动清
            actions.append("websocket-client not installed, browser cookies NOT cleared; pip install websocket-client")
        except Exception as e:
            actions.append(f"browser cookie clear failed: {e}")
    else:
        actions.append("CDP not alive, browser cookies NOT cleared")

    # 3. 走标准 open-login 流程
    launched = False
    if not _cdp_alive():
        launched = True
        if not _launch_browser():
            print(json.dumps({
                "ok": False,
                "verdict": "cdp_unreachable",
                "actions": actions,
                "error": "CDP 9222 不可用，且未能自动启动 Edge/Chrome",
            }, ensure_ascii=False, indent=2))
            return EXIT_UNREACHABLE
        time.sleep(2)

    opened = _open_login_tab()
    out = {
        "ok": opened,
        "cdp_alive": True,
        "browser_launched_by_guard": launched,
        "login_url": LOGIN_URL,
        "actions": actions,
    }
    if opened:
        out["message_for_user"] = (
            "已强制清理旧 session 与浏览器 Cookie，BOSS 登录页已打开。"
            "请用手机扫码登录（这次一定会要求扫码）。"
        )
        out["next_action"] = "用户确认已扫码登录后，运行: python boss_login_guard.py extract"
    else:
        out["error"] = "浏览器已运行但打开登录页失败"
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return EXIT_READY if opened else EXIT_UNREACHABLE


def cmd_ensure_stoken() -> int:
    """无扫码修复：通过 patch_stoken.py 从浏览器直接提取 __zp_stoken__ 注入 session.enc。

    场景：浏览器里实际已有 BOSS 登录态，但 session.enc 缺 __zp_stoken__。
    绕过 CLI extract 的缺陷（只从当前激活标签页所在域提取 Cookie）。
    """
    if not _cdp_alive():
        print(json.dumps({
            "ok": False,
            "verdict": "cdp_unreachable",
            "error": "CDP 不可用，无法触发 stoken",
        }, ensure_ascii=False, indent=2))
        return EXIT_UNREACHABLE

    # 调用同目录下的 patch_stoken.py
    patch_script = Path(__file__).parent / "patch_stoken.py"
    if not patch_script.exists():
        print(json.dumps({
            "ok": False,
            "verdict": "cli_error",
            "error": f"patch_stoken.py 未找到: {patch_script}",
        }, ensure_ascii=False, indent=2))
        return EXIT_UNREACHABLE

    r = subprocess.run(
        [sys.executable, str(patch_script)],
        capture_output=True,
        timeout=60,
    )
    patch_out = r.stdout.decode("utf-8", "ignore")
    patch_ok = r.returncode == 0

    # 复检
    final = _assess(purpose="resume")
    out = {
        "ok": final.get("verdict") == "ready",
        "patch_ok": patch_ok,
        "patch_output": patch_out.strip()[:500],
        **{k: v for k, v in final.items() if k != "verdict"},
        "verdict": final.get("verdict"),
    }
    if out["ok"]:
        out["message"] = "stoken 已通过 patch_stoken.py 注入，resume 用途就绪。"
    else:
        out["message"] = (
            "patch_stoken.py 执行后仍未就绪。"
            "请运行 open-login-force 让用户重新扫码。"
        )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return _VERDICT_EXIT.get(out["verdict"], EXIT_UNREACHABLE)


def cmd_extract_quiet() -> int:
    """静默版 extract：不打印，供 ensure-stoken 内部调用。"""
    for _ in range(2):
        _run_boss(["login", "--cdp", "--timeout", "30"], timeout=90)
        final = _assess(purpose="resume")
        if final.get("verdict") == "ready":
            return EXIT_READY
        if final.get("verdict") in ("not_logged_in", "cdp_unreachable", "cli_error"):
            break
        time.sleep(2)
    return _VERDICT_EXIT.get(final.get("verdict", "cli_error"), EXIT_UNREACHABLE)


def cmd_open_login() -> int:
    launched = False
    if not _cdp_alive():
        launched = True
        if not _launch_browser():
            print(json.dumps({
                "ok": False,
                "verdict": "cdp_unreachable",
                "error": "CDP 9222 不可用，且未能自动启动 Edge/Chrome",
                "next_action": "请用户手动以 --remote-debugging-port=9222 启动浏览器后重试",
            }, ensure_ascii=False, indent=2))
            return EXIT_UNREACHABLE
        time.sleep(2)

    opened = _open_login_tab()
    out = {
        "ok": opened,
        "cdp_alive": True,
        "browser_launched_by_guard": launched,
        "login_url": LOGIN_URL,
    }
    if opened:
        out["message_for_user"] = (
            "BOSS 直聘登录页已在浏览器中打开，请用手机扫码登录。"
            "登录完成后告诉我，我会提取登录凭证并继续。"
        )
        out["next_action"] = "用户确认已扫码登录后，运行: python boss_login_guard.py extract"
    else:
        out["error"] = "浏览器已运行但打开登录页失败"
        out["next_action"] = "请用户在浏览器中手动打开 BOSS 直聘并扫码，然后运行 extract"
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return EXIT_READY if opened else EXIT_UNREACHABLE


def cmd_extract(purpose: str = "resume") -> int:
    attempts = []
    final: dict = {}
    for i in range(1, 3):
        login_resp, _ = _run_boss(["login", "--cdp", "--timeout", "30"], timeout=90)
        attempts.append({"attempt": i, "login_ok": bool(login_resp.get("ok"))})
        final = _assess(purpose=purpose)
        verdict = final.get("verdict", "cli_error")
        if verdict == "ready":
            break
        if verdict in ("not_logged_in", "cdp_unreachable", "cli_error"):
            break  # 重试无意义：需要用户扫码 / 先起浏览器 / 修 CLI
        time.sleep(2)  # degraded → 再试一次提取

    verdict = final.get("verdict", "cli_error")
    out = {
        "ok": verdict == "ready",
        "verdict": verdict,
        "attempts": attempts,
        **{k: v for k, v in final.items() if k != "verdict"},
    }
    if verdict == "ready":
        out["message"] = f"凭证提取成功且验收通过（purpose={purpose}）。"
    elif verdict == "degraded":
        out["message"] = (
            "重提取后仍为半登录（缺失: " + ",".join(final.get("missing") or ["unknown"]) + "）。"
            "建议先运行 ensure-stoken（无扫码修复）；仍失败再 open-login-force。"
        )
    elif verdict == "not_logged_in":
        out["message"] = "浏览器尚未完成登录。请运行 open-login-force 打开登录页让用户扫码。"
    else:
        out["message"] = "CDP 不可用或 CLI 异常。请运行 open-login-force 拉起浏览器后重试。"
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return _VERDICT_EXIT.get(verdict, EXIT_UNREACHABLE)


def main() -> None:
    argv = sys.argv[1:]
    if not argv:
        sys.stderr.write(__doc__ or "")
        sys.exit(64)

    # 解析 --purpose
    purpose = "basic"
    if "--purpose" in argv:
        i = argv.index("--purpose")
        if i + 1 < len(argv):
            purpose = argv[i + 1]
            del argv[i:i + 2]
        else:
            sys.stderr.write("--purpose 需要参数 basic|resume\n")
            sys.exit(64)

    if not argv:
        sys.stderr.write(__doc__ or "")
        sys.exit(64)

    cmd = argv[0]
    if cmd == "check":
        sys.exit(cmd_check(purpose=purpose))
    if cmd == "open-login":
        sys.exit(cmd_open_login())
    if cmd == "open-login-force":
        sys.exit(cmd_open_login_force())
    if cmd == "ensure-stoken":
        sys.exit(cmd_ensure_stoken())
    if cmd == "extract":
        sys.exit(cmd_extract(purpose=purpose))

    sys.stderr.write(__doc__ or "")
    sys.exit(64)


if __name__ == "__main__":
    main()
