# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Verticals v3** — AI-native vertical video engine. One command takes a topic and niche profile and produces a finished YouTube Short with research-grounded script, AI-generated b-roll, voiceover, burned-in captions, background music, and thumbnail upload.

Package name is `verticals`; entry point is `python -m verticals`.

## Commands

### Running the pipeline
```bash
# Full pipeline (research → script → visuals → voice → captions → music → assemble → upload)
python -m verticals run --news "headline" --niche tech

# Draft only (research + script, no video)
python -m verticals draft --news "headline" --niche tech --provider gemini

# Produce video from an existing draft JSON
python -m verticals produce --draft ~/.verticals/drafts/<job_id>.json --lang en

# Upload a produced video
python -m verticals upload --draft ~/.verticals/drafts/<job_id>.json

# Discover trending topics for a niche
python -m verticals topics --niche tech --limit 20

# List available niche profiles
python -m verticals niches
```

### Tests
```bash
pip install pytest pytest-mock
python -m pytest tests/ -v

# Single test file
python -m pytest tests/test_draft.py -v

# Single test
python -m pytest tests/test_state.py::test_complete_stage -v
```

No linter is configured in pyproject.toml. `pip install -e ".[dev]"` installs pytest/pytest-mock.

## Architecture

### Pipeline stages and data flow

The pipeline is split into two top-level commands (`draft` then `produce`/`upload`), each orchestrated in `verticals/__main__.py`:

```
draft command:   research_topic() → generate_draft() → PipelineState → <job_id>.json
produce command: generate_broll() → generate_voiceover() → generate_captions()
                 → select_and_prepare_music() → assemble_video()
upload command:  generate_thumbnail() → upload_to_youtube()
```

The **draft JSON** (`~/.verticals/drafts/<job_id>.json`) is the central artifact that flows through every stage. It contains the script, b-roll prompts, platform metadata, stage completion state, and paths to produced media. All produced files live in `~/.verticals/media/work_<job_id>_<lang>/`.

### Niche intelligence

Every stage is shaped by a **niche profile** loaded from `niches/<name>.yaml`. `verticals/niche.py` loads and caches these and exposes per-stage accessors (`get_script_context`, `get_voice_config`, `get_caption_config`, `get_music_config`, `get_visual_context`). The niche profile is loaded from the draft JSON's `niche` field on produce/upload, so a draft and its video always use the same profile.

To add a new niche: copy any existing YAML in `niches/`, edit it, and reference it with `--niche your_niche_name`. The fallback is always `niches/general.yaml`.

### Resume capability (`PipelineState`)

`verticals/state.py` embeds a `_pipeline_state` dict inside the draft JSON. Each stage records `status` (done/failed), `timestamp`, and artifact paths. `produce` skips any stage already marked `done` unless `--force` is passed. This lets a failed run resume from the last successful stage.

Stage order: `research → draft → broll → voiceover → whisper → captions → music → assemble → thumbnail → upload`

### LLM provider routing (`verticals/llm.py`)

`call_llm(prompt, provider)` resolves the provider via: explicit arg → `LLM_PROVIDER` env → `config.json` → auto-detect (key presence, Ollama availability, Claude CLI). Supports `claude`, `gemini`, `openai`, `ollama`, `claude_cli`. The `claude` provider itself checks for API key vs. Claude CLI via `get_claude_backend()`.

`call_llm` is decorated with `@with_retry(max_retries=2, base_delay=3.0)`.

### Topic engine (`verticals/topics/`)

`TopicEngine` fetches from multiple sources in parallel (ThreadPoolExecutor). Sources implement `TopicSource` ABC. Built-in: `RedditSource`, `RSSSource`, `GoogleTrendsSource`, `NewsAPISource` (optional), `TwitterSource` (optional), `TikTokSource` (optional). Sources load from `config.json["topic_sources"]`; niche defaults (subreddit lists, etc.) are applied from `NICHE_TO_SUBREDDITS` in `config.py` when no explicit config exists.

### Configuration and credential storage

All runtime data lives in `~/.verticals/`:
- `config.json` — API keys and optional `topic_sources` / `LLM_PROVIDER` overrides (0600 permissions)
- `drafts/` — draft JSON files
- `media/` — produced video files
- `youtube_token.json` — YouTube OAuth token

API key resolution in `config.py`: environment variable takes priority over `config.json`. Run `python3 scripts/setup_youtube_oauth.py` to generate the YouTube token.

### Research anti-hallucination gate (`verticals/research.py`)

`research_topic()` fetches DuckDuckGo snippets (truncated to 300 chars each, max 8 snippets) and passes them to the LLM as boundary-marked untrusted data. The LLM prompt explicitly instructs the model to use only facts from this research block, never training knowledge.

## Key conventions

- **Draft JSON is the source of truth.** Never hardcode paths; always read them from the draft dict or `PipelineState.get_artifact()`.
- **Niche profile keys are optional at every level.** All `get_*_config()` helpers return defaults when keys are missing, so new niche profiles don't need to be exhaustive.
- **YAML niche profiles use `yaml.safe_load` only** — no Python tags, no arbitrary code execution.
- **`write_secret_file()` must be used for all credential files** to avoid TOCTOU races with world-readable permissions.
- **`@with_retry` is on all external API calls.** Apply it to any new function that hits an external service.
- The `--force` flag resets `PipelineState` and re-runs all stages. Implement idempotency so stages can be safely re-run.
- Tests mock all external calls (LLM, TTS, ffmpeg). Use `pytest-mock`'s `mocker` fixture. See `tests/conftest.py` for shared fixtures (`sample_draft`, `tmp_work_dir`, `sample_words`).
