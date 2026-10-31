#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p .tmp
export TMPDIR="$PWD/.tmp"
export UV_CACHE_DIR="$PWD/.uv-cache"
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict src
uv run pytest
