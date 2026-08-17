#!/usr/bin/env python3
"""Curious Classroom daily queue builder.

Discovers topics, scores every one against the 50-point rubric, and banks the
approved ones with a script. Builds NOTHING: no images, no voice, no upload.

Why: Phase 1 canon is one long-form per week and no Shorts until video 8 is
live. The bottleneck on this channel is a scored topic queue, not production
capacity. This fills that queue overnight so Kenneth picks from a ranked list
instead of starting from a blank page.

Cost per run: LLM calls only. No Leonardo image credits, no TTS, no upload.

    py -3 scripts/curious_daily.py [--limit 12] [--no-draft]
"""

import argparse
import csv
import datetime
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from verticals import notify
from verticals.config import DRAFTS_DIR, LOGS_DIR, SKILL_DIR
from verticals.log import log, set_verbose
from verticals.score import score_topic

NICHE = "curious_classroom"
QUEUE = SKILL_DIR / "curious_queue.csv"
FIELDS = ["first_seen", "topic", "total", "verdict", "pillars", "summary",
          "titles", "source", "drafted", "draft_path"]


def load_queue() -> list[dict]:
    if not QUEUE.exists():
        return []
    with open(QUEUE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_queue(rows: list[dict]):
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    with open(QUEUE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def norm(s: str) -> str:
    return " ".join(str(s).lower().split())


def discover(limit: int) -> list:
    from verticals.topics import TopicEngine
    try:
        return TopicEngine(niche=NICHE).discover(limit=limit)
    except Exception as e:
        log(f"Topic discovery failed: {e}")
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=12, help="Topics to pull and score")
    ap.add_argument("--no-draft", action="store_true", help="Score only, skip the script")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()
    set_verbose(args.verbose)

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    pruned = notify.prune_logs()
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'=' * 60}\n  Curious Classroom queue — {stamp}\n{'=' * 60}")
    if pruned:
        print(f"  Pruned {pruned} log files older than 45 days")

    rows = load_queue()
    seen = {norm(r["topic"]) for r in rows}
    print(f"  Queue holds {len(rows)} scored topics "
          f"({sum(1 for r in rows if r.get('verdict') == 'APPROVE')} approved)")

    candidates = discover(args.limit)
    fresh = [c for c in candidates if norm(getattr(c, 'title', c)) not in seen]
    print(f"  Discovered {len(candidates)}, {len(fresh)} not scored before")

    # No early return here. An approved topic can be sitting in the queue
    # without a script (a draft failed, or it was scored on a previous run),
    # and it still deserves one even on a day with nothing new to score.
    if not fresh:
        print("  Nothing new to score today.")

    today = datetime.date.today().isoformat()
    added = 0
    score_errors = 0
    for c in fresh:
        title = getattr(c, "title", str(c))
        source = getattr(c, "source", "discovery")
        r = score_topic(title, niche=NICHE)
        if r is None or r.get("verdict") == "ERROR":
            score_errors += 1
            log(f"Skipped (scoring error): {title}")
            continue
        rows.append({
            "first_seen": today,
            "topic": title,
            "total": r.get("total", 0),
            "verdict": r.get("verdict", "?"),
            "pillars": "; ".join(r.get("pillars") or []),
            "summary": r.get("summary", ""),
            "titles": " | ".join(r.get("titles") or r.get("reframes") or []),
            "source": source,
            "drafted": "no",
            "draft_path": "",
        })
        added += 1
        mark = "APPROVE" if r["verdict"] == "APPROVE" else "reject "
        print(f"    [{mark}] {r.get('total', 0):>2}/50  {title[:60]}")

    # Best approved topic that has never been drafted.
    pending = [r for r in rows if r.get("verdict") == "APPROVE" and r.get("drafted") != "yes"]
    pending.sort(key=lambda r: int(r.get("total") or 0), reverse=True)

    draft_error = ""
    if not pending:
        print("  No approved topic is waiting for a script.")
    if pending and not args.no_draft:
        best = pending[0]
        print(f"\n  Drafting the top pending topic ({best['total']}/50):\n    {best['topic']}")
        try:
            import time

            from verticals.draft import generate_draft
            from verticals.state import PipelineState
            DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
            job_id = str(int(time.time()))
            # generate_draft retries an off-topic result itself and raises
            # DraftDriftError only when every attempt drifted. The except below
            # then leaves the topic queued rather than banking a wrong script.
            d = generate_draft(best["topic"], "", niche=NICHE, platform="shorts")
            d["job_id"] = job_id
            d["topic_score"] = {k: best[k] for k in ("total", "verdict", "pillars", "summary")}
            out = DRAFTS_DIR / f"{job_id}.json"
            st = PipelineState(d)
            st.complete_stage("research")
            st.complete_stage("draft")
            st.save(out)
            best["drafted"] = "yes"
            best["draft_path"] = str(out)
            print(f"  Script saved: {out}")
        except Exception as e:
            draft_error = f"{type(e).__name__}: {str(e)[:200]}"
            print(f"  Draft failed (topic still queued): {e}")

    save_queue(rows)

    approved = [r for r in rows if r.get("verdict") == "APPROVE"]
    ready = [r for r in approved if r.get("drafted") == "yes"]
    print(f"\n{'=' * 60}")
    print(f"  Scored today      : {added}")
    print(f"  Approved in queue : {len(approved)}")
    print(f"  With a script     : {len(ready)}")
    print(f"  Queue file        : {QUEUE}")
    print(f"{'=' * 60}")
    print("\n  Nothing was built or uploaded. Phase 1 is one long-form per week —")
    print("  pick a topic from the queue when you're ready to make it.\n")

    # A run that scored nothing and drafted nothing is a failed run, even though
    # every individual step swallowed its exception. Say so out loud and exit
    # non-zero so Task Scheduler stops reporting these mornings as successes.
    problems = []
    if fresh and added == 0:
        problems.append(f"scored 0 of {len(fresh)} new topics ({score_errors} errors)")
    if draft_error:
        problems.append(f"draft failed — {draft_error}")

    if problems:
        detail = "; ".join(problems)
        print(f"  RUN DEGRADED: {detail}\n")
        notify.alert("curious_daily", detail)
        return 1

    notify.record_status("curious_daily", ok=True,
                         detail=f"scored {added}, {len(ready)} scripts banked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
