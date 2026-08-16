"""Tests for verticals/score.py — the topic scoring gate.

call_llm is always patched; nothing here reaches a provider.
"""

import json
from unittest.mock import patch

import pytest

from verticals import score
from verticals.score import TopicRejected


def _cfg(**over):
    cfg = {
        "enabled": True,
        "threshold": 40,
        "max_total": 50,
        "categories": [
            {"id": "curiosity", "max": 10, "question": "Does it hook?"},
            {"id": "clarity", "max": 10, "question": "Can it be explained simply?"},
        ],
    }
    cfg.update(over)
    return cfg


def _profile(**over):
    p = {"display_name": "Curious Classroom", "scoring": _cfg()}
    p.update(over)
    return p


class TestScoringEnabled:
    def test_true_when_enabled(self):
        assert score.scoring_enabled({"scoring": {"enabled": True}}) is True

    def test_false_when_absent(self):
        assert score.scoring_enabled({}) is False

    def test_false_when_scoring_is_none(self):
        # `scoring:` present but empty parses to None, not {}.
        assert score.scoring_enabled({"scoring": None}) is False

    def test_false_when_disabled(self):
        assert score.scoring_enabled({"scoring": {"enabled": False}}) is False


class TestExtractJson:
    def test_plain_object(self):
        assert score._extract_json('{"a": 1}') == {"a": 1}

    def test_fenced_json(self):
        assert score._extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_unlabelled_fence(self):
        assert score._extract_json('```\n{"a": 1}\n```') == {"a": 1}

    def test_strips_surrounding_prose(self):
        assert score._extract_json('Sure!\n{"a": 1}\nHope that helps.') == {"a": 1}

    def test_raises_on_garbage(self):
        with pytest.raises(json.JSONDecodeError):
            score._extract_json("no json here")


class TestBuildPrompt:
    def test_includes_topic_and_categories(self):
        p = score._build_prompt("Why is the sky blue", _cfg(), _profile())
        assert "Why is the sky blue" in p
        assert "curiosity (max 10): Does it hook?" in p
        assert "Threshold: 40 of 50" in p

    def test_uses_channel_block_when_present(self):
        prof = _profile(channel={"name": "CC", "promise": "Big ideas", "audience": "curious adults"})
        p = score._build_prompt("t", _cfg(), prof)
        assert '"CC"' in p
        assert "Big ideas" in p
        assert "curious adults" in p

    def test_falls_back_to_display_name(self):
        assert '"Curious Classroom"' in score._build_prompt("t", _cfg(), _profile())

    def test_optional_sections_omitted_when_empty(self):
        p = score._build_prompt("t", _cfg(), _profile())
        for absent in ("CONTENT PILLARS", "STRENGTHENING FACTORS",
                       "AUTOMATIC REJECTION", "CALIBRATION"):
            assert absent not in p

    def test_pillars_bonuses_and_hard_rejects_render(self):
        cfg = _cfg(pillars=["space"], bonuses=["visual"], hard_rejects=["needs a face"])
        p = score._build_prompt("t", cfg, _profile())
        assert "CONTENT PILLARS" in p and "- space" in p
        assert "STRENGTHENING FACTORS" in p and "- visual" in p
        assert "AUTOMATIC REJECTION" in p and "- needs a face" in p

    def test_calibration_examples_render(self):
        cfg = _cfg(
            calibration_approve=["Good one"],
            calibration_reject=[{"weak": "Bad one", "reframe": "Better one"}],
        )
        p = score._build_prompt("t", cfg, _profile())
        assert "Good one" in p
        assert 'WEAK: "Bad one"  ->  STRONG: "Better one"' in p

    def test_max_total_derived_from_categories(self):
        cfg = _cfg(categories=[{"id": "a", "max": 7}, {"id": "b", "max": 3}])
        cfg.pop("max_total")
        assert "Threshold: 40 of 10" in score._build_prompt("t", cfg, _profile())


class TestScoreTopic:
    def _run(self, payload, niche_profile=None, **kw):
        with patch("verticals.score.load_niche", return_value=niche_profile or _profile()), \
             patch("verticals.score.call_llm", return_value=json.dumps(payload)):
            return score.score_topic("a topic", niche="curious", **kw)

    def test_returns_none_for_ungated_niche(self):
        with patch("verticals.score.load_niche", return_value={}):
            assert score.score_topic("t", niche="general") is None

    def test_approves_at_or_above_threshold(self):
        r = self._run({"scores": {"curiosity": 20, "clarity": 20}, "total": 40})
        assert r["verdict"] == "APPROVE"
        assert r["total"] == 40

    def test_rejects_below_threshold(self):
        r = self._run({"scores": {"curiosity": 10, "clarity": 10}, "total": 20})
        assert r["verdict"] == "REJECT"

    def test_verdict_recomputed_not_trusted_from_model(self):
        # The model claiming APPROVE on a failing total must not win.
        r = self._run({"scores": {}, "total": 5, "verdict": "APPROVE"})
        assert r["verdict"] == "REJECT"

    def test_total_summed_when_model_omits_it(self):
        r = self._run({"scores": {"curiosity": 21, "clarity": 20}})
        assert r["total"] == 41
        assert r["verdict"] == "APPROVE"

    def test_non_numeric_scores_ignored_when_summing(self):
        r = self._run({"scores": {"curiosity": 20, "clarity": "n/a"}})
        assert r["total"] == 20

    def test_float_total_coerced_to_int(self):
        r = self._run({"scores": {}, "total": 41.7})
        assert r["total"] == 41

    def test_carries_topic_and_niche_through(self):
        r = self._run({"scores": {}, "total": 45})
        assert r["topic"] == "a topic"
        assert r["niche"] == "curious"
        assert r["threshold"] == 40
        assert r["max_total"] == 50

    def test_json_mode_requested(self):
        with patch("verticals.score.load_niche", return_value=_profile()), \
             patch("verticals.score.call_llm", return_value='{"total": 45}') as llm:
            score.score_topic("t", niche="curious", provider="gemini")
        assert llm.call_args.kwargs["json_mode"] is True
        assert llm.call_args.kwargs["provider"] == "gemini"


