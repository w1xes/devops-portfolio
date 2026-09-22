#!/usr/bin/env bash
# Bootstrap a fresh, empty public GitHub repository with the same
# repository-level rules used in devops-portfolio (Lab 1, bonus task).
#
# Usage:
#   ./bootstrap-repo.sh <owner>/<repo>
#
# Requires: GitHub CLI (`gh`), already authenticated (`gh auth login`).
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <owner>/<repo>" >&2
  exit 1
fi

REPO="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RULESET_FILE="$SCRIPT_DIR/main-ruleset.json"
PR_TEMPLATE_FILE="$SCRIPT_DIR/pull_request_template.md"

echo "==> Applying rules-as-code to $REPO"

# 1. Make sure the repo is public (branch protection rulesets are a
#    paid-plan-only feature on private repos for personal accounts).
gh repo edit "$REPO" --visibility public --accept-visibility-change-consequences

# 2. Create the branch ruleset for the default branch from the JSON config.
gh api \
  --method POST \
  -H "Accept: application/vnd.github+json" \
  "repos/$REPO/rulesets" \
  --input "$RULESET_FILE"

# 3. Push the PR template into the repo (creates .github/pull_request_template.md).
TMP_DIR="$(mktemp -d)"
gh repo clone "$REPO" "$TMP_DIR/repo" -- --quiet
mkdir -p "$TMP_DIR/repo/.github"
cp "$PR_TEMPLATE_FILE" "$TMP_DIR/repo/.github/pull_request_template.md"
git -C "$TMP_DIR/repo" add .github/pull_request_template.md
git -C "$TMP_DIR/repo" commit -m "chore: add PR template via rules-as-code bootstrap" --quiet || true
git -C "$TMP_DIR/repo" push --quiet
rm -rf "$TMP_DIR"

echo "==> Done. Ruleset + PR template applied to $REPO"
