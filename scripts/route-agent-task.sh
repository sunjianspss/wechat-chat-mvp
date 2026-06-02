#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/route-agent-task.sh <issue-number> [--format human|env] [--comment]

Reads config/agent-routing.yml and routes a GitHub Issue to an agent based on labels.

Required tools:
  gh
  ruby

Environment:
  GH_TOKEN or authenticated gh CLI session
USAGE
}

issue_number=""
format="human"
comment="false"

while [ "$#" -gt 0 ]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --format)
      format="${2:-}"
      shift 2
      ;;
    --comment)
      comment="true"
      shift
      ;;
    *)
      if [ -z "$issue_number" ]; then
        issue_number="$1"
        shift
      else
        echo "Unexpected argument: $1" >&2
        usage
        exit 64
      fi
      ;;
  esac
done

if [ -z "$issue_number" ]; then
  usage
  exit 64
fi

if [ "$format" != "human" ] && [ "$format" != "env" ]; then
  echo "--format must be human or env." >&2
  exit 64
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "gh is required." >&2
  exit 127
fi

if ! command -v ruby >/dev/null 2>&1; then
  echo "ruby is required." >&2
  exit 127
fi

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
workflow_root="$(CDPATH= cd -- "$script_dir/.." && pwd)"
config_file="$workflow_root/config/agent-routing.yml"

labels="$(gh issue view "$issue_number" --json labels --jq '.labels[].name')"

route_output="$(
  ISSUE_LABELS="$labels" ROUTE_FORMAT="$format" ruby -ryaml -rshellwords -e '
    config = YAML.load_file(ARGV.fetch(0))
    labels = ENV.fetch("ISSUE_LABELS").lines.map(&:strip).reject(&:empty?)
    blocked = Array(config["blocked_labels"])
    blocked_hit = labels & blocked

    unless blocked_hit.empty?
      warn "Issue is blocked by label: #{blocked_hit.first}"
      exit 2
    end

    route = Array(config["routes"]).find do |candidate|
      labels.any? { |label| Array(candidate["labels"]).include?(label) }
    end

    unless route
      warn "No matching route for labels: #{labels.join(", ")}"
      exit 3
    end

    agent_name = route.fetch("agent")
    agent = config.fetch("agents").fetch(agent_name)
    checks = Array(route["required_checks"])

    if ENV.fetch("ROUTE_FORMAT") == "env"
      puts "AGENT_ROUTE=#{route.fetch("name").shellescape}"
      puts "AGENT_NAME=#{agent_name.shellescape}"
      puts "AGENT_COMMAND=#{agent.fetch("command").shellescape}"
      puts "AGENT_REQUIRED_CHECKS=#{checks.join(",").shellescape}"
    else
      puts "Route: #{route.fetch("name")}"
      puts "Agent: #{agent_name}"
      puts "Command: #{agent.fetch("command")}"
      puts "Required checks: #{checks.join(", ")}"
    end
  ' "$config_file"
)"

printf '%s\n' "$route_output"

if [ "$comment" = "true" ]; then
  agent_name="$(printf '%s\n' "$route_output" | awk -F': ' '/^Agent:/ {print $2}')"
  route_name="$(printf '%s\n' "$route_output" | awk -F': ' '/^Route:/ {print $2}')"
  gh issue comment "$issue_number" --body "Agent routing decision: route=$route_name, agent=$agent_name."
fi
