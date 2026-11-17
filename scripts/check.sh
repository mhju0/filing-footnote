#!/usr/bin/env bash
# Runs the repo's lint and offline test targets and ends with GATE: PASS or GATE: FAIL.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-.venv/bin/python}"
case "$PYTHON" in /*) ;; *) PYTHON="$ROOT/$PYTHON" ;; esac
RUFF="${RUFF:-$(dirname "$PYTHON")/ruff}"

STEP="start"
finish() {
  status=$?
  if [ "$status" -eq 0 ]; then
    echo "GATE: PASS"
  else
    echo "step failed: $STEP" >&2
    echo "GATE: FAIL"
  fi
}
trap finish EXIT

run() {
  STEP="$1"
  shift
  echo "== $STEP"
  "$@"
}

run "lint" make lint PYTHON="$PYTHON" RUFF="$RUFF"
run "offline tests" make test PYTHON="$PYTHON"
# Contract tests are added here.
