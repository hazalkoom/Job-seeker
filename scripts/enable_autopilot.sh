#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
ENV_FILE="$ROOT/.env"
PROFILE="$ROOT/candidate_profile.json"
ANSWERS="$ROOT/application_answers.json"
DEFAULT_CV="$ROOT/private/Mohamed_Ahmed_CV.pdf"
VENV="$HOME/.venvs/job-hunter-autopilot"
UNIT_DIR="$HOME/.config/systemd/user"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: .env was not found in $ROOT" >&2
  exit 1
fi
if [[ ! -f "$PROFILE" || ! -f "$ANSWERS" ]]; then
  echo "ERROR: candidate_profile.json and application_answers.json must exist locally." >&2
  echo "They are private files and must not be committed." >&2
  exit 1
fi

# Ensure secrets and personal application material stay out of Git.
for pattern in '.env' 'candidate_profile.json' 'application_answers.json' 'private/' '.venv/' 'storage-state.json'; do
  grep -Fqx "$pattern" "$ROOT/.gitignore" 2>/dev/null || printf '\n%s\n' "$pattern" >> "$ROOT/.gitignore"
done

# Pick the configured resume path if present; otherwise use the project default.
RESUME_PATH="$(ROOT="$ROOT" python3 - <<'PY'
from pathlib import Path
import os
root = Path(os.environ["ROOT"])
value = ""
for raw in (root / ".env").read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line.startswith("AUTO_APPLY_RESUME_PATH="):
        value = line.split("=", 1)[1].strip().strip('"\'')
if not value:
    value = "private/Mohamed_Ahmed_CV.pdf"
p = Path(value).expanduser()
if not p.is_absolute():
    p = root / p
print(p)
PY
)"
if [[ ! -f "$RESUME_PATH" ]]; then
  echo "ERROR: resume file not found at the configured path." >&2
  echo "Set AUTO_APPLY_RESUME_PATH in .env to the actual local PDF path." >&2
  exit 1
fi

# Set/replace only the autonomous-application settings; preserve every credential.
python3 - "$ENV_FILE" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
values = {
    "AUTO_APPLY_ENABLED": "true",
    "AUTO_APPLY_MAX_PER_DAY": "10",
    "AUTO_APPLY_MIN_SCORE": "70",
    "AUTO_APPLY_DELAY_SECONDS": "8",
    "AUTO_APPLY_HEADLESS": "true",
    "AUTO_APPLY_TIMEOUT_SECONDS": "30",
}
lines = path.read_text(encoding="utf-8").splitlines()
seen = set()
resume_path_seen = False
out = []
for line in lines:
    stripped = line.strip()
    key = stripped.split("=", 1)[0].strip() if "=" in stripped and not stripped.startswith("#") else ""
    if key == "AUTO_APPLY_RESUME_PATH":
        resume_path_seen = True
    if key in values:
        if key not in seen:
            out.append(f"{key}={values[key]}")
            seen.add(key)
        continue
    out.append(line)
for key, value in values.items():
    if key not in seen:
        out.append(f"{key}={value}")
if not resume_path_seen:
    out.append("AUTO_APPLY_RESUME_PATH=private/Mohamed_Ahmed_CV.pdf")
path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
path.chmod(0o600)
PY

mkdir -p "$HOME/.venvs" "$UNIT_DIR"
if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install -r "$ROOT/requirements.txt"
"$VENV/bin/python" -m playwright install chromium
"$VENV/bin/python" -m compileall -q "$ROOT/app" "$ROOT/scripts" "$ROOT/tests"
"$VENV/bin/python" -m pytest -q "$ROOT/tests"
PYTHONPATH="$ROOT" "$VENV/bin/python" - <<'PY'
from app.application_profile import load_profile_bundle
bundle = load_profile_bundle()
if bundle.issues:
    raise SystemExit("Candidate profile/answer bank validation failed: " + "; ".join(bundle.issues))
print("Candidate profile and answer bank: valid (private values not printed)")
PY

cat > "$UNIT_DIR/job-hunter-autopilot.service" <<EOF
[Unit]
Description=Job Hunter autonomous search and application cycle
After=network-online.target
Wants=network-online.target
RequiresMountsFor=$ROOT

[Service]
Type=oneshot
WorkingDirectory=$ROOT
Environment=PYTHONUNBUFFERED=1
ExecStart=$VENV/bin/python $ROOT/run_once.py
TimeoutStartSec=45min
EOF

cat > "$UNIT_DIR/job-hunter-autopilot.timer" <<'EOF'
[Unit]
Description=Run Job Hunter autopilot four times per day

[Timer]
OnCalendar=*-*-* 03:17:00
OnCalendar=*-*-* 09:17:00
OnCalendar=*-*-* 15:17:00
OnCalendar=*-*-* 21:17:00
Persistent=true
RandomizedDelaySec=90
Unit=job-hunter-autopilot.service

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now job-hunter-autopilot.timer

echo
echo "Autopilot is enabled. Starting the first autonomous cycle now."
echo "Runs are also scheduled for 03:17, 09:17, 15:17, and 21:17 system-local time."
echo "Daily cap: 10 confirmed submissions. The first cycle may submit eligible applications."
systemctl --user start --no-block job-hunter-autopilot.service
systemctl --user --no-pager status job-hunter-autopilot.timer || true
echo
echo "Follow the current cycle with: journalctl --user -u job-hunter-autopilot.service -f"
