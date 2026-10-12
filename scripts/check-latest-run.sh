#!/usr/bin/env bash
set -uo pipefail

REPO="hazalkoom/Job-seeker"
WORKFLOW="Job Hunter"

if ! gh auth status >/dev/null 2>&1; then
    echo "ERROR: GitHub CLI is not authenticated. Run: gh auth login"
    exit 1
fi

echo "Starting Job Hunter workflow..."

if ! output=$(gh workflow run "$WORKFLOW" -R "$REPO" --ref main 2>&1); then
    echo "$output"
    exit 1
fi

echo "$output"

RUN_ID=$(printf '%s\n' "$output" |
    grep -oE '/actions/runs/[0-9]+' |
    tail -1 |
    cut -d/ -f4)

if [[ -z "$RUN_ID" ]]; then
    echo "ERROR: Could not determine the new run ID."
    exit 1
fi

echo
echo "Watching run $RUN_ID..."
watch_status=0
gh run watch "$RUN_ID" -R "$REPO" --exit-status || watch_status=$?

echo
echo "========== RUN SUMMARY =========="

gh run view "$RUN_ID" -R "$REPO" \
    --json status,conclusion,url \
    --jq '"Status: \(.status)\nConclusion: \(.conclusion)\nURL: \(.url)"'

echo
echo "========== JOB HUNTER REPORT =========="

if ! gh run view "$RUN_ID" -R "$REPO" --log 2>&1 |
    grep -E '"newly_stored"|"confirmed_matches"|"telegram_messages_sent"|"job_alerts_sent"|"telegram_status_message_sent"|"source_errors"'; then
    echo "Report fields not found in logs. Inspect the run URL above."
fi

exit "$watch_status"
