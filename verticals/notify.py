"""Failure alerts for unattended runs.

The scheduled jobs write to a log nobody reads. A run could fail every morning
for a week and look healthy from the outside — Task Scheduler reports success
as long as the .bat exits 0, and the .bat exits 0 as long as Python does.

So every unattended entry point records its outcome in one place and raises a
desktop notification when something breaks. No dependencies: the toast goes
through PowerShell, which is always present on this machine.
"""

import datetime
import subprocess

from .config import LOGS_DIR

STATUS_FILE = LOGS_DIR / "last_run_status.txt"
ALERTS_FILE = LOGS_DIR / "ALERTS.md"


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def record_status(job: str, ok: bool, detail: str = ""):
    """Write the outcome of a scheduled job where healthcheck can find it."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    state = "OK" if ok else "FAILED"
    STATUS_FILE.write_text(
        f"{_now()}\t{job}\t{state}\t{detail}\n", encoding="utf-8"
    )


def toast(title: str, message: str):
    """Raise a Windows notification. Never raises — alerting must not crash a job."""
    # Truncated because the toast API silently drops overlong strings.
    message = message.replace('"', "'")[:250]
    title = title.replace('"', "'")[:60]
    script = (
        '[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications,'
        ' ContentType = WindowsRuntime] > $null;'
        '$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(1);'
        f'$t.GetElementsByTagName("text").Item(0).AppendChild($t.CreateTextNode("{title}")) > $null;'
        f'$t.GetElementsByTagName("text").Item(1).AppendChild($t.CreateTextNode("{message}")) > $null;'
        '[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('
        '"Verticals Pipeline").Show($t);'
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=30, check=False,
        )
    except Exception:
        pass


def alert(job: str, detail: str):
    """Record a failure, append it to the alert log, and notify the desktop."""
    record_status(job, ok=False, detail=detail)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(ALERTS_FILE, "a", encoding="utf-8") as f:
        f.write(f"- **{_now()}** `{job}` — {detail}\n")
    toast(f"{job} failed", detail)


def read_status() -> str:
    """Last recorded outcome, for healthcheck to display."""
    if not STATUS_FILE.exists():
        return ""
    return STATUS_FILE.read_text(encoding="utf-8").strip()


def prune_logs(keep_days: int = 45):
    """Delete dated pipeline logs older than keep_days.

    A daily job writes a log a day forever. Nothing ever removed them, so the
    directory had four months of runs in it. Only the dated per-run logs are
    pruned — the rolling logs and ALERTS.md are left alone.
    """
    if not LOGS_DIR.exists():
        return 0
    cutoff = datetime.datetime.now() - datetime.timedelta(days=keep_days)
    removed = 0
    for path in LOGS_DIR.glob("pipeline_*.log"):
        try:
            if datetime.datetime.fromtimestamp(path.stat().st_mtime) < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            pass
    return removed
