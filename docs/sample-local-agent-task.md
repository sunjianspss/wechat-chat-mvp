# Sample Local Agent Task

## Background

`wechat-chat-mvp` is a local-only WeChat chat screenshot, OCR, cleanup, and summary tool. Before wiring GitHub Issues, we need a safe local task format that an agent can read without touching private chat output.

## Goal

Verify that the agent workflow can prepare a local task prompt inside this project without reading or uploading `runs/` data.

## Acceptance Criteria

- The local task runner validates all required sections.
- The local task runner creates a `.agent-runs/local-*` directory.
- The generated prompt tells the agent to read `AGENTS.md` first.
- The generated prompt repeats the privacy rule that `runs/` data must not be read or uploaded unless explicitly required.

## Constraints

- Do not read screenshots or chat outputs in `runs/`.
- Do not operate WeChat.
- Do not change production-like privacy boundaries.
- Do not use system Python directly.

## Required Verification

- Run `scripts/run-local-agent-task.sh docs/sample-local-agent-task.md`.
- Run `UV_CACHE_DIR=/private/tmp/uv-cache uv run --python 3.12 python wechat_analyzer.py --help`.
