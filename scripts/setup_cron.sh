#!/bin/bash
# ─────────────────────────────────────────────────────
# Setup daily cron job for Otto YouTube Shorts pipeline
# ─────────────────────────────────────────────────────
#
# Usage:
#   chmod +x scripts/setup_cron.sh
#   ./scripts/setup_cron.sh
#
# This installs a cron job that runs daily at 6:00 AM (local time).
# Edit CRON_HOUR and CRON_MIN below to change the schedule.
#
# To remove: crontab -l | grep -v 'daily_shorts.py' | crontab -

set -e

CRON_HOUR="${1:-6}"
CRON_MIN="${2:-0}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON="$(which python3 || which python)"
LOG_DIR="$HOME/.verticals/logs"

mkdir -p "$LOG_DIR"

# Build cron line
CRON_CMD="$CRON_MIN $CRON_HOUR * * * cd $PROJECT_DIR && $PYTHON scripts/daily_shorts.py --niche pets --voice edge >> $LOG_DIR/cron.log 2>&1"

# Check if already installed
if crontab -l 2>/dev/null | grep -q "daily_shorts.py"; then
    echo "Cron job already exists. Current schedule:"
    crontab -l | grep "daily_shorts.py"
    echo ""
    read -p "Replace with new schedule ($CRON_HOUR:$(printf '%02d' $CRON_MIN))? [y/N]: " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        echo "Keeping existing schedule."
        exit 0
    fi
    # Remove old entry
    crontab -l 2>/dev/null | grep -v "daily_shorts.py" | crontab -
fi

# Install new cron job
(crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -

echo ""
echo "  Cron job installed!"
echo ""
echo "  Schedule: Daily at $(printf '%02d:%02d' $CRON_HOUR $CRON_MIN)"
echo "  Command:  cd $PROJECT_DIR && $PYTHON scripts/daily_shorts.py --niche pets"
echo "  Logs:     $LOG_DIR/cron.log"
echo ""
echo "  Verify with: crontab -l"
echo "  Remove with: crontab -l | grep -v 'daily_shorts.py' | crontab -"
echo ""
echo "  To change the time, run:"
echo "    ./scripts/setup_cron.sh <HOUR> <MINUTE>"
echo "    Example: ./scripts/setup_cron.sh 9 30  # 9:30 AM"
echo ""
