#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/notify-done.sh --issue-url URL --pr-url URL --agent NAME --ci-status STATUS [--human-action TEXT]

Prints a completion notification. If SLACK_WEBHOOK_URL or FEISHU_WEBHOOK_URL is set,
also posts the notification as JSON text.

Required tools for webhook posting:
  curl
USAGE
}

issue_url=""
pr_url=""
agent_name=""
ci_status=""
human_action="review / merge"

while [ "$#" -gt 0 ]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --issue-url)
      issue_url="${2:-}"
      shift 2
      ;;
    --pr-url)
      pr_url="${2:-}"
      shift 2
      ;;
    --agent)
      agent_name="${2:-}"
      shift 2
      ;;
    --ci-status)
      ci_status="${2:-}"
      shift 2
      ;;
    --human-action)
      human_action="${2:-}"
      shift 2
      ;;
    *)
      echo "Unexpected argument: $1" >&2
      usage
      exit 64
      ;;
  esac
done

if [ -z "$issue_url" ] || [ -z "$pr_url" ] || [ -z "$agent_name" ] || [ -z "$ci_status" ]; then
  usage
  exit 64
fi

message="任务完成

Issue：$issue_url
PR：$pr_url
执行 agent：$agent_name
CI 状态：$ci_status
需要人工处理：$human_action"

printf '%s\n' "$message"

json_payload="$(ruby -rjson -e 'puts({text: STDIN.read}.to_json)' <<<"$message")"

if [ -n "${SLACK_WEBHOOK_URL:-}" ]; then
  curl -fsS -X POST -H 'Content-Type: application/json' --data "$json_payload" "$SLACK_WEBHOOK_URL"
fi

if [ -n "${FEISHU_WEBHOOK_URL:-}" ]; then
  curl -fsS -X POST -H 'Content-Type: application/json' --data "$json_payload" "$FEISHU_WEBHOOK_URL"
fi
