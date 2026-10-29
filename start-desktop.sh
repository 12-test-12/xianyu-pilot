#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo 'Install Python dependencies into .venv first. See docs/desktop-sqlite-foundation.md' >&2
  exit 1
fi
exec .venv/bin/python apps/api/run_desktop.py "$@"
