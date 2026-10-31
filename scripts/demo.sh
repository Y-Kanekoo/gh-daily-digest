#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p .tmp
export TMPDIR="$PWD/.tmp"
export UV_CACHE_DIR="$PWD/.uv-cache"
uv run gh-daily-digest --fixtures examples/fixtures --no-discord "$@"
