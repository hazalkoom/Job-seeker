#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f "app/sources/__init__.py" ]]; then
  echo "Run this from the Job Hunter project root (the folder containing app/ and run_once.py)." >&2
  exit 2
fi

PYTHON_BIN="${PYTHON:-python}"
exec "$PYTHON_BIN" scripts/collect_job_hunter_debug.py "$@"
