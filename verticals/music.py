"""Background music — track selection + volume ducking."""

import random
from pathlib import Path

from .log import log


def _music_root() -> Path:
    """MUSIC_DIR from env or ~/.verticals/config.json; else the packaged music/."""
    from .config import _get_key
    val = _get_key("MUSIC_DIR")
    return Path(val).expanduser() if val else Path(__file__).resolve().parent.parent / "music"


MUSIC_DIR = _music_root()


def _find_tracks(niche: str = None) -> list[Path]:
    """Find MP3 tracks: MUSIC_DIR/<niche>/ first, then flat, then recursive."""
    if not MUSIC_DIR.exists():
        return []
    if niche:
        sub = MUSIC_DIR / niche
        if sub.is_dir():
            tracks = sorted(sub.glob("*.mp3"))
            if tracks:
                return tracks
    tracks = sorted(MUSIC_DIR.glob("*.mp3"))
    return tracks if tracks else sorted(MUSIC_DIR.rglob("*.mp3"))


def _get_speech_regions(audio_path: Path) -> list[tuple[float, float]]:
    """Extract speech regions from Whisper word timestamps (reuses captions data).

    Falls back to treating the entire audio as one speech region.
    """
    try:
        from .captions import _whisper_word_timestamps
        words = _whisper_word_timestamps(audio_path)
        if words:
            # Merge close words into speech regions (gap < 0.5s = same region)
            regions = []
            region_start = words[0]["start"]
            region_end = words[0]["end"]

            for w in words[1:]:
                if w["start"] - region_end < 0.5:
                    region_end = w["end"]
                else:
                    regions.append((region_start, region_end))
                    region_start = w["start"]
                    region_end = w["end"]
            regions.append((region_start, region_end))
            return regions
    except Exception:
        pass

    # Fallback: get total duration and treat as one speech region
    try:
        from .assemble import get_audio_duration
        dur = get_audio_duration(audio_path)
        return [(0.0, dur)]
    except Exception:
        return [(0.0, 60.0)]


def build_duck_filter(speech_regions: list[tuple[float, float]], buffer: float = 0.3, vol_speech: float = 0.12, vol_gap: float = 0.25) -> str:
    """Build ffmpeg volume filter expression for ducking during speech.

    During speech: volume = vol_speech (default 0.12)
    During gaps: volume = vol_gap (default 0.25)
    Transitions smoothed by ±buffer seconds.
    """
    if not speech_regions:
        return f"volume={vol_gap}"

    # Build between() conditions for speech regions
    conditions = []
    for start, end in speech_regions:
        s = max(0, start - buffer)
        e = end + buffer
        conditions.append(f"between(t,{s:.2f},{e:.2f})")

    condition_expr = "+".join(conditions)
    return f"volume='if({condition_expr}, {vol_speech}, {vol_gap})':eval=frame"


def select_and_prepare_music(
    voiceover_path: Path,
    work_dir: Path,
    duck_speech: float = 0.12,
    duck_gap: float = 0.25,
    niche: str = None,
) -> dict:
    """Select a random track, build duck filter from speech regions.

    Returns dict with track_path and duck_filter for use by assemble.py.
    """
    tracks = _find_tracks(niche)
    if not tracks:
        log(f"No music tracks found under {MUSIC_DIR} — skipping background music")
        return {}

    track = random.choice(tracks)
    log(f"Selected music track: {track.name} ({len(tracks)} available)")

    # Get speech regions for ducking
    speech_regions = _get_speech_regions(voiceover_path)
    duck_filter = build_duck_filter(speech_regions, vol_speech=duck_speech, vol_gap=duck_gap)
    log(f"Built duck filter with {len(speech_regions)} speech regions")

    return {
        "track_path": str(track),
        "duck_filter": duck_filter,
    }
