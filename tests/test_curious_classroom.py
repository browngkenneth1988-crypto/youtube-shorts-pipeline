"""Tests for the curious_classroom niche profile and its pipeline integration.

Ported from claude/verticals-sam-altman-analysis-hkfLI, where the file was
written against an older revision of niches/curious_classroom.yaml. Eight of
its seventeen tests failed against the profile as it now stands, so this is a
port of the *intent* rather than a copy — see the notes on individual tests.

Two rules followed throughout, learned from the rest of this suite:

  * Assert wiring and policy, not the arbitrary contents of a data file. A
    profile edit should not fail a plumbing test.
  * Nothing reaches the network. The original publishing-guard test patched a
    symbol the code does not use, so instead of raising it fell through into
    the real pipeline and made a live DuckDuckGo + LLM call.
"""

import sys
from unittest.mock import patch

import pytest

from verticals.niche import (
    _cache,
    get_discovery_config,
    get_script_context,
    get_visual_context,
    get_voice_config,
    load_niche,
)

NICHE = "curious_classroom"


@pytest.fixture(autouse=True)
def clear_cache():
    _cache.clear()
    yield
    _cache.clear()


@pytest.fixture
def profile():
    return load_niche(NICHE)


class TestProfileLoads:
    def test_name_and_display_name(self, profile):
        assert profile["name"] == NICHE
        # startswith, not equality: the display name carries the channel
        # tagline ("Curious Classroom — Big ideas explained simply") and the
        # original test asserted the bare name.
        assert profile["display_name"].startswith("Curious Classroom")

    def test_seven_content_pillars(self, profile):
        # Pillars live under scoring, not at the profile root where the
        # original test looked for them.
        pillars = profile["scoring"]["pillars"]
        assert len(pillars) == 7
        assert "Strange Science" in pillars
        assert "Weird History" in pillars


class TestPublishingPolicy:
    def test_phase_and_shorts_flag(self, profile):
        pub = profile["publishing"]
        assert pub["phase"] == 2
        assert pub["shorts_allowed"] is True

    def test_privacy_defaults_to_private(self, profile):
        # The key is `privacy`; the original test asserted `upload_privacy`,
        # which does not exist and so silently described nothing.
        assert profile["publishing"]["privacy"] == "private"

    def test_not_made_for_kids(self, profile):
        # Load-bearing: made-for-kids disables comments and end screens, and
        # this is a general-audience channel.
        assert profile["publishing"]["made_for_kids"] is False


class TestScoringGate:
    def test_threshold_and_categories(self, profile):
        scoring = profile["scoring"]
        assert scoring["threshold"] == 40
        assert [c["id"] for c in scoring["categories"]] == [
            "curiosity", "evergreen", "visual", "simplicity", "subscriber_fit",
        ]

    def test_gate_is_actually_enabled(self, profile):
        # Without this the rubric is inert and every topic passes ungated.
        from verticals.score import scoring_enabled
        assert scoring_enabled(profile) is True

    def test_max_total_matches_category_maxima(self, profile):
        scoring = profile["scoring"]
        assert scoring["max_total"] == sum(c["max"] for c in scoring["categories"])

    def test_threshold_is_reachable(self, profile):
        scoring = profile["scoring"]
        assert 0 < scoring["threshold"] <= scoring["max_total"]


class TestVoice:
    def test_edge_uses_brian(self, profile):
        assert get_voice_config(profile, "edge_tts", "en")["voice_id"] == (
            "en-US-BrianMultilingualNeural"
        )

    def test_elevenlabs_uses_brian_with_settings(self, profile):
        cfg = get_voice_config(profile, "elevenlabs")
        assert cfg["voice_id"] == "nPczCjzI2devNBz1zQrb"
        # Asserted as a range, not 0.55 exactly: stability is a tuning dial,
        # and the original test pinned 0.5 and broke when it was retuned.
        assert 0.4 <= cfg["settings"]["stability"] <= 0.7


class TestScriptContext:
    def test_tone_reaches_the_prompt(self, profile):
        ctx = get_script_context(profile).lower()
        assert "warm" in ctx
        assert "curious" in ctx

    def test_forbidden_phrases_reach_the_prompt(self, profile):
        ctx = get_script_context(profile)
        for phrase in profile["script"]["forbidden_phrases"][:3]:
            assert phrase in ctx

    def test_every_hook_id_reaches_the_prompt(self, profile):
        # Hooks are a list of dicts with an `id`; the original test grepped for
        # "misconception" and "mind_blow", which are not this profile's ids.
        ctx = get_script_context(profile)
        for hook in profile["script"]["hooks"]:
            assert hook["id"] in ctx


