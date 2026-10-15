#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
  echo "Create the environment first: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi
exec .venv/bin/python -m uvicorn api.main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-3000}"
