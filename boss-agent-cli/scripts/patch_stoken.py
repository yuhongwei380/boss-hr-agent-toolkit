#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
临时补丁：从 CDP 浏览器提取 __zp_stoken__，注入到 CLI 的 session.enc。

背景（上游 CLI 缺陷）：
  `boss login --cdp` 只从当前激活标签页所在域提取 Cookie。
  如果浏览器停在 login.zhipin.com 或 _security_check 验证页，
  www.zhipin.com 域下的 __zp_stoken__ 就会被漏掉，导致 session.enc 缺 stoken。

本脚本：
  1. 通过 patchright 连接 CDP 浏览器
  2. 访问 https://www.zhipin.com/web/geek/job 触发前端 JS 写入 __zp_stoken__
  3. 读取浏览器中所有 BOSS 域 Cookie
  4. 用 boss_agent_cli.auth.token_store.TokenStore 把 __zp_stoken__ 合并进 session.enc

退出码：
  0  成功（stoken 已注入或本来就有）
  1  CDP 不可达
  2  浏览器里没有 __zp_stoken__（用户可能未登录）
  3  session.enc 不存在（需先 boss login --cdp）
  4  其他异常
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

CDP_URL = "http://localhost:9222"
AUTH_DIR = Path.home() / ".boss-agent" / "auth"


async def fetch_stoken_from_browser() -> tuple[str | None, dict[str, str]]:
    """从浏览器提取 __zp_stoken__ 与所有 BOSS Cookie。

    先尝试直接从现有 Cookie 读，没有再 goto 触发；goto 后每 1.5 秒轮询，
    最多等 12 秒，避免时序问题导致偶发拿不到。
    """
    from patchright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        ctx = browser.contexts[0]

        # 第 1 步：直接读现有 Cookie（可能已经有）
        cookies = await ctx.cookies()
        cookie_map = {c["name"]: c["value"] for c in cookies}
        stoken = cookie_map.get("__zp_stoken__")
        if stoken:
            return stoken, cookie_map

        # 第 2 步：goto 触发 stoken 写入，并轮询
        page = await ctx.new_page()
        try:
            await page.goto(
                "https://www.zhipin.com/web/geek/job",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            # 轮询最多 12 秒，每 1.5 秒查一次
            for _ in range(8):
                await page.wait_for_timeout(1500)
                cookies = await ctx.cookies()
                cookie_map = {c["name"]: c["value"] for c in cookies}
                stoken = cookie_map.get("__zp_stoken__")
                if stoken:
                    return stoken, cookie_map
        finally:
            await page.close()

    return None, cookie_map


def patch_session(stoken: str, cookie_map: dict[str, str]) -> dict:
    """把 stoken 合并进 session.enc。"""
    from boss_agent_cli.auth.token_store import TokenStore

    ts = TokenStore(AUTH_DIR)
    data = ts.load()
    if data is None:
        return {"ok": False, "error": "session.enc 不存在或解密失败"}

    # 回填 stoken 字段（顶层）
    data["stoken"] = stoken

    # 同时合并进 cookies dict（防止其他地方从 cookies 读取）
    if "cookies" not in data or not isinstance(data["cookies"], dict):
        data["cookies"] = {}
    data["cookies"]["__zp_stoken__"] = stoken

    # 顺手补齐其他浏览器里有但 session.enc 缺失的 BOSS cookie
    added = []
    for name, value in cookie_map.items():
        if name not in data["cookies"]:
            data["cookies"][name] = value
            added.append(name)

    ts.save(data)
    return {
        "ok": True,
        "stoken_len": len(stoken),
        "cookies_total": len(data["cookies"]),
        "cookies_added": added,
    }


def main() -> int:
    try:
        stoken, cookie_map = asyncio.run(fetch_stoken_from_browser())
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": f"CDP 连接或浏览器操作失败: {e}",
            "hint": "确认 Edge 以 --remote-debugging-port=9222 运行",
        }, ensure_ascii=False, indent=2))
        return 1

    if not stoken:
        print(json.dumps({
            "ok": False,
            "error": "浏览器中未找到 __zp_stoken__",
            "hint": "确认你已在浏览器中登录 BOSS 直聘，并且能访问 www.zhipin.com",
            "cookies_seen": sorted(cookie_map.keys()),
        }, ensure_ascii=False, indent=2))
        return 2

    if not (AUTH_DIR / "session.enc").exists():
        print(json.dumps({
            "ok": False,
            "error": "session.enc 不存在",
            "hint": "先运行 boss login --cdp 建立基础 session",
        }, ensure_ascii=False, indent=2))
        return 3

    result = patch_session(stoken, cookie_map)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 4


if __name__ == "__main__":
    sys.exit(main())
