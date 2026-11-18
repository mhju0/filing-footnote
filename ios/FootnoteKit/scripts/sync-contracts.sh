#!/usr/bin/env bash
# Copies the shared contracts FootnoteKit's tests read into the test resources.
# ContractCopyTests fails when a copy differs from contracts/, so run this after editing one.
set -euo pipefail

PACKAGE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$(cd "$PACKAGE/../.." && pwd)"
for name in comparison-cases.json financial-vocabulary.json filing-categories.json; do
  cp "$ROOT/contracts/$name" "$PACKAGE/Tests/FootnoteKitTests/Contracts/$name"
done
echo "copied contracts into $PACKAGE/Tests/FootnoteKitTests/Contracts"
