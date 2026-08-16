"""Multi-provider LLM abstraction.

Supports: claude (Anthropic), gemini (Google), openai (OpenAI), ollama (local).
Provider selection: --provider flag or LLM_PROVIDER env var or config.json.
"""

import os
import threading
import time

from .config import (
    call_claude_cli,
    get_anthropic_client,
    get_anthropic_key,
    get_claude_backend,
    get_gemini_key,
)
from .log import log


def get_provider(name: str | None = None) -> str:
    """Resolve which LLM provider to use.

    Priority: explicit name > LLM_PROVIDER env > config.json > auto-detect.
    """
    if name and name != "auto":
        return name.lower()

    from_env = os.environ.get("LLM_PROVIDER", "").lower()
    if from_env:
        return from_env

    from .config import load_config
    cfg = load_config()
    from_cfg = cfg.get("LLM_PROVIDER", "").lower()
    if from_cfg:
        return from_cfg

    # Auto-detect: try providers in preference order
    if get_anthropic_key():
        return "claude"
    if get_gemini_key():
        return "gemini"
    if os.environ.get("OPENAI_API_KEY") or cfg.get("OPENAI_API_KEY"):
        return "openai"
    if _ollama_available():
        return "ollama"

    # Last resort: Claude CLI
    from .config import has_claude_cli
    if has_claude_cli():
        return "claude_cli"

    raise RuntimeError(
        "No LLM provider found. Set one of:\n"
        "  ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY\n"
        "  Or install Ollama with a model pulled\n"
        "  Or install Claude Code with a Max subscription"
    )


