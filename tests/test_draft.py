"""Tests for verticals/draft.py — draft generation with mocked LLM provider."""

import json
from unittest.mock import patch

from verticals.draft import generate_draft


class TestGenerateDraft:
    @patch("verticals.draft.research_topic")
    @patch("verticals.draft.call_llm")
    def test_basic_draft_generation(self, mock_llm, mock_research):
        mock_research.return_value = "Some research data about the topic."
        mock_llm.return_value = json.dumps({
            "script": "This is a test script about AI.",
            "broll_prompts": ["Prompt 1", "Prompt 2", "Prompt 3"],
            "youtube_title": "AI Revolution 2026",
            "youtube_description": "All about AI.",
            "youtube_tags": "ai,tech,2026",
            "instagram_caption": "AI is changing the world!",
            "thumbnail_prompt": "Futuristic AI image",
        })

        draft = generate_draft("AI is changing everything in 2026")

        assert draft["script"] == "This is a test script about AI."
        assert len(draft["broll_prompts"]) == 3
        assert draft["youtube_title"] == "AI Revolution 2026"
        assert draft["news"] == "AI is changing everything in 2026"
        assert draft["research"] == "Some research data about the topic."

    @patch("verticals.draft.research_topic")
    @patch("verticals.draft.call_llm")
    def test_handles_code_block_wrapper(self, mock_llm, mock_research):
        mock_research.return_value = "research"
        mock_llm.return_value = '```json\n{"script":"test","broll_prompts":["p1","p2","p3"],"youtube_title":"T","youtube_description":"D","youtube_tags":"t","instagram_caption":"C","thumbnail_prompt":"P"}\n```'

        draft = generate_draft("Test topic")
        assert draft["script"] == "test"

    @patch("verticals.draft.research_topic")
    @patch("verticals.draft.call_llm")
    def test_sanitizes_non_string_fields(self, mock_llm, mock_research):
        mock_research.return_value = "research"
        mock_llm.return_value = json.dumps({
            "script": 12345,  # non-string
            "broll_prompts": "not a list",  # non-list
            "youtube_title": "T",
            "youtube_description": "D",
            "youtube_tags": "t",
            "instagram_caption": "C",
            "thumbnail_prompt": "P",
        })

        draft = generate_draft("Test")
        assert isinstance(draft["script"], str)
        assert isinstance(draft["broll_prompts"], list)
        assert len(draft["broll_prompts"]) == 3  # fallback

    @patch("verticals.draft.research_topic")
    @patch("verticals.draft.call_llm")
    def test_includes_channel_context(self, mock_llm, mock_research):
        mock_research.return_value = "research"
        mock_llm.return_value = json.dumps({
            "script": "s", "broll_prompts": ["p1", "p2", "p3"],
            "youtube_title": "T", "youtube_description": "D",
            "youtube_tags": "t", "instagram_caption": "C",
            "thumbnail_prompt": "P",
        })

        generate_draft("Test", channel_context="esports news channel")
        # Verify the channel context was passed to the LLM
        call_args = mock_llm.call_args[0][0]
        assert "esports news channel" in call_args

    @patch("verticals.draft.research_topic")
    @patch("verticals.draft.call_llm")
    def test_truncates_broll_prompts(self, mock_llm, mock_research):
        mock_research.return_value = "research"
        mock_llm.return_value = json.dumps({
            "script": "s",
            "broll_prompts": ["p1", "p2", "p3", "p4", "p5"],  # too many
            "youtube_title": "T", "youtube_description": "D",
            "youtube_tags": "t", "instagram_caption": "C",
            "thumbnail_prompt": "P",
        })

        draft = generate_draft("Test")
        assert len(draft["broll_prompts"]) == 3  # truncated to 3


VALID = {
    "script": "s", "broll_prompts": ["a", "b", "c"],
    "youtube_title": "T", "youtube_description": "D",
    "youtube_tags": "t", "instagram_caption": "C", "thumbnail_prompt": "P",
}


