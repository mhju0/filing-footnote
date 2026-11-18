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
# FootnoteKit runs on the host Mac with swift test (no simulator); other hosts skip it.
if [ "$(uname -s)" = "Darwin" ]; then
  run "FootnoteKit tests" swift test --package-path ios/FootnoteKit
else
  echo "== FootnoteKit tests skipped: swift test needs macOS"
fi

# ios/Footnote.xcodeproj is generated from ios/project.yml and committed. Regenerate it
# and compare. On drift, or when generation itself fails, restore the checked-in copy and
# fail. Another XcodeGen version writes a different file, so the version is pinned.
XCODEGEN_VERSION="2.46.0"
xcodeproj_current() {
  found="$(xcodegen --version 2>/dev/null | sed -n 's/^Version: //p')"
  if [ "$found" != "$XCODEGEN_VERSION" ]; then
    echo "the Xcode project check expects XcodeGen $XCODEGEN_VERSION, found ${found:-no version}" >&2
    return 1
  fi
  (
    snapshot="$(mktemp -d)"
    restore() {
      status=$?
      if [ "$status" -ne 0 ]; then
        rm -rf ios/Footnote.xcodeproj
        cp -R "$snapshot/Footnote.xcodeproj" ios/
      fi
      rm -rf "$snapshot"
      exit "$status"
    }
    trap restore EXIT
    cp -R ios/Footnote.xcodeproj "$snapshot/"
    xcodegen generate --quiet --spec ios/project.yml
    if ! diff -r "$snapshot/Footnote.xcodeproj" ios/Footnote.xcodeproj >/dev/null; then
      echo "ios/Footnote.xcodeproj is stale: run xcodegen generate --spec ios/project.yml" >&2
      exit 1
    fi
  )
}
if command -v xcodegen >/dev/null 2>&1; then
  run "Xcode project matches project.yml" xcodeproj_current
else
  echo "== Xcode project check skipped: xcodegen is not installed"
fi
# Contract tests are added here.