def _ollama_available() -> bool:
    """Check if Ollama is running locally."""
    try:
        import requests
        r = requests.get("http://localhost:11434/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


# Order the unattended jobs fall through when a provider stops answering.
# Cheapest first: Gemini's free tier, then paid Claude/OpenAI, then local Ollama
# which costs nothing but needs the daemon running.
FALLBACK_ORDER = ["gemini", "claude", "openai", "ollama", "claude_cli"]

# Every provider _dispatch knows how to route to.
#
# An unrecognised name is a configuration error — a typo in --provider or in
# config.json — so it fails fast instead of entering the fallback chain. The
# chain exists for providers that are real but unavailable; letting a bad name
# through means a typo silently runs the job on a different vendor than asked
# for, and (before this check) burned three retries plus 9s of backoff first.
KNOWN_PROVIDERS = frozenset(FALLBACK_ORDER)


def _provider_configured(name: str) -> bool:
    """True if this provider has what it needs to be worth attempting."""
    from .config import has_claude_cli, load_config
    cfg = load_config()
    if name == "gemini":
        return bool(get_gemini_key())
    if name == "claude":
        return bool(get_anthropic_key()) or has_claude_cli()
    if name == "claude_cli":
        return has_claude_cli()
    if name == "openai":
        return bool(os.environ.get("OPENAI_API_KEY") or cfg.get("OPENAI_API_KEY"))
    if name == "ollama":
        return _ollama_available()
    return False


def build_fallback_chain(provider: str | None = None) -> list[str]:
    """Preferred provider first, then every other configured provider.

    The 6am job used to die whenever Gemini's free tier hit its daily quota —
    three retries against the same exhausted key, then a stack trace. A quota
    error is a fact about one vendor, not about the task, so the chain exists
    to let the run finish on a different one.
    """
    first = get_provider(provider)
    if first not in KNOWN_PROVIDERS:
        raise ValueError(
            f"Unknown LLM provider: {first}. "
            f"Known providers: {', '.join(sorted(KNOWN_PROVIDERS))}"
        )
    chain = [first]
    for name in FALLBACK_ORDER:
        if name not in chain and _provider_configured(name):
            chain.append(name)
    return chain


# Requests-per-minute pacing. Gemini's free tier caps gemini-2.5-flash at 10/min
# and the queue builder fires scoring calls back to back, so pacing keeps the
# per-minute ceiling from adding avoidable 429s on top of the daily one.
# 0 means "don't throttle".
PROVIDER_RPM = {"gemini": 8, "claude": 0, "openai": 0, "ollama": 0, "claude_cli": 0}

# Errors that mean "this provider is done for now" rather than "try again".
# Retrying these is worse than useless on a metered free tier: Gemini's free
# allowance for gemini-2.5-flash is 20 requests PER DAY, so three attempts
# against an exhausted quota burn 3 of the day's 20 to learn what the first
# attempt already said. Fail over immediately instead.
_EXHAUSTED_MARKERS = (
    "429", "quota", "rate limit", "resource_exhausted",
    "permission_denied", "403", "401", "unauthenticated",
    "invalid api key", "api key not valid", "billing",
)


class ProviderExhausted(RuntimeError):
    """This provider will not answer again this run — move to the next one."""


def _is_exhausted(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _EXHAUSTED_MARKERS)


# Providers that have already reported exhaustion this process. The queue
# builder scores a dozen topics in one run; without this, every topic after the
# first failure spends another request rediscovering the same dead quota.
_exhausted: set[str] = set()


def reset_exhausted():
    """Clear the exhausted set. For tests and long-lived processes."""
    _exhausted.clear()


_throttle_lock = threading.Lock()
_last_call_at: dict[str, float] = {}


def _throttle(provider: str):
    """Block until enough time has passed since the last call to this provider."""
    rpm = PROVIDER_RPM.get(provider, 0)
    if not rpm:
        return
    min_gap = 60.0 / rpm
    with _throttle_lock:
        previous = _last_call_at.get(provider)
        now = time.monotonic()
        if previous is not None:
            wait = min_gap - (now - previous)
            if wait > 0:
                log(f"Pacing {provider} — waiting {wait:.1f}s to stay under {rpm}/min")
                time.sleep(wait)
                now = time.monotonic()
        _last_call_at[provider] = now


def _call_provider(provider: str, prompt: str, max_tokens: int,
                   json_mode: bool = False) -> str:
    """Call one provider, retrying only failures that retrying can fix.

    A timeout or a 500 is worth another attempt. A quota or auth error is not —
    it costs another request against the same exhausted budget and returns the
    same answer, so it raises ProviderExhausted and lets call_llm fail over.
    """
    attempts = 3
    for attempt in range(attempts):
        try:
            return _dispatch(provider, prompt, max_tokens, json_mode=json_mode)
        except Exception as e:
            if _is_exhausted(e):
                raise ProviderExhausted(f"{provider} exhausted: {e}") from e
            if attempt == attempts - 1:
                raise
            delay = 3.0 * (2 ** attempt)
            log(f"{provider} failed (attempt {attempt + 1}/{attempts}): {e} "
                f"— retrying in {delay:.1f}s")
            time.sleep(delay)


def _dispatch(provider: str, prompt: str, max_tokens: int,
              json_mode: bool = False) -> str:
    """Route to one provider's implementation, after pacing."""
    _throttle(provider)
    if provider == "claude":
        return _call_claude(prompt, max_tokens)
    elif provider == "claude_cli":
        return call_claude_cli(prompt, max_tokens=max_tokens)
    elif provider == "gemini":
        return _call_gemini(prompt, max_tokens, json_mode=json_mode)
    elif provider == "openai":
        return _call_openai(prompt, max_tokens)
    elif provider == "ollama":
        return _call_ollama(prompt)
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")


def call_llm(prompt: str, provider: str | None = None, max_tokens: int = 1500,
             json_mode: bool = False) -> str:
    """Call an LLM, falling through to other configured providers on failure.

    Args:
        prompt: The full prompt text.
        provider: Preferred provider (claude, gemini, openai, ollama, claude_cli).
        max_tokens: Maximum response tokens.
        json_mode: Ask the provider to guarantee JSON where it supports it.

    Returns:
        The LLM response text.

    Raises:
        RuntimeError: only when every configured provider failed.
    """
    chain = build_fallback_chain(provider)
    failures = []
    live = [n for n in chain if n not in _exhausted]

    if not live:
        raise RuntimeError(
            "Every configured LLM provider is out of quota for this run: "
            + ", ".join(chain)
            + "\n  Add a second provider (ANTHROPIC_API_KEY, OPENAI_API_KEY, or a "
              "local Ollama) so the queue builder survives one vendor running dry."
        )

    for i, name in enumerate(live):
        log(f"Calling LLM via {name}...")
        try:
            return _call_provider(name, prompt, max_tokens, json_mode=json_mode)
        except ProviderExhausted as e:
            _exhausted.add(name)
            failures.append(f"{name}: exhausted — {str(e)[:200]}")
            log(f"{name} is out of quota; skipping it for the rest of this run")
        except Exception as e:
            failures.append(f"{name}: {type(e).__name__}: {str(e)[:200]}")
        if i + 1 < len(live):
            log(f"Falling through to {live[i + 1]}")

    raise RuntimeError(
        "Every configured LLM provider failed.\n  " + "\n  ".join(failures)
    )


def _call_claude(prompt: str, max_tokens: int) -> str:
    """Call Claude via Anthropic API."""
    backend = get_claude_backend()
    if backend == "cli":
        return call_claude_cli(prompt, max_tokens=max_tokens)

    client = get_anthropic_client()
    # Thinking is on by default on Opus 5 and max_tokens caps thinking plus the
    # answer together, so the budget is floored — a 1500-token cap tuned for a
    # non-thinking model truncates the response mid-sentence. Effort is low
    # because scoring and drafting are routine work, not hard reasoning.
    msg = client.messages.create(
        model="claude-opus-5",
        max_tokens=max(max_tokens, 4096),
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": prompt}],
    )
    if msg.stop_reason == "refusal":
        raise RuntimeError("Claude declined the request (stop_reason=refusal)")

    # content can lead with a thinking block — take the text, don't index [0].
    text = " ".join(b.text for b in msg.content if b.type == "text").strip()
    if not text:
        raise RuntimeError(f"Empty response from Claude (stop_reason={msg.stop_reason})")
    return text


def _call_gemini(prompt: str, max_tokens: int, json_mode: bool = False) -> str:
    """Call Gemini via Google AI API.

    gemini-2.5-flash is a thinking model and reasoning tokens are charged
    against maxOutputTokens. Left alone, a modest budget returns an empty
    candidate. So thinking is disabled and the budget is floored, and when
    json_mode is set the API is asked to guarantee a JSON response instead
    of us hoping the prompt was persuasive.
    """
    import requests

    api_key = get_gemini_key()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    url = (
        "https://generativelanguage.googleapis.com/v1beta"
        "/models/gemini-2.5-flash:generateContent"
    )
    gen = {
        "maxOutputTokens": max(max_tokens, 2048),
        "temperature": 0.2 if json_mode else 0.7,
        "thinkingConfig": {"thinkingBudget": 0},
    }
    if json_mode:
        gen["responseMimeType"] = "application/json"

    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}

    def _post(generation_config):
        return requests.post(
            url,
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": generation_config},
            timeout=90, headers=headers,
        )

    r = _post(gen)
    # Older/other models reject thinkingConfig — retry without it rather than die.
    if r.status_code == 400 and "thinking" in r.text.lower():
        gen.pop("thinkingConfig", None)
        r = _post(gen)
    if r.status_code != 200:
        raise RuntimeError(f"Gemini API {r.status_code}: {r.text[:300]}")

    data = r.json()
    cand = (data.get("candidates") or [{}])[0]
    parts = cand.get("content", {}).get("parts", [])
    text = " ".join(p.get("text", "") for p in parts).strip()
    if not text:
        reason = cand.get("finishReason", "unknown")
        usage = data.get("usageMetadata", {})
        raise RuntimeError(
            f"Empty response from Gemini (finishReason={reason}, usage={usage})"
        )
    return text