class TestMalformedJsonRecovery:
    """The LLM's JSON is treated as untrusted; every degradation path is a
    documented behaviour, not an accident. Nothing here should raise."""

    @patch("verticals.draft.research_topic", return_value="research")
    @patch("verticals.draft.call_llm")
    def test_missing_opening_brace_is_repaired(self, llm, _research):
        # Gemini sometimes starts at the first key instead of the brace.
        llm.return_value = '"script": "hello", "youtube_title": "T"'
        assert generate_draft("Test")["script"] == "hello"

    @patch("verticals.draft.research_topic", return_value="research")
    @patch("verticals.draft.call_llm")
    def test_missing_both_braces_is_repaired(self, llm, _research):
        llm.return_value = '"script": "hello"'
        assert generate_draft("Test")["script"] == "hello"

    @patch("verticals.draft.research_topic", return_value="research")
    @patch("verticals.draft.call_llm")
    def test_raw_newlines_inside_strings_are_escaped(self, llm, _research):
        # Literal newlines inside a JSON string are invalid JSON.
        llm.return_value = '{"script": "line one\nline two", "youtube_title": "T"}'
        assert "line one" in generate_draft("Test")["script"]

    @patch("verticals.draft.research_topic", return_value="research")
    @patch("verticals.draft.call_llm")
    def test_carriage_returns_are_escaped(self, llm, _research):
        llm.return_value = '{"script": "line one\r\nline two", "youtube_title": "T"}'
        assert "line one" in generate_draft("Test")["script"]

    @patch("verticals.draft.research_topic", return_value="research")
    @patch("verticals.draft.call_llm")
    def test_json_extracted_from_surrounding_prose(self, llm, _research):
        llm.return_value = 'Sure, here you go:\n{"script": "inner"}\nHope that helps!'
        assert generate_draft("Test")["script"] == "inner"

    @patch("verticals.draft.research_topic", return_value="research")
    @patch("verticals.draft.call_llm")
    def test_balanced_brace_scan_stops_at_outermost_pair(self, llm, _research):
        llm.return_value = 'prose {"script": "s", "meta": {"nested": 1}} trailing'
        assert generate_draft("Test")["script"] == "s"

    @patch("verticals.draft.research_topic", return_value="research")
    @patch("verticals.draft.call_llm")
    def test_no_json_at_all_falls_back(self, llm, _research):
        llm.return_value = "I am unable to help with that request."
        draft = generate_draft("A headline")
        assert draft["script"]
        assert len(draft["broll_prompts"]) == 3

    @patch("verticals.draft.research_topic", return_value="research")
    @patch("verticals.draft.call_llm")
    def test_irreparable_json_falls_back(self, llm, _research):
        llm.return_value = '{"script": "unterminated, "broll_prompts": [}'
        draft = generate_draft("A headline")
        assert draft["script"]
        assert isinstance(draft["broll_prompts"], list)


class TestNicheDrivenPrompt:
    """Each optional profile block should reach the prompt when present."""

    def _prompt_for(self, profile, **kw):
        with patch("verticals.draft.research_topic", return_value="research"), \
             patch("verticals.draft.load_niche", return_value=profile), \
             patch("verticals.draft.call_llm", return_value=json.dumps(VALID)) as llm:
            generate_draft("Test", **kw)
        return llm.call_args[0][0]

    def test_thumbnail_guidance_included(self):
        p = self._prompt_for({
            "thumbnail": {"style": "bold flat art", "guidelines": ["big face", "3 words", "x", "y"]}
        })
        assert "THUMBNAIL GUIDANCE" in p
        assert "bold flat art" in p
        assert "big face; 3 words; x" in p  # capped at 3
        assert "y" not in p.split("THUMBNAIL GUIDANCE")[1].split("\n")[2]

    def test_thumbnail_block_absent_when_empty(self):
        assert "THUMBNAIL GUIDANCE" not in self._prompt_for({})

    def test_children_quotes_sampled_into_prompt(self):
        # Zero-padded so no quote is a substring of another; "quote 1" would
        # otherwise also match inside "quote 10" and inflate the count.
        quotes = [f"quote-{i:02d}-end" for i in range(12)]
        p = self._prompt_for({
            "children_quotes": quotes,
            "script": {"quote_instruction": "Say it gently."},
        })
        assert "CHILDREN'S QUOTES" in p
        assert sum(q in p for q in quotes) == 5  # samples exactly 5
        assert "Say it gently." in p

    def test_fewer_quotes_than_sample_size(self):
        p = self._prompt_for({"children_quotes": ["only one"]})
        assert "only one" in p

    def test_channel_branding_included(self):
        p = self._prompt_for({
            "channel": {
                "name": "Life With Otto",
                "website": "https://example.com",
                "youtube_description_footer": "  Subscribe!  ",
                "tags": [f"t{i}" for i in range(15)],
            }
        })
        assert "CHANNEL BRANDING" in p
        assert "Life With Otto" in p
        assert "https://example.com" in p
        assert "Subscribe!" in p
        assert "t0,t1" in p
        assert "t10" not in p  # capped at 10

    def test_branding_block_absent_when_empty(self):
        assert "CHANNEL BRANDING" not in self._prompt_for({})

    def test_channel_context_reaches_prompt(self):
        p = self._prompt_for({}, channel_context="esports news")
        assert "esports news" in p
