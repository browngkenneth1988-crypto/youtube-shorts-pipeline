# Verticals v3

AI-native vertical video engine: topic + niche -> finished YouTube Short in ~3 minutes.

## Quick reference

```bash
python -m verticals run --news "headline" --niche tech          # full pipeline
python -m verticals run --news "headline" --niche tech --dry-run # draft only
python -m verticals draft --news "headline" --niche finance     # script + metadata
python -m verticals produce --draft <path> --voice edge         # video from draft
python -m verticals topics --niche tech --limit 20              # discover topics
python -m verticals niches                                      # list niche profiles
```

## Key flags

- `--news`: topic/headline (required for draft/run)
- `--niche`: content niche profile from `niches/*.yaml` (default: general)
- `--provider`: LLM provider — claude, gemini, openai, ollama, claude_cli
- `--voice`: TTS provider — edge, elevenlabs, say
- `--platform`: shorts, reels, tiktok, all
- `--dry-run`: generate draft only, skip produce + upload

## Architecture

All modules are flat under `verticals/`:
- `__main__.py` — CLI entry point (argparse)
- `config.py` — API key resolution, setup wizard, constants
- `llm.py` — multi-provider LLM abstraction (call_llm)
- `draft.py` — script generation with niche intelligence
- `research.py` — DuckDuckGo anti-hallucination gate
- `niche.py` — YAML niche profile loader
- `broll.py` — b-roll image generation (Gemini Imagen)
- `tts.py` — TTS provider abstraction (Edge TTS, ElevenLabs)
- `captions.py` — Whisper transcription + ASS/SRT caption styling
- `music.py` — background music selection + voice ducking
- `assemble.py` — ffmpeg video composition
- `thumbnail.py` — thumbnail generation
- `upload.py` — YouTube OAuth upload
- `state.py` — pipeline state tracking (JSON)
- `topics/` — topic discovery engine (reddit, rss, google_trends, newsapi)

Niche profiles live in `niches/*.yaml` (16 built-in).

## Config

API keys resolve: env var -> `~/.verticals/config.json` -> fallback.
Data dirs: `~/.verticals/{drafts,media,logs}/`

## Tests

```bash
python -m pytest tests/ -v
```

Tests mock `verticals.draft.call_llm` (not the old `_call_claude`).

## Known limitations

- Twitter and TikTok topic sources are stubs (return empty)
- `music/` directory must be manually created with MP3 tracks
- Full pipeline requires GEMINI_API_KEY (b-roll) and network access (Edge TTS)