class TestScoreTopicFailure:
    """A scoring outage must never read as approval."""

    def test_llm_failure_returns_error_verdict(self, tmp_path):
        with patch("verticals.score.load_niche", return_value=_profile()), \
             patch("verticals.score.call_llm", side_effect=RuntimeError("quota")), \
             patch("verticals.config.LOGS_DIR", tmp_path):
            r = score.score_topic("t", niche="curious")
        assert r["verdict"] == "ERROR"
        assert r["total"] == 0
        assert "quota" in r["summary"]

    def test_unparseable_response_returns_error_verdict(self, tmp_path):
        with patch("verticals.score.load_niche", return_value=_profile()), \
             patch("verticals.score.call_llm", return_value="not json at all"), \
             patch("verticals.config.LOGS_DIR", tmp_path):
            r = score.score_topic("t", niche="curious")
        assert r["verdict"] == "ERROR"

    def test_raw_response_dumped_for_diagnosis(self, tmp_path):
        with patch("verticals.score.load_niche", return_value=_profile()), \
             patch("verticals.score.call_llm", return_value="I refuse to emit JSON"), \
             patch("verticals.config.LOGS_DIR", tmp_path):
            score.score_topic("the topic", niche="curious")
        dump = (tmp_path / "last_llm_failure.txt").read_text(encoding="utf-8")
        assert "I refuse to emit JSON" in dump
        assert "the topic" in dump

    def test_dump_failure_does_not_mask_error_verdict(self):
        with patch("verticals.score.load_niche", return_value=_profile()), \
             patch("verticals.score.call_llm", side_effect=RuntimeError("boom")), \
             patch("verticals.config.LOGS_DIR") as logs:
            logs.mkdir.side_effect = OSError("read-only")
            r = score.score_topic("t", niche="curious")
        assert r["verdict"] == "ERROR"


class TestFormatResult:
    def test_renders_scores_and_verdict(self):
        out = score.format_result({
            "topic": "T", "scores": {"curiosity": 9}, "total": 45,
            "max_total": 50, "threshold": 40, "verdict": "APPROVE",
        })
        assert "Topic: T" in out
        assert "curiosity" in out
        assert "45/50" in out
        assert "APPROVE" in out

    def test_titles_only_on_approve(self):
        base = {"total": 45, "verdict": "APPROVE", "titles": ["A"], "reframes": ["R"]}
        assert "Working titles" in score.format_result(base)
        assert "Stronger angles" not in score.format_result(base)

    def test_reframes_only_on_reject(self):
        base = {"total": 5, "verdict": "REJECT", "titles": ["A"], "reframes": ["R"]}
        assert "Stronger angles" in score.format_result(base)
        assert "Working titles" not in score.format_result(base)

    def test_pillars_and_summary_optional(self):
        assert "PILLARS" not in score.format_result({"total": 1, "verdict": "REJECT"})
        out = score.format_result({"total": 1, "verdict": "REJECT",
                                   "pillars": ["space"], "summary": "too niche"})
        assert "space" in out and "too niche" in out

    def test_tolerates_empty_result(self):
        assert isinstance(score.format_result({}), str)


class TestGateTopic:
    def test_none_for_ungated_niche(self, capsys):
        with patch("verticals.score.score_topic", return_value=None):
            assert score.gate_topic("t", "general") is None

    def test_returns_result_on_approve(self, capsys):
        result = {"verdict": "APPROVE", "total": 45, "max_total": 50}
        with patch("verticals.score.score_topic", return_value=result):
            assert score.gate_topic("t", "curious") == result

    def test_raises_on_reject(self, capsys):
        result = {"verdict": "REJECT", "total": 12, "max_total": 50, "summary": "weak"}
        with patch("verticals.score.score_topic", return_value=result):
            with pytest.raises(TopicRejected) as exc:
                score.gate_topic("t", "curious")
        assert exc.value.result is result
        assert "weak" in str(exc.value)

    def test_force_overrides_reject(self, capsys):
        result = {"verdict": "REJECT", "total": 12, "max_total": 50}
        with patch("verticals.score.score_topic", return_value=result):
            assert score.gate_topic("t", "curious", force=True) == result

    def test_error_verdict_is_not_treated_as_approval(self, capsys):
        # A scoring outage must block, not pass through.
        result = {"verdict": "ERROR", "total": 0, "max_total": 50, "summary": "call failed"}
        with patch("verticals.score.score_topic", return_value=result):
            with pytest.raises(TopicRejected):
                score.gate_topic("t", "curious")

    def test_prints_the_scorecard(self, capsys):
        result = {"verdict": "APPROVE", "total": 45, "max_total": 50, "topic": "Sky"}
        with patch("verticals.score.score_topic", return_value=result):
            score.gate_topic("Sky", "curious")
        assert "Sky" in capsys.readouterr().out
