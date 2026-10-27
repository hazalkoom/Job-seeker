#!/usr/bin/env bash
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "Run this from inside the Job Hunter Git repository." >&2
  exit 1
}
cd "$ROOT"
python scripts/collect_job_hunter_diagnostics.py "$@"
