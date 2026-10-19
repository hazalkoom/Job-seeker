#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 was not found. Install Python 3.11+ first." >&2
  exit 2
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit(f"ERROR: Python 3.11+ is required; found {sys.version.split()[0]}")
print(f"Using Python {sys.version.split()[0]}")
PY

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example. Edit it to configure Telegram and optional sources."
else
  echo "Kept existing .env unchanged."
fi

cat <<'EOF'

Setup complete.
Next:
  1. Edit .env and add your own credentials if you want Telegram/Google Jobs/email alerts.
  2. Activate the environment: source .venv/bin/activate
  3. Run tests: pytest -q
  4. Inspect candidates without database writes/notifications: python scripts/debug_candidates.py
  5. Run normal collection only when ready: python run_once.py
EOF
