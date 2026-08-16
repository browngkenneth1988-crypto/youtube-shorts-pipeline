#!/usr/bin/env python3
"""Download royalty-free lullaby tracks for Life With Otto videos.

Downloads Creative Commons / royalty-free lullaby music from Pixabay's
free music library. These tracks are safe for YouTube monetization.

Usage:
    python scripts/download_lullabies.py
"""

import sys
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MUSIC_DIR = PROJECT_ROOT / "music"
MUSIC_DIR.mkdir(exist_ok=True)

# Pixabay royalty-free music API (free, no key needed for search)
PIXABAY_API = "https://pixabay.com/api/"
# Note: Pixabay requires an API key for downloads.
# These are direct links to well-known royalty-free lullaby sources.

# Curated list of royalty-free lullaby/sleep music from free sources
# All CC0 or royalty-free for commercial use
FREE_TRACKS = [
    {
        "name": "gentle_lullaby_music_box",
        "url": "https://cdn.pixabay.com/audio/2022/01/18/audio_d0a13f69d2.mp3",
        "description": "Gentle music box lullaby",
    },
    {
        "name": "soft_piano_lullaby",
        "url": "https://cdn.pixabay.com/audio/2022/08/02/audio_884fe92c21.mp3",
        "description": "Soft piano lullaby for sleep",
    },
    {
        "name": "dreamy_ambient_sleep",
        "url": "https://cdn.pixabay.com/audio/2022/05/27/audio_1808fbf07a.mp3",
        "description": "Dreamy ambient sleep music",
    },
    {
        "name": "twinkle_music_box",
        "url": "https://cdn.pixabay.com/audio/2021/11/25/audio_91b32e02f9.mp3",
        "description": "Twinkle twinkle music box style",
    },
    {
        "name": "calm_piano_bedtime",
        "url": "https://cdn.pixabay.com/audio/2023/01/16/audio_4d0cfe498f.mp3",
        "description": "Calm piano for bedtime",
    },
]


def download_track(track: dict) -> bool:
    """Download a single track to the music directory."""
    out_path = MUSIC_DIR / f"{track['name']}.mp3"
    if out_path.exists():
        print(f"  Already exists: {out_path.name}")
        return True

    print(f"  Downloading: {track['description']}...")
    try:
        r = requests.get(track["url"], timeout=60, stream=True)
        r.raise_for_status()
        out_path.write_bytes(r.content)
        size_mb = out_path.stat().st_size / (1024 * 1024)
        print(f"  Saved: {out_path.name} ({size_mb:.1f} MB)")
        return True
    except Exception as e:
        print(f"  Failed: {e}")
        if out_path.exists():
            out_path.unlink()
        return False


def main():
    print("Downloading royalty-free lullaby tracks for Life With Otto...")
    print(f"Music directory: {MUSIC_DIR}\n")

    success = 0
    for track in FREE_TRACKS:
        if download_track(track):
            success += 1

    print(f"\nDone! {success}/{len(FREE_TRACKS)} tracks downloaded.")
    print(f"Music directory: {MUSIC_DIR}")

    if success == 0:
        print("\nNo tracks downloaded. You can manually add .mp3 files to the music/ folder.")
        print("Good sources for free lullaby music:")
        print("  - Pixabay Music (pixabay.com/music)")
        print("  - YouTube Audio Library (studio.youtube.com)")
        print("  - Free Music Archive (freemusicarchive.org)")
        sys.exit(1)


if __name__ == "__main__":
    main()
