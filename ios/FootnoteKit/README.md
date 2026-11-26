# FootnoteKit

The Swift package the Filing Footnote app (iPhone, iPad and native Mac) builds on. It has no
third-party dependencies and no UI.

- `BundleStore` opens the bundled `footnote.sqlite` read-only with the system SQLite, refuses a
  `schema_version` other than the one in `backend/app/build/bundle.py` (5) or schema 4, which
  opens without source sentences (D101), and reads every table
  into `Sendable` values. Figures and decimal facts are `Decimal`, parsed from canonical
  strings. A release build of the app calls `requireRelease()`, which throws for a
  development bundle (`allow_unapproved = 1`).
- `Calculator` is the port of `backend/app/compare/calculator.py`: year over year, derived
  operating margin and cross-company rates, with the six refusal reasons.
- `Formatting` gives the display strings: amounts in 조 and 억 or in trillions and billions,
  signed percentages with a direction word, and month-day dates.

Nothing in `Sources/` uses binary floating point; a test fails if a source file names
`Double` or `Float`.

## Tests

```sh
swift test --package-path ios/FootnoteKit
```

They run on the host Mac, with no simulator. `scripts/check.sh` runs them on macOS.

Test resources:

- `Tests/FootnoteKitTests/Contracts/` holds copies of `comparison-cases.json`,
  `financial-vocabulary.json` and `filing-categories.json` from `contracts/`. After editing
  one of those, run `ios/FootnoteKit/scripts/sync-contracts.sh`. A test compares each copy
  with its original and fails when they differ.
- `Tests/FootnoteKitTests/Fixtures/footnote.sqlite` is a development bundle written through
  the real exporter from the backend's offline test seed. It is never shipped. Rewrite it
  after a schema change with `cd backend && ../.venv/bin/python -m tests.footnotekit_fixture`;
  `backend/tests/test_footnotekit_fixture.py` fails while it does not match `bundle.py`.
  The generator has drifted from the committed fixture (its event summary is missing), so
  the schema 5 change migrated the committed file and added `summary_sources` rows from
  the generator's made-up records instead of rewriting it.
