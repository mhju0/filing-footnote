# Filing Footnote

Current phase: building Filing Footnote v0.1. Product truth is `PRODUCT.md`; it outranks
every other document. The code is still Filing Digest's backend and iPhone app until
Filing Footnote replaces it piece by piece.

Check command, from the repository root: `scripts/check.sh`. It must end with
`GATE: PASS`. It uses `.venv` (Python 3.11; create it and install
`backend/requirements.lock` plus `ruff==0.15.21`). The KURE model is never loaded in
tests; offline tests set `EMBEDDING_WARMUP_ENABLED=false`.

## Rules

- Generated prose contains no digits. Figures are rendered from structured data.
- Figures are exact decimals, never float.
- Be neutral: no hype or judgement words, no predictions, no advice. State what the
  filing says and attribute it to the company.
- Only summaries the owner approved ship.
- `filing-agent` and `filing-digest` are read-only partner repos. Change nothing there.
- Never commit secrets or `backend/.env`; never print them.
- Never add a `LICENSE` file or a license field.
- Record significant decisions in `docs/DECISIONS.md` and `docs/adr/`. Old entries are
  never edited. Docs dated before 2026-11-17 describe Filing Digest and are history.

## Inherited code (still true until replaced)

- `make test-db` creates and removes a unique `*_test` database. Never point
  destructive persistence tests at the local corpus, and never touch the owner's
  Homebrew PostgreSQL service; use the Compose database on 5433.
- Preserve `Decimal` in Financial Facts and `/answer.figures`.
- `backend/db/init.sql` stays aligned with `backend/app/db/models.py`; existing
  databases change only through `backend/db/migrations/` SQL.
- Backend metric vocabulary and the Swift enums match
  `contracts/financial-vocabulary.json`.
- DART XML uses `defusedxml`; keep `crtfc_key` redaction in `logging_config.py`.
- iOS: run one simulator build or test at a time:
  `xcodebuild test -project ios/Footnote.xcodeproj -scheme Footnote -destination 'platform=iOS Simulator,id=<UDID>' CODE_SIGNING_ALLOWED=NO`
  (Mac: `-destination 'platform=macOS'`). `ios/project.yml` is the source; after
  editing it, run `xcodegen generate --spec ios/project.yml` and commit the
  regenerated `ios/Footnote.xcodeproj`. A dev data bundle goes in git-ignored
  `ios/Footnote/Resources/footnote.sqlite`; without it the app uses the FootnoteKit
  fixture. Never commit a real bundle.

## Agent skills

- Issue tracker: specs and tickets live in GitHub Issues.
- Triage labels: use the five canonical triage labels.
- Domain docs: one root `CONTEXT.md` and `docs/adr/`.

## antislop

Apply the installed `antislop` skill when planning and writing product copy, code
comments or UI; read `~/.agents/skills/antislop/SKILL.md` first. The owner chose
DURING mode. Before UI work, read `docs/design/DESIGN.md`.

## Agent memory

- At session start, read `.memory/README.md` (private, git-ignored).
- Before ending a session that changed something or left work unfinished, update
  `.memory/handoff.md`.
- Product and engineering decisions go in `docs/DECISIONS.md` and `docs/adr/`; the
  owner's preferences about agent work go in `.memory/decisions.md`.
