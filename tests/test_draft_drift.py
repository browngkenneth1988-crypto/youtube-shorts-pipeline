"""Topic drift — the draft must be about the topic that was asked for.

Two real failures prompted this. A "Parasitic zombie-ant fungus thrives in
mosses" topic came back as a script on pareidolia, and a Neptune topic as one on
why the brain makes up stories. Both parsed as valid JSON, so every existing
check passed, the draft was banked, and the queue marked the real topic
`drafted=yes` pointing at a script about something else. Nothing compared the
draft to the request.
"""

from unittest.mock import patch

import pytest

from verticals.draft import DraftDriftError, topic_drift


class TestTopicDrift:
    def test_the_real_pareidolia_failure_is_caught(self):
        drift = topic_drift(
            "Parasitic zombie-ant fungus thrives in mosses, too",
            {"script": "Your brain is doing something right now that you did not agree to. "
                       "You see a face in a cloud. This is called pareidolia.",
             "youtube_title": "Why Do You See Faces in Clouds?"},
        )
        assert drift is not None

    def test_the_real_neptune_failure_is_caught(self):
        drift = topic_drift(
            "Neptune May Have Once Witnessed a Lunar Massacre",
            {"script": "Your brain fills gaps with invented detail to keep a story coherent.",
             "youtube_title": "Why Does Your Brain Make Up Stories?"},
        )
        assert drift is not None

    def test_a_matching_draft_passes(self):
        assert topic_drift(
            "Parasitic zombie-ant fungus thrives in mosses, too",
            {"script": "A parasitic fungus hijacks ants, and now it turns out it thrives in mosses.",
             "youtube_title": "The Zombie-Ant Fungus Found a New Home"},
        ) is None

    def test_a_loose_paraphrase_still_passes(self):
        """The bar is one shared content word — this must not police phrasing."""
        assert topic_drift(
            "Why we get goosebumps",
            {"script": "Goosebumps are a leftover reflex from ancestors with far more hair.",
             "youtube_title": "Why Do We Get Goosebumps?"},
        ) is None

    def test_title_alone_is_enough_to_match(self):
        assert topic_drift(
            "Why time feels faster as you get older",
            {"script": "Something entirely unrelated.",
             "youtube_title": "Why Does Time Speed Up As You Get Older?"},
        ) is None

    def test_empty_topic_does_not_block(self):
        assert topic_drift("", {"script": "anything", "youtube_title": "x"}) is None

    def test_empty_draft_is_reported(self):
        assert topic_drift("zombie ant fungus", {"script": "", "youtube_title": ""}) is not None

    def test_stopwords_alone_do_not_count_as_a_match(self):
        """A draft sharing only filler words is not about the topic."""
        drift = topic_drift(
            "Parasitic zombie-ant fungus thrives in mosses",
            {"script": "This is about that thing which would have been there.",
             "youtube_title": "What Should You Know?"},
        )
        assert drift is not None


class TestGenerateDraftRaisesOnDrift:
    def _patched(self, payload):
        return patch("verticals.draft.call_llm", return_value=payload), \
               patch("verticals.draft.research_topic", return_value="research context")

    def test_generate_draft_raises_when_the_model_drifts(self):
        import json as _json
        payload = _json.dumps({
            "script": "You see a face in a cloud. This is called pareidolia.",
            "broll_prompts": ["a", "b", "c"],
            "youtube_title": "Why Do You See Faces in Clouds?",
            "youtube_description": "d", "youtube_tags": "t",
            "instagram_caption": "c", "tiktok_caption": "c", "thumbnail_prompt": "p",
        })
        llm, research = self._patched(payload)
        with llm, research:
            from verticals.draft import generate_draft
            with pytest.raises(DraftDriftError):
                generate_draft("Parasitic zombie-ant fungus thrives in mosses, too")

    def test_generate_draft_returns_when_on_topic(self):
        import json as _json
        payload = _json.dumps({
            "script": "The zombie-ant fungus also thrives in mosses.",
            "broll_prompts": ["a", "b", "c"],
            "youtube_title": "The Zombie-Ant Fungus in Mosses",
            "youtube_description": "d", "youtube_tags": "t",
            "instagram_caption": "c", "tiktok_caption": "c", "thumbnail_prompt": "p",
        })
        llm, research = self._patched(payload)
        with llm, research:
            from verticals.draft import generate_draft
            d = generate_draft("Parasitic zombie-ant fungus thrives in mosses, too")
        assert d["news"] == "Parasitic zombie-ant fungus thrives in mosses, too"
