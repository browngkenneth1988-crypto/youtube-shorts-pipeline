# CLAUDE.md — Otto's Production Hub

## Project Identity

**Verticals v3.0.0** — AI-native vertical video engine with niche intelligence.
One command takes a topic + niche and outputs a finished YouTube Short/Reel/TikTok
with AI-generated b-roll, voiceover, burned-in captions, background music, and thumbnail.

- **Repo:** `browngkenneth1988-crypto/youtube-shorts-pipeline`
- **Package name:** `verticals`
- **License:** MIT
- **Owner:** Dr Rushindra Sinha

## Stack

- **Language:** Python 3.10+
- **Build system:** setuptools via `pyproject.toml`
- **Dependencies:** anthropic, requests, Pillow, feedparser, google-api-python-client,
  google-auth, google-auth-oauthlib, openai-whisper, PyYAML, edge-tts
- **Dev dependencies:** pytest, pytest-mock
- **External tools required at runtime:** ffmpeg, ffprobe (video assembly), whisper (captions)
- **No CI pipeline** — no GitHub Actions, no Dockerfile in repo yet
- **No web UI in repo** — Gradio UI mentioned in README/CHANGELOG but code not present

## Architecture

Flat package under `verticals/`. Pipeline flows left to right:

```
topic -> research -> draft (script) -> broll -> voiceover -> captions -> music -> assemble -> upload
```

Each stage is a separate module. A `PipelineState` object (state.py) tracks completion
per stage in the draft JSON for resume capability.

### Key modules

| Module | Purpose |
|--------|---------|
| `__main__.py` | CLI entry point (argparse), orchestrates `run/draft/produce/upload/topics/niches` commands |
| `config.py` | API key resolution (env -> config.json), paths, constants, setup wizard, Claude CLI support |
| `niche.py` | YAML niche profile loader, stage-specific context extractors |
| `llm.py` | Multi-provider LLM abstraction (claude, gemini, openai, ollama, claude_cli) |
| `draft.py` | Script generation with niche intelligence, calls `research_topic` + `call_llm` |
| `research.py` | DuckDuckGo HTML scraping for anti-hallucination gate |
| `broll.py` | Gemini Imagen b-roll generation + Ken Burns animation |
| `tts.py` | Multi-provider TTS (Edge TTS default, ElevenLabs, macOS say) |
| `voiceover.py` | Legacy shim, delegates to `tts.py` |
| `captions.py` | Whisper word-level timestamps -> ASS (burn-in) + SRT (upload) |
| `music.py` | Track selection + ffmpeg volume ducking filter |
| `assemble.py` | ffmpeg final assembly (animated frames + voice + captions + music) |
| `thumbnail.py` | Gemini Imagen thumbnail + Pillow text overlay |
| `upload.py` | YouTube API upload with OAuth, SRT captions, thumbnail |
| `retry.py` | Exponential backoff decorator |
| `log.py` | Structured file + console logging |
| `topics/` | Multi-source topic discovery engine (reddit, rss, google_trends, newsapi, twitter, tiktok) |
| `state.py` | Pipeline stage tracking for resume capability |

### Niche profiles

16 YAML files in `niches/` (tech, gaming, finance, fitness, cooking, travel, true_crime,
science, politics, entertainment, sports, fashion, education, motivation, comedy, general).
Each profile configures: script tone/hooks/CTAs, visual style, voice config, caption styling,
music mood, thumbnail strategy, topic discovery sources.

## Commands

```bash
# Full pipeline
python -m verticals run --topic "headline" --niche tech

# Individual stages
python -m verticals draft --news "headline" --niche tech
python -m verticals produce --draft <path> --lang en
python -m verticals upload --draft <path>
python -m verticals topics --niche tech --limit 20
python -m verticals niches
```

## Testing

```bash
python -m pytest tests/ -v
```

- 78 tests across 8 test files
- Tests use `pytest-mock` and `unittest.mock` for API mocking
- No integration tests — all external calls (LLM, TTS, Gemini, YouTube) are mocked
- Test fixtures in `tests/conftest.py` (sample_draft, sample_words, sample_speech_regions)

### Test conventions
- Test files mirror source: `test_config.py`, `test_draft.py`, `test_captions.py`, etc.
- Mock at the boundary: patch `call_llm` (not internal provider functions) for draft tests
- Mock `research_topic` to avoid network calls
- Each test class groups related tests: `TestGenerateDraft`, `TestWordGrouping`, etc.

## Quality Gates

Before pushing any change, run:

1. **`python -m pytest tests/ -v`** — all tests must pass
2. **`python -c "import verticals"`** — package must import cleanly
3. Review for OWASP top-10 issues (injection, credential exposure, etc.)

## Code Conventions

- **No type stubs** — use inline type hints (Python 3.10+ syntax: `str | None`)
- **Docstrings** on public functions and modules (one-line or numpy-style)
- **Logging** via `verticals.log.log()` (INFO level) — never bare `print()` in library code
  (CLI entry points in `__main__.py` use `print()` for user-facing output)
- **Retry** via `@with_retry(max_retries=N, base_delay=X)` decorator for external API calls
- **Security:** credentials via `write_secret_file()` (0600 perms), API keys via headers not URLs,
  YAML via `safe_load()`, research snippets truncated to 300 chars
- **Config resolution:** env var -> `~/.verticals/config.json` -> fallback/auto-detect
- **Imports:** stdlib -> third-party -> local (relative imports within package)
- **Error handling:** let exceptions bubble up to CLI layer; stages log warnings and use fallbacks

## Known Issues & Tech Debt

1. **README drift:** README describes `providers/`, `stages/`, `ui/`, `docker-compose.yml`,
   `Dockerfile`, `notebooks/` directories that don't exist in the repo. The actual structure
   is flat under `verticals/`.
2. **No CI:** No GitHub Actions workflow. Tests must be run manually.
3. **No Docker:** Dockerfile and docker-compose.yml mentioned but not in repo.
4. **No Gradio UI:** Web UI code not present despite README documentation.
5. **voiceover.py is a shim:** Just re-exports from `tts.py`. Could be removed if
   all imports are updated.

## Git Conventions

- **Branch:** develop on feature branches, merge to `main`
- **Commit style:** `type: description` (e.g., `feat:`, `fix:`, `docs:`, `security:`, `polish:`)
- **No force-push to main**

## Session Continuity

When starting a new session on this repo:
1. Read this CLAUDE.md first
2. Run `python -m pytest tests/ -v` to verify baseline
3. Check `git log --oneline -5` for recent changes
4. Check for any open issues or PRs
