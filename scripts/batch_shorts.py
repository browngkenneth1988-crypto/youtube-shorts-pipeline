#!/usr/bin/env python3
"""Produce and upload a batch of shorts, one topic per run of the pipeline.

    py -3 scripts/batch_shorts.py --niche curious_classroom "topic one" "topic two"
    py -3 scripts/batch_shorts.py --niche curious_classroom --topics-file topics.txt

Each topic runs draft -> produce -> upload independently, so one bad topic
never costs the whole batch. Three outcomes are distinguished, because they
need different responses:

  QUOTA      the LLM is out of daily requests. Stops the batch immediately --
             every further topic would fail the same way and burn retries.
  REJECTED   the niche's score gate declined the topic. Skips to the next one;
             this is the gate working, not a failure.
  ERROR      anything else. Records it and continues.

Uploads inherit the niche's privacy setting (private for curious_classroom),
so nothing goes public without a deliberate step elsewhere.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DRAFTS = Path.home() / ".verticals" / "drafts"

QUOTA_MARKERS = ("quota", "429", "exhausted", "rate limit")
REJECT_MARKERS = ("topicrejected", "verdict          reject")


def run_stage(args, timeout=1800):
    p = subprocess.run(
        [sys.executable, "-m", "verticals", *args],
        cwd=REPO, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def classify(out: str) -> str:
    low = out.lower()
    if any(m in low for m in QUOTA_MARKERS):
        return "QUOTA"
    if any(m in low for m in REJECT_MARKERS):
        return "REJECTED"
    return "ERROR"


def newest_draft(before: set):
    fresh = set(DRAFTS.glob("*.json")) - before
    return max(fresh, key=lambda p: p.stat().st_mtime) if fresh else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("topics", nargs="*")
    ap.add_argument("--niche", default="general")
    ap.add_argument("--topics-file")
    ap.add_argument("--dry-run", action="store_true", help="draft only, no produce/upload")
    a = ap.parse_args()

    topics = list(a.topics)
    if a.topics_file:
        topics += [ln.strip() for ln in Path(a.topics_file).read_text(encoding="utf-8").splitlines()
                   if ln.strip() and not ln.startswith("#")]
    if not topics:
        ap.error("no topics given")

    results = []
    for i, topic in enumerate(topics, 1):
        print(f"\n{'=' * 62}\n[{i}/{len(topics)}] {topic}\n{'=' * 62}", flush=True)
        row = {"topic": topic, "stage": "draft", "url": None, "note": None, "title": None}

        before = set(DRAFTS.glob("*.json"))
        rc, out = run_stage(["draft", "--topic", topic, "--niche", a.niche])
        draft = newest_draft(before)
        if rc != 0 or draft is None:
            kind = classify(out)
            row["note"] = kind
            results.append(row)
            print(f"  {kind}", flush=True)
            if kind == "QUOTA":
                print("  stopping: every remaining topic would fail identically", flush=True)
                break
            continue

        score = next((ln.strip() for ln in out.splitlines() if "TOTAL" in ln and "/" in ln), "")
        print(f"  drafted {draft.name}  {score}", flush=True)
        if a.dry_run:
            row.update(stage="drafted", note="dry run")
            results.append(row)
            continue

        rc, out = run_stage(["produce", "--draft", str(draft)])
        if rc != 0:
            row.update(stage="produce", note=classify(out))
            results.append(row)
            print(f"  produce failed: {row['note']}", flush=True)
            continue
        print("  produced", flush=True)

        rc, out = run_stage(["upload", "--draft", str(draft)])
        url = next((ln.split("Live:")[-1].strip() for ln in out.splitlines() if "Live:" in ln), None)
        if rc != 0 or not url:
            row.update(stage="upload", note=classify(out))
            results.append(row)
            print(f"  upload failed: {row['note']}", flush=True)
            continue

        row.update(stage="done", url=url,
                   title=json.loads(draft.read_text(encoding="utf-8")).get("youtube_title"))
        results.append(row)
        print(f"  UPLOADED {url}", flush=True)
        time.sleep(2)

    done = [r for r in results if r["stage"] == "done"]
    print(f"\n{'=' * 62}\nSUMMARY  {len(done)}/{len(topics)} uploaded\n{'=' * 62}")
    for r in results:
        if r["stage"] == "done":
            print(f"  OK    {r['url']}  {r['title']}")
        else:
            print(f"  {r['note'] or 'FAIL':6} [{r['stage']}] {r['topic']}")
    for r in results:
        if r["note"] == "QUOTA":
            print("\n  Quota stopped this batch. Either wait for the daily reset or")
            print("  configure a second LLM provider — llm.py already fails over,")
            print("  it just has nothing to fail over to.")
            break
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
