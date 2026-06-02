#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/private/tmp/uv-cache}"
exec uv run --python 3.12 python wechat_analyzer.py run "$@"
