#!/usr/bin/env bash
set -euo pipefail

# Disable only the local user-level scheduler; it does not change GitHub Actions.
if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl not found; no local timer was changed."
  exit 2
fi
if systemctl --user list-unit-files job-hunter-autopilot.timer --no-legend 2>/dev/null | grep -q 'job-hunter-autopilot.timer'; then
  systemctl --user disable --now job-hunter-autopilot.timer || true
fi
systemctl --user stop job-hunter-autopilot.service 2>/dev/null || true
systemctl --user --no-pager status job-hunter-autopilot.timer 2>&1 || true

echo
echo "Local Job Hunter timer was disabled/stopped where present. GitHub Actions is managed separately."
