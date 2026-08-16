"""Publishing policy — resolved per niche, overridable by environment.

Nothing here decides content. It decides how a finished file reaches YouTube:
privacy, made-for-kids, category, and whether the niche is allowed to publish
Shorts at all right now.

Resolution order for every value: environment variable > niche profile > safe default.
The safe default is private. Publishing is irreversible and customer-facing; an
unattended pipeline should never be the thing that makes something public.
"""

import os

from .log import log
from .niche import load_niche

VALID_PRIVACY = {"private", "unlisted", "public"}

DEFAULTS = {
    "privacy": "private",
    "made_for_kids": False,
    "category_id": "22",
    "shorts_allowed": True,
    "phase": None,
}


def _env_bool(name: str):
    val = os.environ.get(name)
    if val is None:
        return None
    return val.strip().lower() in ("1", "true", "yes", "on")


def get_publish_policy(niche: str = "general") -> dict:
    profile = load_niche(niche)
    cfg = profile.get("publishing", {}) or {}

    privacy = os.environ.get("YT_PRIVACY") or cfg.get("privacy") or DEFAULTS["privacy"]
    privacy = str(privacy).strip().lower()
    if privacy not in VALID_PRIVACY:
        log(f"Unknown privacy '{privacy}' — falling back to private")
        privacy = "private"

    mfk = _env_bool("YT_MADE_FOR_KIDS")
    if mfk is None:
        mfk = cfg.get("made_for_kids", DEFAULTS["made_for_kids"])

    shorts_allowed = _env_bool("YT_SHORTS_ALLOWED")
    if shorts_allowed is None:
        shorts_allowed = cfg.get("shorts_allowed", DEFAULTS["shorts_allowed"])

    return {
        "niche": niche,
        "privacy": privacy,
        "made_for_kids": bool(mfk),
        "category_id": str(os.environ.get("YT_CATEGORY_ID") or cfg.get("category_id") or DEFAULTS["category_id"]),
        "shorts_allowed": bool(shorts_allowed),
        "phase": cfg.get("phase"),
        "blocked_reason": cfg.get("shorts_blocked_reason", ""),
    }


class PublishBlocked(Exception):
    """Raised when a niche's own policy forbids publishing this format right now."""


def assert_publishable(niche: str, platform: str = "shorts") -> dict:
    """Check the niche's publishing policy before an upload is attempted."""
    policy = get_publish_policy(niche)
    if platform in ("shorts", "reels", "tiktok") and not policy["shorts_allowed"]:
        reason = policy["blocked_reason"] or (
            f"Niche '{niche}' has shorts_allowed: false in its profile."
        )
        raise PublishBlocked(reason)
    return policy