class TestVisuals:
    def test_avoids_identifiable_faces(self, profile):
        # This is the real requirement behind the original "faceless" test:
        # the channel is faceless, expressed as an avoid-list entry rather
        # than the word "faceless" in the style string.
        avoid = " ".join(get_visual_context(profile)["subjects"]["avoid"]).lower()
        assert "face" in avoid

    def test_avoids_rendered_text(self, profile):
        # Burned-in captions are added later; text baked into the image
        # collides with them.
        avoid = " ".join(get_visual_context(profile)["subjects"]["avoid"]).lower()
        assert "text" in avoid


class TestDiscovery:
    def test_reddit_sources(self, profile):
        subs = get_discovery_config(profile)["reddit"]["subreddits"]
        assert "todayilearned" in subs
        assert "askscience" in subs

    def test_rss_feeds_are_populated_and_absolute(self, profile):
        # The original pinned one specific publication (quantamagazine) that
        # the feed list no longer carries. What matters is that the source is
        # wired and usable, not which outlet is in it.
        feeds = get_discovery_config(profile)["rss"]["feeds"]
        assert feeds
        assert all(f.startswith("http") for f in feeds)


class TestPublishGuard:
    """The guard lives in publish.py, not cmd_run.

    The original test patched verticals.niche.load_niche and expected cmd_run
    to SystemExit. Nothing in __main__ reads shorts_allowed, so the patch
    missed, no exception was raised, and the test ran the real pipeline —
    reaching DuckDuckGo and call_llm. These call the guard directly instead.
    """

    def test_shorts_allowed_for_this_niche(self):
        from verticals.publish import get_publish_policy
        assert get_publish_policy(NICHE)["shorts_allowed"] is True

    def test_guard_blocks_shorts_when_profile_forbids(self):
        from verticals.publish import PublishBlocked, assert_publishable
        blocked = {"publishing": {
            "shorts_allowed": False, "phase": 1,
            "shorts_blocked_reason": "Phase 1 ships long-form only.",
        }}
        with patch("verticals.publish.load_niche", return_value=blocked):
            with pytest.raises(PublishBlocked, match="Phase 1"):
                assert_publishable("some_niche", platform="shorts")

    def test_guard_permits_shorts_when_profile_allows(self):
        from verticals.publish import assert_publishable
        assert_publishable(NICHE, platform="shorts")  # must not raise

    def test_long_form_is_never_blocked(self):
        # The gate is Shorts-specific; a Phase 1 niche must still ship its
        # weekly long-form.
        from verticals.publish import assert_publishable
        blocked = {"publishing": {"shorts_allowed": False, "phase": 1}}
        with patch("verticals.publish.load_niche", return_value=blocked):
            assert_publishable("some_niche", platform="longform")  # must not raise

    def test_env_override_can_force_shorts(self, monkeypatch):
        # YT_SHORTS_ALLOWED is the documented escape hatch.
        from verticals.publish import assert_publishable
        monkeypatch.setenv("YT_SHORTS_ALLOWED", "true")
        blocked = {"publishing": {"shorts_allowed": False, "phase": 1}}
        with patch("verticals.publish.load_niche", return_value=blocked):
            assert_publishable("some_niche", platform="shorts")  # must not raise


class TestTopicAlias:
    """--topic is an alias of --news.

    The original test built a throwaway ArgumentParser and asserted argparse's
    own aliasing behaviour, so it would have passed even if the CLI dropped the
    flag entirely. There is no build_parser() to call — main() constructs the
    parser inline — so these drive main() with a patched argv and a stubbed
    command function, which exercises the real parser without running anything.
    """

    def _parse(self, argv):
        from verticals import __main__ as cli
        with patch.object(sys, "argv", ["verticals", *argv]), \
             patch.object(cli, "CONFIG_FILE") as cfg, \
             patch.object(cli, "cmd_draft") as draft:
            cfg.exists.return_value = True   # don't trigger the setup wizard
            cli.main()
        return draft.call_args.args[0]

    def test_topic_is_accepted_by_the_real_cli(self):
        assert self._parse(["draft", "--topic", "a headline"]).news == "a headline"

    def test_news_still_works(self):
        assert self._parse(["draft", "--news", "a headline"]).news == "a headline"

    def test_score_requires_a_topic(self):
        from verticals import __main__ as cli
        with patch.object(sys, "argv", ["verticals", "score"]), \
             patch.object(cli, "CONFIG_FILE") as cfg:
            cfg.exists.return_value = True
            with pytest.raises(SystemExit):
                cli.main()
