"""Tests for verticals/notify.py — status file, alert log, toast, log pruning.

subprocess is always patched: toast() shells out to PowerShell, and a real
invocation would pop a desktop notification during a test run.
"""

import datetime
from unittest.mock import patch

import pytest

from verticals import notify


@pytest.fixture
def logs(tmp_path):
    """Point notify's module-level paths at a temp dir.

    The three constants are resolved at import time, so each has to be
    redirected individually — patching LOGS_DIR alone leaves STATUS_FILE and
    ALERTS_FILE pointing at the real ~/.verticals/logs.
    """
    with patch.object(notify, "LOGS_DIR", tmp_path), \
         patch.object(notify, "STATUS_FILE", tmp_path / "last_run_status.txt"), \
         patch.object(notify, "ALERTS_FILE", tmp_path / "ALERTS.md"):
        yield tmp_path


class TestRecordStatus:
    def test_writes_ok_state(self, logs):
        with patch.object(notify, "_now", return_value="2026-08-16 06:00:00"):
            notify.record_status("curious", ok=True, detail="12 topics")
        line = (logs / "last_run_status.txt").read_text(encoding="utf-8")
        assert line == "2026-08-16 06:00:00\tcurious\tOK\t12 topics\n"

    def test_writes_failed_state(self, logs):
        notify.record_status("curious", ok=False, detail="quota")
        assert "\tFAILED\tquota" in (logs / "last_run_status.txt").read_text(encoding="utf-8")

    def test_detail_is_optional(self, logs):
        notify.record_status("job", ok=True)
        assert (logs / "last_run_status.txt").read_text(encoding="utf-8").endswith("\tOK\t\n")

    def test_creates_missing_log_dir(self, tmp_path):
        nested = tmp_path / "deep" / "logs"
        with patch.object(notify, "LOGS_DIR", nested), \
             patch.object(notify, "STATUS_FILE", nested / "s.txt"):
            notify.record_status("job", ok=True)
        assert (nested / "s.txt").exists()

    def test_overwrites_previous_run(self, logs):
        notify.record_status("job", ok=False, detail="old")
        notify.record_status("job", ok=True, detail="new")
        body = (logs / "last_run_status.txt").read_text(encoding="utf-8")
        assert "old" not in body
        assert "new" in body


class TestToast:
    def test_invokes_powershell(self):
        with patch.object(notify.subprocess, "run") as run:
            notify.toast("Title", "Body")
        cmd = run.call_args.args[0]
        assert cmd[0] == "powershell"
        assert "-NonInteractive" in cmd
        assert "Body" in cmd[-1]

    def test_swallows_subprocess_failure(self):
        # Alerting must never be the reason a job dies.
        with patch.object(notify.subprocess, "run", side_effect=OSError("no shell")):
            notify.toast("t", "m")  # must not raise

    def test_truncates_and_escapes(self):
        with patch.object(notify.subprocess, "run") as run:
            notify.toast('T"' + "t" * 200, 'M"' + "m" * 500)
        script = run.call_args.args[0][-1]
        # Double quotes would terminate the PowerShell string early.
        assert 'T"' not in script
        assert "m" * 251 not in script

    def test_passes_timeout_and_does_not_check(self):
        with patch.object(notify.subprocess, "run") as run:
            notify.toast("t", "m")
        assert run.call_args.kwargs["timeout"] == 30
        assert run.call_args.kwargs["check"] is False


class TestAlert:
    def test_records_appends_and_toasts(self, logs):
        with patch.object(notify, "toast") as toast:
            notify.alert("curious", "Gemini quota exhausted")
        assert "FAILED" in (logs / "last_run_status.txt").read_text(encoding="utf-8")
        assert "Gemini quota exhausted" in (logs / "ALERTS.md").read_text(encoding="utf-8")
        toast.assert_called_once()
        assert "curious failed" in toast.call_args.args[0]

    def test_appends_rather_than_overwrites(self, logs):
        with patch.object(notify, "toast"):
            notify.alert("job", "first")
            notify.alert("job", "second")
        body = (logs / "ALERTS.md").read_text(encoding="utf-8")
        assert "first" in body and "second" in body
        assert body.count("- **") == 2


class TestReadStatus:
    def test_empty_when_absent(self, logs):
        assert notify.read_status() == ""

    def test_returns_stripped_contents(self, logs):
        notify.record_status("job", ok=True, detail="d")
        assert notify.read_status().endswith("OK\td")


class TestPruneLogs:
    def _aged(self, path, days):
        import os
        ts = (datetime.datetime.now() - datetime.timedelta(days=days)).timestamp()
        os.utime(path, (ts, ts))

    def test_zero_when_dir_missing(self, tmp_path):
        with patch.object(notify, "LOGS_DIR", tmp_path / "nope"):
            assert notify.prune_logs() == 0

    def test_removes_only_old_dated_logs(self, logs):
        old = logs / "pipeline_2026-01-01.log"
        new = logs / "pipeline_2026-08-15.log"
        old.write_text("x")
        new.write_text("x")
        self._aged(old, 100)
        self._aged(new, 1)
        assert notify.prune_logs(keep_days=45) == 1
        assert not old.exists()
        assert new.exists()

    def test_leaves_rolling_logs_and_alerts_alone(self, logs):
        rolling = logs / "daily.log"
        alerts = logs / "ALERTS.md"
        rolling.write_text("x")
        alerts.write_text("x")
        self._aged(rolling, 400)
        self._aged(alerts, 400)
        assert notify.prune_logs(keep_days=45) == 0
        assert rolling.exists()
        assert alerts.exists()

    def test_unlink_error_is_ignored(self, logs):
        stale = logs / "pipeline_old.log"
        stale.write_text("x")
        self._aged(stale, 100)
        with patch("pathlib.Path.unlink", side_effect=OSError("locked")):
            assert notify.prune_logs(keep_days=45) == 0
