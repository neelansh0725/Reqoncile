#!/usr/bin/env bash
# Start the Reqoncile API (T057).
#
#   ./scripts/serve.sh            # http://127.0.0.1:8000
#   PORT=9000 ./scripts/serve.sh
#
# Startup loads the embedding model (~9s) so the first request does not pay
# for it -- see docs/latency.md.
set -euo pipefail
cd "$(dirname "$0")/.."
exec ./.venv/bin/uvicorn backend.main:app \
  --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}" "$@"
