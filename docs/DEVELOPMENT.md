# Development

How to run the checks, build a data bundle and test the app. [ARCHITECTURE.md](ARCHITECTURE.md)
explains the parts. Run every command from the repository root unless it says otherwise.

## Checks

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r backend/requirements.lock ruff==0.15.21
scripts/check.sh
```

The gate passes only when the last line is `GATE: PASS`. It runs, in order:

1. `make lint`: Ruff over `backend/`.
2. `make test`: the offline pytest suite, with `DART_API_KEY` and `TEST_DATABASE_URL` unset,
   so no network or key is used.
3. `swift test --package-path ios/FootnoteKit` (macOS only).
4. Regenerates `ios/Footnote.xcodeproj` with XcodeGen 2.47.0 and fails if it differs from the
   committed copy (skipped when XcodeGen is not installed; fails on another version).
5. A grep that fails if app code names an exchange rate or a currency conversion (D84).

Other targets:

```bash
make test TESTS='tests/test_comparison_cases.py'   # one backend test file
make test-db                                       # PostgreSQL suites in a throwaway *_test database
```

`make test-db` creates and removes its own database. Point it at the Compose PostgreSQL on
port 5433 (`docker compose up -d db`), never at a database that holds real data.

## Building a data bundle

This needs network access, a DART API key, an SEC contact string and, for summaries, a Groq
API key. Put them in `backend/.env`, which is git-ignored and must never be committed:
`DART_API_KEY`, `SEC_USER_AGENT`, `LLM_API_KEY` and `DATABASE_URL` for the build database.

From `backend/`, with the Compose database running:

```bash
# Annual report and statements, then the report before it for restatement checks
../.venv/bin/python -m app.ingest --source dart --ticker 005930 --save-pinned data/pinned
../.venv/bin/python -m app.ingest --source dart --ticker 005930 --prior --save-pinned data/pinned
# Twelve months of event filings
../.venv/bin/python -m app.ingest events --source dart --ticker 005930 --save-pinned data/pinned

# Summaries: stage, proofread, approve (the owner runs approve)
../.venv/bin/python -m app.build.summaries generate --as-of 2026-11-19 --dry-run
../.venv/bin/python -m app.build.summaries generate --as-of 2026-11-19
../.venv/bin/python -m app.build.review --out ../dist/review.html
../.venv/bin/python -m app.build.approve --filing <filing id>

# Counts: guard results, retries, reviewer flags, approvals, calls and tokens (read-only)
../.venv/bin/python -m app.build.quality
```

Groq's free tier allows 1000 output tokens a minute (D68), so `generate` waits between calls
(`--call-interval`). During the 2026-11-19 run it also returned HTTP 429 errors for tokens
per day. Cached sections are not sent again.

Export and verify, from the repository root:

```bash
make data AS_OF=2026-11-19 PINNED=backend/data/pinned                                   # release
make data AS_OF=2026-11-19 PINNED=backend/data/pinned DATA_FLAGS=--allow-unapproved     # development
make data-preview AS_OF=2026-11-19 PINNED=backend/data/pinned                            # preview, for internal TestFlight (D90)
cd backend && ../.venv/bin/python -m app.build.verify ../dist/footnote.sqlite --pinned data/pinned --release
```

The bundle and its report land in `dist/` (git-ignored). A release export fails until every
summary and glossary entry in scope is approved; see the release gates in
[ARCHITECTURE.md](ARCHITECTURE.md#release-gates). To run the app on a development bundle,
copy it to `ios/Footnote/Resources/footnote.sqlite`, which is git-ignored. Never commit a
real bundle.

## App

`ios/project.yml` is the source of the Xcode project. After editing it:

```bash
xcodegen generate --spec ios/project.yml   # XcodeGen 2.47.0
```

and commit the regenerated `ios/Footnote.xcodeproj`. Tests:

```bash
xcodebuild test -project ios/Footnote.xcodeproj -scheme Footnote \
  -destination 'platform=iOS Simulator,id=<UDID>' CODE_SIGNING_ALLOWED=NO
xcodebuild test -project ios/Footnote.xcodeproj -scheme Footnote \
  -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO
xcodebuild test -project ios/Footnote.xcodeproj -scheme FootnoteUITests \
  -destination 'platform=iOS Simulator,id=<UDID>' CODE_SIGNING_ALLOWED=NO
```

Run one simulator job at a time. The UI tests open the FootnoteKit fixture through the debug
launch argument `-FootnoteBundle`. `ios/scripts/screenshots.sh` captures the screens in
[screenshots/footnote/](screenshots/footnote/) from a built app on a booted simulator.
`ios/scripts/walkthrough.sh <udid> <out.mp4>` records the walkthrough video: it reinstalls the
app with the development bundle and runs `WalkthroughUITests`, which is skipped unless
`TEST_RUNNER_FOOTNOTE_WALKTHROUGH=1` is set.

## Changing a shared contract

- After editing `contracts/comparison-cases.json`, `financial-vocabulary.json` or
  `filing-categories.json`, run `ios/FootnoteKit/scripts/sync-contracts.sh`; tests fail while
  the copies differ.
- After changing the bundle schema, rewrite the FootnoteKit fixture with
  `cd backend && ../.venv/bin/python -m tests.footnotekit_fixture`.
- A change to the summary prompt, a template or the lexicon changes the summary cache key, so
  every affected summary is generated and approved again.

The Filing Digest setup (FastAPI server, device builds over the LAN, API contract) is kept in
[history/filing-digest-development.md](history/filing-digest-development.md).
