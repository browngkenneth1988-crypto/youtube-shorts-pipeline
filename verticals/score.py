"""Topic scoring gate.

A niche profile can declare a `scoring:` block. When it does, no script is written
for that niche until the topic clears the threshold. The rubric, threshold, pillars,
and calibration examples all live in the YAML — this module only runs them.

Niches with no `scoring:` block are ungated and behave exactly as before.
"""

import json
import re

from .llm import call_llm
from .log import log
from .niche import load_niche


class TopicRejected(Exception):
    """Raised when a topic scores below its niche threshold."""

    def __init__(self, result: dict):
        self.result = result
        super().__init__(result.get("summary", "Topic rejected"))


def scoring_enabled(profile: dict) -> bool:
    cfg = profile.get("scoring", {}) or {}
    return bool(cfg.get("enabled"))


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of an LLM response."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start : end + 1]
    return json.loads(text)


def _build_prompt(topic: str, cfg: dict, profile: dict) -> str:
    categories = cfg.get("categories", [])
    threshold = cfg.get("threshold", 40)
    max_total = cfg.get("max_total", sum(c.get("max", 10) for c in categories) or 50)

    lines = [
        f"You are the topic gate for the channel \"{profile.get('channel', {}).get('name', profile.get('display_name', 'this channel'))}\".",
        f"Promise: {profile.get('channel', {}).get('promise', '')}".rstrip(),
        f"Audience: {profile.get('channel', {}).get('audience', '')}".rstrip(),
        "",
        f"Score this proposed topic: \"{topic}\"",
        "",
        "Score each category from 1 to 10. Be harsh. A 7 means genuinely good, not adequate.",
        "Most proposed topics should fail. The cost of approving a weak topic is a wasted",
        "production week; the cost of rejecting a decent one is one more scoring call.",
        "",
        "CATEGORIES:",
    ]
    for c in categories:
        lines.append(f"  {c['id']} (max {c.get('max', 10)}): {c.get('question', '')}")

    pillars = cfg.get("pillars", [])
    if pillars:
        lines += ["", "CONTENT PILLARS — the topic must clearly fit at least one:"]
        lines += [f"  - {p}" for p in pillars]
        lines.append("Cross-pillar fit (two or more) is a strength; name every pillar it fits.")

    bonuses = cfg.get("bonuses", [])
    if bonuses:
        lines += ["", "STRENGTHENING FACTORS:"] + [f"  - {b}" for b in bonuses]

    hard = cfg.get("hard_rejects", [])
    if hard:
        lines += [
            "",
            "AUTOMATIC REJECTION regardless of score — set total to 0 if the topic requires any of:",
        ] + [f"  - {h}" for h in hard]

    approve = cfg.get("calibration_approve", [])
    if approve:
        lines += ["", "CALIBRATION — these are approved-quality topics:"] + [f"  - {a}" for a in approve]

    reject = cfg.get("calibration_reject", [])
    if reject:
        lines += ["", "CALIBRATION — these fail, with the reframe that saves them:"]
        for r in reject:
            lines.append(f"  - WEAK: \"{r.get('weak', '')}\"  ->  STRONG: \"{r.get('reframe', '')}\"")
        lines.append("Pattern: lead with the curiosity hook, hide the academic framing inside the video.")

    lines += [
        "",
        f"Threshold: {threshold} of {max_total}. Below that is a REJECT.",
        "",
        "Return ONLY this JSON, no prose:",
        "{",
        '  "scores": {' + ", ".join(f'"{c["id"]}": 0' for c in categories) + "},",
        '  "total": 0,',
        '  "verdict": "APPROVE" or "REJECT",',
        '  "pillars": ["pillar names it fits"],',
        '  "summary": "one sentence on why it scored this way",',
        '  "titles": ["3 working titles, only if APPROVE"],',
        '  "reframes": ["1-2 stronger angles that would clear the threshold, only if REJECT"]',
        "}",
    ]
    return "\n".join(lines)


def score_topic(topic: str, niche: str = "general", provider: str | None = None) -> dict | None:
    """Score a topic against its niche rubric.

    Returns None when the niche has no scoring block (ungated niche).
    Returns a result dict otherwise. Never raises on LLM failure — a scoring
    outage must not silently approve, so a failed call returns verdict ERROR.
    """
    profile = load_niche(niche)
    cfg = profile.get("scoring", {}) or {}
    if not cfg.get("enabled"):
        return None

    threshold = cfg.get("threshold", 40)
    max_total = cfg.get("max_total", 50)

    try:
        raw = ""
        raw = call_llm(_build_prompt(topic, cfg, profile), provider=provider,
                       max_tokens=2048, json_mode=True)
        result = _extract_json(raw)
    except Exception as e:
        # Dump whatever the model actually said, so a parse failure is
        # diagnosable instead of just a stack trace.
        try:
            from .config import LOGS_DIR
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            (LOGS_DIR / "last_llm_failure.txt").write_text(
                f"topic: {topic}\nerror: {e}\n\n--- raw response ---\n{raw}",
                encoding="utf-8")
        except Exception:
            pass
        log(f"Topic scoring failed: {e}")
        return {
            "topic": topic,
            "niche": niche,
            "verdict": "ERROR",
            "total": 0,
            "threshold": threshold,
            "max_total": max_total,
            "scores": {},
            "summary": f"Scoring call failed: {e}",
            "pillars": [],
            "titles": [],
            "reframes": [],
        }

    scores = result.get("scores", {}) or {}
    total = result.get("total")
    if not isinstance(total, (int, float)):
        total = sum(v for v in scores.values() if isinstance(v, (int, float)))
    total = int(total)

    result.update(
        {
            "topic": topic,
            "niche": niche,
            "total": total,
            "threshold": threshold,
            "max_total": max_total,
            "verdict": "APPROVE" if total >= threshold else "REJECT",
        }
    )
    return result


def format_result(result: dict) -> str:
    """Human-readable scorecard for the terminal."""
    lines = ["", f"  Topic: {result.get('topic', '')}", ""]
    for k, v in (result.get("scores") or {}).items():
        lines.append(f"    {k:<16} {v:>2}/10")
    lines.append("")
    lines.append(f"    TOTAL            {result.get('total', 0):>2}/{result.get('max_total', 50)}   (threshold {result.get('threshold', 40)})")
    lines.append(f"    VERDICT          {result.get('verdict', '?')}")
    pillars = result.get("pillars") or []
    if pillars:
        lines.append(f"    PILLARS          {', '.join(pillars)}")
    if result.get("summary"):
        lines += ["", f"    {result['summary']}"]
    if result.get("verdict") == "APPROVE" and result.get("titles"):
        lines += ["", "    Working titles:"] + [f"      - {t}" for t in result["titles"]]
    if result.get("verdict") == "REJECT" and result.get("reframes"):
        lines += ["", "    Stronger angles:"] + [f"      - {r}" for r in result["reframes"]]
    lines.append("")
    return "\n".join(lines)


def gate_topic(topic: str, niche: str, provider: str | None = None, force: bool = False) -> dict | None:
    """Score and enforce. Raises TopicRejected unless force=True or the niche is ungated."""
    result = score_topic(topic, niche=niche, provider=provider)
    if result is None:
        return None

    print(format_result(result))

    if result["verdict"] == "APPROVE":
        return result

    if force:
        log(f"Topic scored {result['total']}/{result['max_total']} — overridden with --force")
        return result

    raise TopicRejected(result)
