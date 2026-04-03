#!/usr/bin/env python3
"""Daily YouTube Shorts automation for Otto the Shih-Poo.

Runs once per day via cron. Picks a topic from the daily content calendar
(or auto-discovers a trending topic), generates the full video, and uploads.

Usage:
    # Run with content calendar topic (recommended for daily automation)
    python scripts/daily_shorts.py

    # Force trending topic discovery instead of calendar
    python scripts/daily_shorts.py --discover

    # Dry run (draft only, no produce/upload)
    python scripts/daily_shorts.py --dry-run

    # Override voice provider
    python scripts/daily_shorts.py --voice elevenlabs

Cron example (daily at 6 AM):
    0 6 * * * cd /path/to/youtube-shorts-pipeline && python scripts/daily_shorts.py >> ~/.verticals/logs/cron.log 2>&1
"""

import argparse
import datetime
import json
import random
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from verticals.config import DRAFTS_DIR, MEDIA_DIR, LOGS_DIR, CONFIG_FILE
from verticals.log import log, set_verbose
from verticals.niche import load_niche


def get_todays_topic(niche_name: str = "pets") -> tuple[str, str]:
    """Pick today's topic from the content calendar.

    Returns (topic, theme) based on the day of the week.
    Uses a hash of the date to rotate through topics so you don't
    repeat the same one every Monday, etc.
    """
    profile = load_niche(niche_name)
    daily_themes = profile.get("daily_themes", {})

    day_name = datetime.datetime.now().strftime("%A").lower()
    day_config = daily_themes.get(day_name, {})

    if not day_config:
        # Fallback: generic Otto topic
        return "A day in the life of Otto the Shih-Poo", "General"

    theme = day_config.get("theme", day_name.title())
    topics = day_config.get("topics", [])

    if not topics:
        return f"Otto's {theme} adventure", theme

    # Rotate through topics based on week number to avoid repeats
    week_num = datetime.datetime.now().isocalendar()[1]
    topic_index = week_num % len(topics)
    return topics[topic_index], theme


def discover_trending_topic(niche_name: str = "pets") -> str:
    """Use the topic engine to find a trending pet topic."""
    from verticals.topics import TopicEngine

    engine = TopicEngine(niche=niche_name)
    candidates = engine.discover(limit=10)

    if not candidates:
        topic, _ = get_todays_topic(niche_name)
        log("No trending topics found, falling back to content calendar")
        return topic

    # Auto-pick the best one
    try:
        return engine.auto_pick(candidates)
    except Exception:
        return candidates[0].title


