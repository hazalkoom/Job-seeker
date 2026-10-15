#!/usr/bin/env bash
set -euo pipefail

# Resolve the project root from this script's location, even if invoked elsewhere.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

if [[ ! -f "${PROJECT_ROOT}/app/sources/__init__.py" ]]; then
  echo "Could not identify project root from ${SCRIPT_DIR}; expected app/sources/__init__.py." >&2
  exit 2
fi

PYTHON_BIN="${PYTHON:-python}"
exec "${PYTHON_BIN}" "${SCRIPT_DIR}/collect_job_hunter_debug.py" --root "${PROJECT_ROOT}" "$@"
