#!/usr/bin/env python3
"""Find an auth path that works for this Gemini key.

Google is migrating API keys from AIza to AQ. (AIza deprecated Sept 2026) and
the new keys behave differently across endpoints. This tries every combination
the pipeline could use and reports which ones actually work, so the fix is
measured instead of guessed.

    py -3 scripts/gemini_probe.py
"""

import os
import sys

KEY = os.environ.get("GEMINI_API_KEY", "")
BASE = "https://generativelanguage.googleapis.com/v1beta"
MODEL = "gemini-2.5-flash"
BODY = {"contents": [{"parts": [{"text": "Reply with the single word: pong"}]}],
        "generationConfig": {"maxOutputTokens": 10}}

results = []


def show(name, ok, detail):
    results.append((name, ok, detail))
    print(f"[{'  OK  ' if ok else ' FAIL '}] {name}")
    if detail:
        print(f"          {detail}")


def main():
    if not KEY:
        print("GEMINI_API_KEY is not set. Run this from healthcheck.bat or fix_deps.bat.")
        sys.exit(1)
    print(f"\nKey prefix: {KEY[:6]}...  length: {len(KEY)}")
    print("=" * 62)

    import requests

    def try_req(name, method, url, **kw):
        try:
            r = requests.request(method, url, timeout=45, **kw)
            if r.status_code == 200:
                show(name, True, "HTTP 200")
                return True
            body = r.text[:150].replace("\n", " ")
            show(name, False, f"HTTP {r.status_code} — {body}")
        except Exception as e:
            show(name, False, f"{type(e).__name__}: {str(e)[:100]}")
        return False

    hdr = {"Content-Type": "application/json", "x-goog-api-key": KEY}

    try_req("generateContent + x-goog-api-key  (what the pipeline uses now)",
            "POST", f"{BASE}/models/{MODEL}:generateContent", json=BODY, headers=hdr)
    try_req("generateContent + ?key= query param",
            "POST", f"{BASE}/models/{MODEL}:generateContent?key={KEY}", json=BODY,
            headers={"Content-Type": "application/json"})
    try_req("models.list + x-goog-api-key",
            "GET", f"{BASE}/models", headers={"x-goog-api-key": KEY})
    try_req("models.list + ?key=",
            "GET", f"{BASE}/models?key={KEY}")
    try_req("OpenAI-compat + Bearer",
            "POST", f"{BASE}/openai/chat/completions",
            json={"model": MODEL, "messages": [{"role": "user", "content": "pong"}],
                  "max_tokens": 10},
            headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})

    # Official SDK — handles the new key format internally, per Google's guidance.
    try:
        from google import genai
        try:
            c = genai.Client(api_key=KEY)
            resp = c.models.generate_content(model=MODEL, contents="Reply with: pong")
            show("google-genai SDK", bool(getattr(resp, "text", "")), "SDK call returned text")
        except Exception as e:
            show("google-genai SDK", False, f"{type(e).__name__}: {str(e)[:120]}")
    except ImportError:
        show("google-genai SDK", False, "not installed — py -3 -m pip install google-genai")

    print("=" * 62)
    winners = [n for n, ok, _ in results if ok]
    if winners:
        print("\n  WORKING PATHS:")
        for w in winners:
            print(f"    - {w}")
        print("\n  Paste this list back and I'll point the pipeline at one of them.\n")
    else:
        print("\n  Nothing worked. This key cannot reach Gemini at all.")
        print("  Most likely an account-level restriction on the new AQ. key type.")
        print("  Paste the FAIL lines back — the error codes tell us which.\n")


if __name__ == "__main__":
    main()