def _call_openai(prompt: str, max_tokens: int) -> str:
    """Call OpenAI GPT via API."""
    import requests

    from .config import load_config
    api_key = os.environ.get("OPENAI_API_KEY") or load_config().get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "gpt-4o-mini",
            "max_tokens": max_tokens,
            "temperature": 0.7,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    if r.status_code != 200:
        raise RuntimeError(f"OpenAI API {r.status_code}: {r.text[:300]}")

    data = r.json()
    return data["choices"][0]["message"]["content"].strip()


def _call_ollama(prompt: str) -> str:
    """Call Ollama locally (no API key needed).

    Tries models in preference order: llama3.1:8b, mistral, gemma2.
    """
    import requests

    # Find available models
    try:
        tags = requests.get("http://localhost:11434/api/tags", timeout=5).json()
        available = [m["name"] for m in tags.get("models", [])]
    except Exception as e:
        raise RuntimeError("Ollama not running. Start with: ollama serve") from e

    if not available:
        raise RuntimeError("No Ollama models found. Pull one: ollama pull llama3.1:8b")

    # Pick best available model
    preferred = ["llama3.1:8b", "llama3:8b", "mistral", "gemma2", "qwen2.5:7b"]
    model = None
    for pref in preferred:
        for avail in available:
            if pref in avail:
                model = avail
                break
        if model:
            break
    if not model:
        model = available[0]

    log(f"Using Ollama model: {model}")

    r = requests.post(
        "http://localhost:11434/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=120,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Ollama {r.status_code}: {r.text[:300]}")

    return r.json().get("response", "").strip()