def run_daily_pipeline(
    niche: str = "pets",
    discover: bool = False,
    dry_run: bool = False,
    voice: str | None = None,
    lang: str = "en",
    provider: str | None = None,
):
    """Run the complete daily pipeline: topic -> draft -> produce -> upload."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log(f"\n{'='*60}")
    log(f"Daily Shorts Pipeline — {timestamp}")
    log(f"{'='*60}")

    # Step 1: Pick topic
    if discover:
        topic = discover_trending_topic(niche)
        theme = "Trending"
        log(f"Trending topic: {topic}")
    else:
        topic, theme = get_todays_topic(niche)
        log(f"Calendar topic [{theme}]: {topic}")

    # Step 2: Draft
    from verticals.draft import generate_draft
    from verticals.state import PipelineState

    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    job_id = str(int(time.time()))

    # Build channel context from niche profile
    profile = load_niche(niche)
    character = profile.get("character", {})
    channel = profile.get("channel", {})
    channel_name = channel.get("name", "OttoMissClub")
    website = channel.get("website", "www.brownstoryworld.com")

    channel_context = (
        f"{channel_name} — a children's bedtime and comfort channel. Theme: {theme}. "
        f"{character.get('name', 'Otto')} is a {character.get('breed', 'small curly black Shih-Poo')}. "
        f"His favorite toy is {character.get('sidekick', 'Kobi, an orange plush dragon')}. "
        f"Every video includes a gentle inspirational quote for children. "
        f"Tone is soothing, warm, and safe for young kids. "
        f"Lullaby-style background music. "
        f"Website: {website}"
    )

    log(f"Drafting script for: {topic}")
    draft = generate_draft(
        topic,
        channel_context=channel_context,
        niche=niche,
        platform="shorts",
        provider=provider,
    )
    draft["job_id"] = job_id
    draft["daily_theme"] = theme
    draft["auto_generated"] = True

    draft_path = DRAFTS_DIR / f"{job_id}.json"
    state = PipelineState(draft)
    state.complete_stage("research")
    state.complete_stage("draft")
    state.save(draft_path)

    log(f"Draft saved: {draft_path}")
    log(f"Title: {draft.get('youtube_title', '')}")

    if dry_run:
        log("Dry run — stopping after draft")
        print(f"\nDraft: {draft_path}")
        print(f"Title: {draft.get('youtube_title', '')}")
        print(f"Script:\n{draft.get('script', '')}")
        return draft_path

    # Step 3: Produce video
    from verticals.broll import generate_broll
    from verticals.tts import generate_voiceover
    from verticals.captions import generate_captions
    from verticals.music import select_and_prepare_music
    from verticals.assemble import assemble_video
    from verticals.niche import get_voice_config, get_caption_config, get_music_config
    import shutil

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    work_dir = MEDIA_DIR / f"work_{job_id}_{lang}"
    work_dir.mkdir(exist_ok=True)

    # B-roll (with Leonardo.ai reference images for Otto)
    log("Generating b-roll...")
    frames = generate_broll(
        draft.get("broll_prompts", ["Cute black Shih-Poo dog"] * 3),
        work_dir,
        niche=niche,
    )
    state.complete_stage("broll", {"frames": [str(f) for f in frames]})

    # Voiceover
    log("Generating voiceover...")
    tts_provider = voice or "edge"
    voice_config = get_voice_config(profile, provider=tts_provider, lang=lang)
    vo_path = generate_voiceover(
        draft["script"], work_dir, lang,
        provider=tts_provider,
        voice_config=voice_config,
    )
    state.complete_stage("voiceover", {"path": str(vo_path)})

    # Captions
    log("Generating captions...")
    caption_config = get_caption_config(profile)
    captions_result = generate_captions(
        vo_path, work_dir, lang,
        highlight_color=caption_config.get("highlight_color", "#FFD6A5"),
        words_per_group=caption_config.get("words_per_group", 3),
    )
    state.complete_stage("captions", {
        "srt_path": str(captions_result.get("srt_path", "")),
        "ass_path": str(captions_result.get("ass_path", "")),
    })

    # Music
    log("Selecting music...")
    music_config = get_music_config(profile)
    music_result = select_and_prepare_music(
        vo_path, work_dir,
        duck_speech=music_config.get("duck_volume_speech", 0.10),
        duck_gap=music_config.get("duck_volume_gap", 0.20),
    )
    state.complete_stage("music", {
        "track_path": str(music_result.get("track_path", "")),
        "duck_filter": music_result.get("duck_filter", ""),
    })

    # Assemble
    log("Assembling video...")
    video_path = assemble_video(
        frames=frames,
        voiceover=vo_path,
        out_dir=work_dir,
        job_id=job_id,
        lang=lang,
        ass_path=captions_result.get("ass_path"),
        music_path=music_result.get("track_path"),
        duck_filter=music_result.get("duck_filter"),
    )
    state.complete_stage("assemble", {"video_path": str(video_path)})

    # Save SRT
    srt_path = captions_result.get("srt_path")
    if srt_path and Path(srt_path).exists():
        final_srt = MEDIA_DIR / f"verticals_{job_id}_{lang}.srt"
        shutil.copy(srt_path, final_srt)
        draft[f"srt_{lang}"] = str(final_srt)

    draft[f"video_{lang}"] = str(video_path)
    state.save(draft_path)
    log(f"Video produced: {video_path}")

    # Step 4: Upload
    from verticals.upload import upload_to_youtube
    from verticals.thumbnail import generate_thumbnail

    # Thumbnail
    try:
        thumb_path = generate_thumbnail(draft, MEDIA_DIR)
        state.complete_stage("thumbnail", {"path": str(thumb_path)})
    except Exception as e:
        log(f"Thumbnail failed: {e}")
        thumb_path = None

    # Upload
    srt_upload = Path(draft.get(f"srt_{lang}", "")) if draft.get(f"srt_{lang}") else None
    url = upload_to_youtube(video_path, draft, srt_upload, lang, thumb_path)
    state.complete_stage("upload", {"url": url})
    draft[f"youtube_url_{lang}"] = url
    state.save(draft_path)

    log(f"\nDone! Live at: {url}")
    log(f"Draft: {draft_path}")

    # Log to daily history
    history_file = LOGS_DIR / "daily_history.jsonl"
    history_entry = {
        "date": timestamp,
        "theme": theme,
        "topic": topic,
        "title": draft.get("youtube_title", ""),
        "url": url,
        "draft": str(draft_path),
        "job_id": job_id,
    }
    with open(history_file, "a") as f:
        f.write(json.dumps(history_entry) + "\n")

    return url


def main():
    parser = argparse.ArgumentParser(description="Daily YouTube Shorts automation for Otto")
    parser.add_argument("--niche", default="pets", help="Niche profile (default: pets)")
    parser.add_argument("--discover", action="store_true", help="Use trending topics instead of calendar")
    parser.add_argument("--dry-run", action="store_true", help="Draft only, no produce/upload")
    parser.add_argument("--voice", default=None, help="TTS provider: edge, elevenlabs")
    parser.add_argument("--lang", default="en", help="Language code")
    parser.add_argument("--provider", default=None, help="LLM provider: claude, gemini, openai")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    if args.verbose:
        set_verbose(True)

    try:
        run_daily_pipeline(
            niche=args.niche,
            discover=args.discover,
            dry_run=args.dry_run,
            voice=args.voice,
            lang=args.lang,
            provider=args.provider,
        )
    except Exception as e:
        log(f"Pipeline failed: {e}")
        # Log failure
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        error_log = LOGS_DIR / "errors.log"
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(error_log, "a") as f:
            f.write(f"[{timestamp}] {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
