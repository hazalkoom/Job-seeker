#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "Run this from inside your Job Hunter git repository." >&2
  exit 1
}
cd "$ROOT"

for bin in gpg gh openssl; do
  command -v "$bin" >/dev/null 2>&1 || {
    echo "Missing required tool: $bin" >&2
    exit 1
  }
done

gh auth status >/dev/null
REPO="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"
if [[ -z "$REPO" ]]; then
  echo "Could not determine the GitHub repository from this checkout." >&2
  exit 1
fi

PROFILE="$ROOT/candidate_profile.json"
ANSWERS="$ROOT/application_answers.json"
RESUME="$ROOT/private/Mohamed_Ahmed-general.pdf"
for file in "$PROFILE" "$ANSWERS" "$RESUME"; do
  if [[ ! -s "$file" ]]; then
    echo "Required private file is missing or empty: $file" >&2
    exit 1
  fi
  if git ls-files --error-unmatch "${file#"$ROOT"/}" >/dev/null 2>&1; then
    echo "SAFETY STOP: plaintext private file is already tracked by git: ${file#"$ROOT"/}" >&2
    echo "Remove it from tracking and review repository history before continuing." >&2
    exit 1
  fi
done

# Ensure the GitHub workflow knows that these paths are private; never print their contents.
for pattern in '.env' 'candidate_profile.json' 'application_answers.json' 'private/' '.venv/' 'storage-state.json'; do
  grep -Fqx "$pattern" .gitignore 2>/dev/null || printf '\n%s\n' "$pattern" >> .gitignore
done

PASS_DIR="$HOME/.config/job-hunter"
PASS_FILE="$PASS_DIR/github-autopilot-passphrase"
mkdir -p "$PASS_DIR"
chmod 700 "$PASS_DIR"
if [[ ! -s "$PASS_FILE" ]]; then
  (umask 077; openssl rand -hex 48 > "$PASS_FILE")
fi
chmod 600 "$PASS_FILE"

mkdir -p private
encrypt_file() {
  local source="$1" dest="$2"
  gpg --batch --yes --quiet --pinentry-mode loopback \
    --passphrase-file "$PASS_FILE" --symmetric --cipher-algo AES256 \
    --s2k-digest-algo SHA512 --output "$dest" "$source"
  local testfile
  testfile="$(mktemp)"
  gpg --batch --yes --quiet --pinentry-mode loopback \
    --passphrase-file "$PASS_FILE" --output "$testfile" --decrypt "$dest"
  cmp -s "$source" "$testfile"
  rm -f "$testfile"
}

encrypt_file "$PROFILE" private/candidate_profile.json.gpg
encrypt_file "$ANSWERS" private/application_answers.json.gpg
encrypt_file "$RESUME" private/Mohamed_Ahmed-general.pdf.gpg

gh secret set AUTOPILOT_DECRYPTION_PASSPHRASE --repo "$REPO" < "$PASS_FILE"

git add -f private/candidate_profile.json.gpg private/application_answers.json.gpg private/Mohamed_Ahmed-general.pdf.gpg

echo
echo "Encrypted private files are staged for: $REPO"
echo "The decryption passphrase is stored locally at: $PASS_FILE (permissions 600)"
echo "GitHub Actions secret set: AUTOPILOT_DECRYPTION_PASSPHRASE"
echo "Encrypted files staged (only ciphertext):"
git status --short -- private/candidate_profile.json.gpg private/application_answers.json.gpg private/Mohamed_Ahmed-general.pdf.gpg
echo
echo "Existing Actions secret NAMES (values are not shown):"
gh secret list --repo "$REPO" || true
echo
echo "Next: inspect git status, commit the code/workflow and these three .gpg files, then push to the repository's default branch."
echo "Never git-add .env, candidate_profile.json, application_answers.json, or the unencrypted PDF."
