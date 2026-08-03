"""Tests for verticals/niche.py — profile loading and stage-specific extractors."""

import pytest

from verticals import niche


@pytest.fixture(autouse=True)
def clear_niche_cache():
    """load_niche memoizes into a module-level cache; reset it per test."""
    niche._cache.clear()
    yield
    niche._cache.clear()


class TestLoadNiche:
    def test_loads_real_general_profile(self):
        profile = niche.load_niche("general")
        assert profile["name"] == "general"
        assert "script" in profile

    def test_name_is_normalized(self):
        # Whitespace/case are stripped; "General" resolves to general.yaml.
        profile = niche.load_niche("  General  ")
        assert profile["name"] == "general"

    def test_none_defaults_to_general(self):
        profile = niche.load_niche(None)
        assert profile["name"] == "general"

    def test_result_is_cached(self):
        first = niche.load_niche("general")
        assert "general" in niche._cache
        second = niche.load_niche("general")
        assert first is second  # same object returned from cache

    def test_unknown_niche_falls_back_to_general(self):
        profile = niche.load_niche("does-not-exist-xyz")
        # Falls back to the general profile rather than erroring.
        assert profile["name"] == "general"

    def test_missing_general_returns_minimal(self, tmp_path, monkeypatch):
        # Point NICHES_DIR at an empty dir so even general.yaml is missing.
        monkeypatch.setattr(niche, "NICHES_DIR", tmp_path)
        profile = niche.load_niche("general")
        assert profile["name"] == "general"
        assert profile["display_name"] == "General"
        assert profile["script"]["tone"]

    def test_broken_yaml_returns_minimal(self, tmp_path, monkeypatch):
        bad = tmp_path / "broken.yaml"
        bad.write_text("script: [unterminated\n  :::junk")
        monkeypatch.setattr(niche, "NICHES_DIR", tmp_path)
        profile = niche.load_niche("broken")
        assert profile["name"] == "broken"
        assert "script" in profile  # minimal profile shape


class TestMinimalProfile:
    def test_shape(self):
        p = niche._minimal_profile("gaming")
        assert p["name"] == "gaming"
        assert p["display_name"] == "Gaming"
        for key in ("script", "visuals", "voice", "captions", "music", "thumbnail", "discovery"):
            assert key in p


class TestGetScriptContext:
    def test_empty_when_no_script(self):
        assert niche.get_script_context({}) == ""

    def test_includes_tone_and_word_count(self):
        profile = {
            "display_name": "Tech",
            "script": {"tone": "punchy", "word_count": "150 to 180"},
        }
        ctx = niche.get_script_context(profile)
        assert "NICHE: Tech" in ctx
        assert "TONE: punchy" in ctx
        assert "TARGET WORD COUNT: 150 to 180" in ctx

    def test_renders_hooks_and_ctas_and_forbidden(self):
        profile = {
            "name": "x",
            "script": {
                "hooks": [{"id": "h1", "template": "Hook one", "when": "always"}],
                "cta_variants": ["Follow for more."],
                "forbidden_phrases": ["smash that bell"],
            },
        }
        ctx = niche.get_script_context(profile)
        assert "HOOK PATTERNS" in ctx
        assert 'h1: "Hook one"' in ctx
        assert "use when: always" in ctx
        assert "CTA OPTIONS (pick one): Follow for more." in ctx
        assert "NEVER USE: smash that bell" in ctx

    def test_renders_structure(self):
        profile = {
            "name": "x",
            "script": {"structure": {"opening": "Hook fast", "closing": "CTA"}},
        }
        ctx = niche.get_script_context(profile)
        assert "SCRIPT STRUCTURE:" in ctx
        assert "Opening: Hook fast" in ctx
        assert "Closing: CTA" in ctx


