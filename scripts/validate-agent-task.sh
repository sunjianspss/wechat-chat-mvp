#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/validate-agent-task.sh <issue-number>

Validates that a GitHub Issue is safe and complete enough for an agent to start.

Required tools:
  gh

Environment:
  GH_TOKEN or authenticated gh CLI session
USAGE
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

issue_number="${1:-}"

if [ -z "$issue_number" ]; then
  usage
  exit 64
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "gh is required." >&2
  exit 127
fi

body="$(gh issue view "$issue_number" --json body --jq '.body // ""')"
labels="$(gh issue view "$issue_number" --json labels --jq '.labels[].name')"

blocked_labels='needs-human
missing-acceptance-criteria
blocked'

for blocked in $blocked_labels; do
  if printf '%s\n' "$labels" | grep -Fxq "$blocked"; then
    echo "Issue #$issue_number is blocked by label: $blocked" >&2
    exit 2
  fi
done

missing=0
while IFS= read -r section; do
  if ! printf '%s\n' "$body" | grep -Eiq "^(#{2,3}[[:space:]]*)?$section[[:space:]]*$"; then
    echo "Missing required section: $section" >&2
    missing=1
  fi
done <<'SECTIONS'
Background
Goal
Acceptance Criteria
Constraints
Required Verification
SECTIONS

if [ "$missing" -ne 0 ]; then
  echo "Issue #$issue_number is not ready for agent execution." >&2
  exit 3
fi

if printf '%s\n' "$body" | grep -Eiq 'ignore (all )?(previous|above|system|developer) instructions|do not read AGENTS\.md|bypass (ci|tests|review)|disable (ci|tests)'; then
  echo "Issue #$issue_number contains text that looks like prompt-injection or safety-bypass instructions." >&2
  exit 4
fi

echo "Issue #$issue_number passed agent-task validation."
