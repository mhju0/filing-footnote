# Architecture

Filing Footnote has two halves that meet at one file. A Python build on the owner's Mac
turns regulator data into `footnote.sqlite`; a SwiftUI app reads that file offline and
read-only. Product rules are in [PRODUCT.md](../PRODUCT.md); the reasons behind each part are
in [DECISIONS.md](DECISIONS.md) and [adr/](adr/).

```text
DART / SEC APIs
   │  python -m app.ingest (--save-pinned)
   ▼
PostgreSQL build database ──────────────┐      backend/data/pinned/  (raw regulator responses)
   │                                    │             │
   │  app.build.summaries generate      │             │ re-read with the ingest parsers
   ▼                                    │             ▼
staged.jsonl ── owner: app.build.approve ──► approved.jsonl
                                        │
                                        ▼
                    app.build.export ──► footnote.sqlite + footnote.report.json
                                        │  app.build.verify --release
                                        ▼
          ios/Footnote (SwiftUI app) ◄── FootnoteKit (BundleStore, Calculator, page models)
```

## Backend build (`backend/app/`)

| Module | Role |
|---|---|
| `clients/` | HTTP clients and parsers: `dart.py` (lists, statements, documents), `dart_events.py` (DART structured event endpoints), `dart_tables.py` (tables read from a filing's own body, D78), `sec.py` (submissions, companyfacts), `sec_8k.py`, `sec_document.py` |
| `ingest/` | The `python -m app.ingest` CLI. Annual reports and statements (`dart.py`, `sec_ingest.py`), twelve months of event filings (`events.py`, `sec_events.py`), DART correction chains (D65), prior-year reports for restatement checks (`--prior`, D79) and pinned response files (`pinned.py`) |
| `filings/categories.py` | Assigns each filing one category or a named exclusion from `contracts/filing-categories.json` by rule, never by model (ADR 0004, ADR 0007) |
| `llm/neutrality_guard.py` | Rules N1 to N8 that block a line (digits, judgement words, predictions, attribution, links, shape, advice, language) and N9 warnings, with word lists in `contracts/neutrality-lexicon.json` (ADR 0005) |
| `build/summaries.py`, `build/templates.py` | Summary generation on Groq (D68) with the guard and one retry; template lines for DART table filings (D78); an advisory reviewer call |
| `build/review.py`, `build/approve.py` | The owner's proofreading page and the approval command |
| `build/faithfulness.py` | Finds the source sentences behind each summary line and marks it supported, partly or unsupported, with places, products and currencies from `contracts/faithfulness-lexicon.json`; writes the report `verify --release` reads, and runs the eval (D97) |
| `build/quality.py` | Read-only counts from the summary files: guard results, retries, reviewer flags, approvals, calls and tokens |
| `build/model.py`, `build/source.py` | Regulator-neutral rows read from the build database, the canonical decimal form, the scope rules (`ANNUAL_SCOPE`, `annual_sections`) and summary cache keys |
| `build/export.py`, `build/bundle.py`, `build/glossary.py` | Writes the bundle and its report; owns the schema and the content fingerprint |
| `build/verify.py` | Checks every figure and fact against the pinned responses; checks a finished file with `--release` |
| `compare/calculator.py` | The reference comparison calculator: year over year, operating margin, cross-company rates and the six refusal reasons. FootnoteKit's `Calculator` is a port of it |

The backend package and the app still carry version 0.5.2; the
v0.5.2 portfolio architecture of Filing Digest is kept in
[history/filing-digest-architecture.md](history/filing-digest-architecture.md).

## The bundle contract

`backend/app/build/bundle.py` is the schema. Its tables:

- `build_meta`: `schema_version` (5), `data_as_of`, `source_revision`, `llm_model`,
  `prompt_version`, `content_sha256`, `allow_unapproved` (1 for a development build),
  `preview` (1 for a preview build, D90) and `aligner_version` (D100).
- `companies`, `filings` (annual or event, with category and source link), `notices`
  (listed as a count, never summarised), `filing_summaries` (only rows whose
  `review_state` is `approved` can be written), `summary_sources` (the verbatim source
  sentence behind each summary line, from the faithfulness report, D100), `filing_facts`,
  `figures` and `glossary`.
- Every amount is `TEXT` in canonical decimal form; there is no `REAL` column. The
  fingerprint is a SHA-256 over a canonical dump of every table except `build_meta`
  ([build-bundle.md](build-bundle.md)).

Both sides read shared files in [`contracts/`](../contracts/):

| File | Shared by |
|---|---|
| `financial-vocabulary.json` | Metric keys for ingest, export and the Swift enums |
| `filing-categories.json` | Categories for the classifier, export and the app's tags |
| `filing-facts.json` | Fact names; the app bundles it for its labels |
| `comparison-cases.json` | 112 cases that the Python and Swift calculators must both pass ([comparison-rules.md](comparison-rules.md)) |
| `neutrality-lexicon.json` | The guard's word lists |
| `faithfulness-lexicon.json` | Places, products, currencies and terms in both languages for the faithfulness check (D97) |
| `glossary.json` | Glossary entries, each with an owner `approved` flag |

FootnoteKit's tests keep copies of three of these files; a backend test byte-compares the
copies with the originals, and `BundleStore` refuses any `schema_version` but the current one
and schema 4, which it opens without source sentences.

## The app (`ios/`)

| Part | Holds |
|---|---|
| `ios/FootnoteKit` | A Swift package with no UI and no third-party code. `BundleStore` opens the bundle read-only with the system SQLite and parses figures into `Decimal`. `Calculator` ports the backend calculator. `CompanyPage`, `FilingPage`, `AnnualPage`, `FigureCompare` and `NewsFeed` decide what each screen shows; `Formatting` and `Titles` produce the text. A test fails if a source file names `Double` or `Float` |
| `ios/Footnote` | The SwiftUI target for iPhone, iPad and native Mac: `App/` (launch, copy, release check), `Screens/`, `Components/`. Views lay out FootnoteKit models and hold little logic |
| `ios/project.yml` | The XcodeGen spec. The generated `ios/Footnote.xcodeproj` is committed |

Because the screen logic lives in FootnoteKit, `swift test` covers it on the Mac with no
simulator. iPhone uses tabs (기업 · 소식 · 용어); iPad and Mac use a three-column split view
(ADR 0008).

## Release gates

A development bundle can be built and shown at any time; a release cannot ship until the
owner has approved what it contains. The gates, in order:

1. `app.build.export` refuses in every mode, development builds included, when a figure or
   fact differs from its pinned response, or when an exported summary line or glossary text
   fails the guard. Without `--allow-unapproved` (a release, the default) it also refuses
   when a filing in scope lacks approved summaries in both languages, when an approval's
   input hash no longer matches its source text, prompt, model and lexicon, when any glossary
   entry is unapproved, when either prompt version is `none`, or when a prior-year figure
   cannot be checked against its own year's report (`restatement_unchecked`). A development
   build skips stale approvals and lists them in its report.
2. `python -m app.build.verify <file> --pinned <dir> --release` checks a finished file on its
   own: it recomputes the fingerprint, re-reads every figure and fact, runs the guard on every
   summary line, checks summary coverage and refuses `allow_unapproved = 1`. It does not
   re-check glossary rows (D81). It also reads the faithfulness report: every summary line
   needs a current record, and with the default policy an unsupported line blocks unless the
   owner accepted it (D97).
3. The Xcode build phase fails a Release build with no bundle or with a development bundle.
4. At launch a release build calls `BundleStore.requireRelease()`, which throws for a
   development bundle; the app then shows an error screen instead of the data.

## Tests

| Suite | Where | Runs in |
|---|---|---|
| Backend offline tests | `backend/tests/`, pytest | `scripts/check.sh`, and CI on pushes to `main` and on every PR |
| PostgreSQL persistence tests | `backend/tests/run_postgres.py` | `make test-db` and CI |
| FootnoteKit tests | `ios/FootnoteKit/Tests/`, Swift Testing, against a fixture bundle the real exporter writes | `scripts/check.sh` on macOS |
| App unit tests | `ios/FootnoteTests/`, scheme `Footnote` | `xcodebuild`, iOS simulator and Mac; CI job on manual dispatch only |
| UI tests | `ios/FootnoteUITests/`, scheme `FootnoteUITests` | `xcodebuild`, iOS simulator only |

Counts and how they were taken are in [CASE_STUDY.md](CASE_STUDY.md#measured-results).