class TestVisualExtractors:
    def test_get_visual_context(self):
        profile = {"visuals": {"style": "cinematic", "mood": "tense"}}
        assert niche.get_visual_context(profile) == {"style": "cinematic", "mood": "tense"}

    def test_get_visual_context_empty(self):
        assert niche.get_visual_context({}) == {}

    def test_prompt_suffix_from_profile(self):
        profile = {"visuals": {"prompt_suffix": "neon, 4k"}}
        assert niche.get_visual_prompt_suffix(profile) == "neon, 4k"

    def test_prompt_suffix_default(self):
        # Falls back to a sensible default when not configured.
        assert "photorealistic" in niche.get_visual_prompt_suffix({})

    def test_get_visual_subjects(self):
        profile = {"visuals": {"subjects": {"prefer": ["cars"], "avoid": ["blur"]}}}
        subjects = niche.get_visual_subjects(profile)
        assert subjects == {"prefer": ["cars"], "avoid": ["blur"]}

    def test_get_visual_subjects_defaults_empty(self):
        subjects = niche.get_visual_subjects({})
        assert subjects == {"prefer": [], "avoid": []}


class TestVoiceConfig:
    def test_dict_provider_voices_selects_lang(self):
        profile = {
            "voice": {
                "pace": "fast",
                "suggested_voices": {"edge_tts": {"en": "en-US-Guy", "es": "es-ES-Alvaro"}},
            }
        }
        cfg = niche.get_voice_config(profile, provider="edge_tts", lang="es")
        assert cfg["voice_id"] == "es-ES-Alvaro"
        assert cfg["pace"] == "fast"

    def test_dict_provider_voices_falls_back_to_en(self):
        profile = {"voice": {"suggested_voices": {"edge_tts": {"en": "en-US-Guy"}}}}
        cfg = niche.get_voice_config(profile, provider="edge_tts", lang="fr")
        assert cfg["voice_id"] == "en-US-Guy"

    def test_string_provider_voice(self):
        profile = {"voice": {"suggested_voices": {"say": "Daniel"}}}
        cfg = niche.get_voice_config(profile, provider="say")
        assert cfg["voice_id"] == "Daniel"

    def test_elevenlabs_settings(self):
        profile = {
            "voice": {
                "suggested_voices": {
                    "elevenlabs": {"voice_id": "abc123", "settings": {"stability": 0.5}}
                }
            }
        }
        cfg = niche.get_voice_config(profile, provider="elevenlabs")
        assert cfg["voice_id"] == "abc123"
        assert cfg["settings"] == {"stability": 0.5}

    def test_missing_voice_returns_blanks(self):
        cfg = niche.get_voice_config({})
        assert cfg["pace"] == ""
        assert "voice_id" not in cfg or cfg["voice_id"] == ""


class TestConfigDefaults:
    def test_caption_defaults_merged(self):
        cfg = niche.get_caption_config({})
        assert cfg["highlight_color"] == "#FFFF00"
        assert cfg["words_per_group"] == 4

    def test_caption_overrides(self):
        cfg = niche.get_caption_config({"captions": {"highlight_color": "#00FF00"}})
        assert cfg["highlight_color"] == "#00FF00"
        assert cfg["font_family"] == "Arial"  # default preserved

    def test_music_defaults_merged(self):
        cfg = niche.get_music_config({})
        assert cfg["energy"] == "medium"
        assert cfg["duck_volume_speech"] == 0.12

    def test_music_overrides(self):
        cfg = niche.get_music_config({"music": {"energy": "high"}})
        assert cfg["energy"] == "high"
        assert cfg["duck_volume_gap"] == 0.25  # default preserved

    def test_thumbnail_and_discovery_passthrough(self):
        assert niche.get_thumbnail_config({"thumbnail": {"style": "bold"}}) == {"style": "bold"}
        assert niche.get_discovery_config({"discovery": {"sources": ["rss"]}}) == {"sources": ["rss"]}
        assert niche.get_thumbnail_config({}) == {}


class TestListNiches:
    def test_lists_yaml_files_sorted(self):
        names = niche.list_niches()
        assert "general" in names
        assert names == sorted(names)
        # There are real profiles shipped in the repo.
        assert "gaming" in names

    def test_missing_dir_returns_general(self, tmp_path, monkeypatch):
        monkeypatch.setattr(niche, "NICHES_DIR", tmp_path / "nope")
        assert niche.list_niches() == ["general"]

    def test_appends_general_if_absent(self, tmp_path, monkeypatch):
        (tmp_path / "custom.yaml").write_text("name: custom")
        monkeypatch.setattr(niche, "NICHES_DIR", tmp_path)
        names = niche.list_niches()
        assert "general" in names
        assert "custom" in names
