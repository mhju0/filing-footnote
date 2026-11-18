# Decision Ledger

Chronological record of the choices that shaped Filing Digest, including the
ones that were later undone. Git shows *what* changed; this file records *why*,
*what it replaced*, and *whether it still holds*.

**Statuses:** `ACTIVE` · `REVERSED` · `SUPERSEDED` · `DEFERRED` ·
`EXPERIMENTAL` · `ABANDONED` · `UNKNOWN`

Evidence is a commit hash, PR number, file path, or, where the only source is
prior assistant conversation, **(conversation context)**. Formal architecture
decisions also live in [`docs/adr/`](adr/); this ledger is broader and includes
product, process, and tooling calls that never earned an ADR.

---

## 2026-07 · Foundation

### D1 · Project identity: galpi → haeksim → filing-digest (`ACTIVE`)
The repository was initialized as `galpi` (`0967185`), briefly carried the iOS
target name `Haeksim`, and was renamed to `filing-digest` on the same day
(`d33604e`, `0450da8`, `78f58f7`, all 2026-07-02). The English name survived
because the audience is a recruiter or hiring engineer reading in English.
No trace of the old names remains in tracked source.

### D2 · Stack: FastAPI + SwiftUI + PostgreSQL/pgvector (`ACTIVE`)
Scaffolded in one commit (`f1636c3`, 2026-07-02). Chosen so the project would
demonstrate a real async Python backend and a native client rather than a
notebook or a web toy. The iOS client deliberately carries **zero third-party
packages** (SwiftUI, URLSession, Codable, Swift Testing only) to keep the
build surface small and reviewable.

### D3 · Embeddings: KURE-v1 at 1024 dimensions, normalized, cosine (`ACTIVE`)
`c7d65a1` (2026-07-02). One cross-lingual embedding space serves both Korean
and English rather than two monolingual indexes with a translation hop.
`normalize_embeddings=True` is fixed at write time and distance is cosine
(`<=>`), which is why any vector index **must** use `vector_cosine_ops`.
Alternative considered and rejected: separate KO/EN models with query-side
translation, because it would have made cross-lingual answers a translation-quality
problem instead of a retrieval problem. **(conversation context)**

### D4 · No Alembic; `init.sql` is the schema source of truth (`ACTIVE`)
Decided at scaffold time and never revisited. `backend/db/init.sql` and
`backend/app/db/models.py` must agree exactly, and
`backend/tests/test_database_schema.py` checks selected ORM invariants rather
than full SQL/ORM parity. The reasoning: for a
single-developer project with one database, a migration framework adds a second
source of truth and a class of drift bugs without buying anything.
**Refined, not reversed**, in D26: existing databases are upgraded by
hand-written versioned SQL under `backend/db/migrations/` after a `pg_dump`.

### D5 · `defusedxml` only for XML (`ACTIVE`)
DART returns XML from a public endpoint, so XXE and billion-laughs are real
input classes. The rule is absolute; DSD content is repaired *before* being
handed to `defusedxml`, never parsed with the stdlib parser instead.

### D6 · Ports moved off the defaults (`ACTIVE`)
`98ba68a` moved the API from host `8000` to `8001` (2026-07-04) and `f3e7d4d`
moved Compose PostgreSQL from host `5432` to `5433` the same day. Both were
collision avoidance with a neighboring project on the same machine whose Vite
proxy target could not move. Consequence: **omitting `--port 8001` silently
starts on 8000 and collides.** The committed `.env.example` default therefore
points at 5433, while this machine's actual `.env` points at 5432 (see D24).

### D7 · Compose backend isolated behind a `container` profile (`ACTIVE`)
`bab72c9` (2026-07-05). A bare `docker compose up` was starting a backend
container that fought host uvicorn for the port and answered `/health` with an
empty body because it had no KURE-v1 cache. Rather than delete the service, it
was moved behind `profiles: ["container"]` so `up -d db` does the right thing
and the container path stays available and documented.

### D8 · The fake `/chat` endpoint and Chat tab (`ABANDONED`)
Built during scaffolding as a placeholder: 100% canned responses, two hardcoded
UUIDs, no DB and no LLM. Deleted in two commits once the real `/answer`
pipeline worked: `306dcaf` removed the route and the 287-line `stub_data.py`,
`7bdffeb` removed `ChatView.swift` and promoted `SearchView` to root
(both 2026-07-05). The stated reason: it was redundant with `/answer` and it
produced a confusing `[스텁] 선택된 회사가 없습니다` in a demo.
**Lasting effect:** the app has no tab bar. The tab bar existed only to hold
Chat, and removing it left a single-root client, which the later browse-first
decision (D14) then built on.

### D9 · Numbers are excluded from prose by code, not by prompt (`ACTIVE`)
The deterministic guards (`backend/app/llm/citation_guard.py`,
`number_guard.py`) validate; they never repair and never re-prompt. Callers
decide what to do with a violation. The number guard's blocklist is
**suffix/prefix-anchored** (`원`, `%`, `배`, `$`, currency words, `x`, `times`)
rather than a bare digit scan, precisely so that years, article numbers, `Item 7`
and `10-K` do not false-positive; the calibration reasoning is written into the
module docstring. `5fdef11` (2026-07-06) extended it from Korean-only to English
numerals after SEC ingestion landed.

### D10 · A `no_results` similarity gate at 0.42 (`ACTIVE`)
`326831c` (2026-07-05). Before this, an unrelated question still produced
confident prose over irrelevant chunks. The threshold is empirically
calibrated: relevant queries' best chunk scored ≥0.45, clearly unrelated ≤0.38,
so 0.42 sits in the gap (`backend/app/search/constants.py:11-14`). It is
explicitly **not** a groundedness classifier, and the README says so.

### D11 · SEC EDGAR as a second source, sharing one persistence layer (`ACTIVE`)
Built 2026-07-06/07 (`f752167`, `40d27ab`, `95f9653`, `520ee7c`) and
live-verified against Apple's 10-K before commit. `sec_accession_no` became a
second nullable UNIQUE natural key beside `rcept_no`; PostgreSQL's NULL-distinct
semantics let both live on one table without collision. `182a46e` stripped
tables from 10-K prose the same week, matching what DART parsing already did.

### D12 · MIT license (`REVERSED`)
Added with the portfolio README (`917c58d`, 2026-07-06), copyright holder
corrected (`2468e2e`), then **removed entirely** on 2026-07-31 (`67da653`):
`LICENSE` deleted, README changed to "All rights reserved. No license is
granted… This repository is public for portfolio review purposes only."
The repository has carried no license since. `b865f8f` then moved the License
section to the end of the README so the product, not the legal notice, leads.

### D13 · English is the canonical documentation language (`ACTIVE`)
`1d7de60` (2026-07-12) made `docs/ARCHITECTURE.md` English and kept the Korean
original as `ARCHITECTURE.ko.md`; `c8f881e` deleted the Korean file the next day.
English remains the canonical documentation language. The former tracked
`CLAUDE.md` was predominantly Korean; it was retired in D47. Korean source
comments remain where they describe Korean-language input quirks.

### D14 · Browse-first home replaces search-box-first (`ACTIVE`)
`a9328dd` (2026-07-12). The original screen was an empty search field. With a
bounded eight-company corpus, hiding the entire corpus behind a text input was
"a dead end", so the home screen now lists every company grouped by source and the
field filters locally as you type. `GET /companies?q=` stayed on the server
(initial load sends `q=""`, matching all) so the API did not have to change.

### D15 · Demo corpus: eight non-financial large caps (`ACTIVE`)
Scope fixed 2026-07-12: DART: 삼성전자, SK하이닉스, NAVER, 현대자동차; SEC:
Apple, Microsoft, NVIDIA, Tesla. Rationale: search should feel like a product,
not a fixture, and household names make screenshots legible.
**Financial and holding companies were declared a non-goal**: IFRS
financial-sector account mapping is a separate project, not a robustness win.
Ingesting six new companies immediately surfaced three real DSD malformation
classes (`313856a`), each fixed with a regression test proven to fail unfixed.

### D16 · YoY from prior-period rows in the same annual filing (`ACTIVE`)
`8bbacb3` (2026-07-12). DART annual filings carry 전기 (prior-period) amounts
that were being parsed and then dropped at persist. Writing them as separate
`<year-1>-annual` rows cited to the same filing gives YoY deltas **without
extracting a single number from prose**; the alternative would have violated D9.

### D17 · HNSW index with `vector_cosine_ops` (`ACTIVE`)
`29d09d7` (2026-07-12), added to `init.sql`, `models.py`, and the live database
together, with `EXPLAIN` confirming the planner uses it. Default build
parameters (m=16, ef_construction=64) are appropriate at ~1k chunks and the
comment says to revisit only at orders-of-magnitude growth.

### D18 · "Ledger" over "Terminal" as the visual direction (`ACTIVE`)
Two directions were mocked up in Stitch (project *Filing Digest Redesign*,
2026-07-12): **Ledger** (light, editorial: paper, ink, ruled structure, one
green accent) and **Terminal** (dark). Ledger was chosen and locked into
`docs/design/DESIGN.md`; the Terminal mockups were deleted with the rest of
`docs/design/mockups/` in `c8f881e`. The Stitch project and its design-system
asset ids survive only in assistant memory. **(conversation context)**

### D19 · String Catalog / device-locale localization (`DEFERRED`)
Recorded in the Phase B checklist and never done. Reasoning as written at the
time: the **in-app KO/EN toggle is this product's bilingual mechanism**, and
device-locale chrome localization would add a second competing language system
for little demo value. Marked "revisit only if the app ships to non-Korean
testers." It never did.

### D20 · Repository "finalized for archival" at v0.2 (`SUPERSEDED`)
`c8f881e` and `059f70d` (2026-07-13) declared the project complete: `ROADMAP.md`
deleted, all logo comps and mockups deleted, README opened with "feature-complete,
not actively maintained, repo-as-artifact." **This did not hold.** Development
continued for another seven weeks through v0.3.0, v0.4.0, v0.5.0 and v0.5.1,
adding the Ledger client, CI, a Pages demo, and three ADRs. The genuinely final
close came 2026-08-27 (D40). Treat pre-v0.5.1 "final" statements as historical.

### D21 · Citation-bracket brand identity (`ACTIVE`)
`01ad634` (2026-07-13). Eleven logo comps were generated and compared
(`docs/design/logos/contact_sheet.png` and friends, all since deleted); the
`[F]` citation-bracket mark won because the bracket *is* the product's thesis.
Only `mark_light.png` and `mark_dark.png` survive in the repository.

### D22 · Local agent tooling is untracked (`ACTIVE`)
Three commits over two weeks: `ca36f18` untracked `.serena/`, `8be72f5`
scrubbed local tooling references out of public source comments (2026-07-14),
and `bccdd98` untracked `docs/agents/` while promoting `CONTEXT.md` and
`docs/adr/` to tracked, README-linked documents (2026-07-25).
The principle that emerged: **domain knowledge is tracked; agent behavior is
not.** `docs/agents/*.md` was added at `427f591` and removed eleven days later.
`CLAUDE.md` was an exception (D23). D47 replaces it with a deliberately small,
tracked `AGENTS.md`; local harness configuration remains untracked.

### D23 · `CLAUDE.md` was gitignored and tracked (`SUPERSEDED` by D47)
`CLAUDE.md` became tracked at `912b32e` (2026-08-02), after its ignore rule
already existed. The rule did not hide tracked changes from `git status` or
prevent normal staging; the original handoff's claim otherwise was incorrect.
The release-version test did depend on its contents. D47 removes that redundant
assertion and retires the file, while Git history retains it as evidence.

### D24 · Local database moved from Docker to Homebrew `postgresql@16` (`ACTIVE`, machine-local)
2026-07-25. The corpus was migrated out of the Docker volume
`filing-digest_pgdata` into a Homebrew PostgreSQL 16 server on port 5432, with
row counts verified to match (8 / 13 / 1191 / 86). pgvector 0.8.4 had to be
**built from source** because `brew install pgvector` only builds for
postgresql@17/@18. Docker Desktop is still required on this machine for other
projects' MySQL volumes and must not be uninstalled.
`docker-compose.yml` and `backend/Dockerfile` stay in the repository because
they are what a fresh clone can reproduce; the Homebrew setup is a local choice,
not the project's story. **(conversation context, recorded in `CLAUDE.md`)**

### D25 · `httpx2` for the Starlette test client only (`ACTIVE`)
`89a8878` (2026-07-14). Starlette's TestClient needed a transport `httpx` no
longer provided; `httpx2` was added as a test-side dependency while **runtime
clients stayed on `httpx`**. Both are in `requirements.txt` with a comment
saying exactly this, so the pairing does not read as an accident.

### D26 · Versioned SQL migrations, without inventing history (`ACTIVE`)
`backend/db/migrations/0001_normalized_filing_snapshots.sql` upgrades a pre-v0.3
database. Two choices inside it matter: it **refuses to run** if `financials`
contains rows without a `filing_id`, because their Filing Identity cannot be
reconstructed honestly (`:25-32`); and it leaves `period_start`/`period_end`
NULL rather than deriving dates from period labels; re-ingestion enriches them
when the regulator provides real ones.

---

## 2026-08 · Depth, then closure

### D27 · DB password in `CLAUDE.md`: removed, then restored (`REVERSED`)
`912b32e` (2026-08-02) replaced the literal `filing_digest_dev` with an
instruction to source it from `backend/.env`. `b0b053e` restored the literal
**the same day**, because the value is a local-development default that already
sits in the committed `backend/.env.example`, and treating it as a secret made
every psql invocation two steps longer for zero security gain. The distinction
now stated in the global instructions: a credential that reaches a live system
is a secret; a committed local-dev default is not.

### D28 · Four-direction UI exploration lab (`EXPERIMENTAL`, none adopted)
`3d769fc` (2026-08-11) added `docs/design/explorations/`: a static comparison of
**A Ledger Focus**, **B Research Desk**, **C Signal Brief**, and **D Evidence
Thread**, twelve mock screens with adaptive-layout and motion rules. Direction A
(the safest refinement of what already shipped) is effectively what the Ledger
implementation became. B, C and D were never built. C in particular was rejected
implicitly because it "requires a defensible *what changed* model," which this
corpus does not have. The lab is kept as a comparison artifact, not a plan.

### D29 · Ledger implemented across the iOS client (`ACTIVE`)
PRs #1 and #2 (2026-08-11): presentation foundation, company index, company
folio, evidence sheets, then a `CompanyDirectory` module extracted out of
`SearchView`. PR #2's own reasoning is worth preserving: *"This creates a pure
in-process seam with no adapter or protocol. Deleting the module would spread
its query, ordering, and persistence rules back into the view."*

### D30 · Orchestration moved out of HTTP routes (`ACTIVE`)
PR #4 (2026-08-11): `cb0f09e` moved digest and answer orchestration into
`app/digests/` and `app/answers/`, `3e8d95c` unified DART and SEC ingestion
behind one normalized-filing pipeline (renaming `ingest/persist.py` →
`ingest/dart.py`), and `da38cb1` removed the compatibility scaffolding that
transition had needed. `routes.py` is now 130 lines of translation.

### D31 · The `embedding_dim` setting was a no-op and was deleted (`ACTIVE`)
`478aaf6` (2026-08-11). The real dimension is fixed by `vector(1024)` in
`init.sql` and the `EMBEDDING_DIM` constant in `models.py`; the *setting* could
be changed with no effect, which is worse than no knob. Removed from
`Settings` and `.env.example`. **Note:** this machine's `backend/.env` still
contains the dead variable; `extra="ignore"` in `config.py:23` swallows it.

### D32 · CI covers real PostgreSQL and a real simulator (`ACTIVE`)
PR #5 (2026-08-22). Before this, CI was lint plus the offline suite, so schema
drift and iOS breakage were invisible until a manual run. CI now boots a
`pgvector/pgvector:pg16` service, applies `init.sql` and a deterministic
smoke-seed fixture, runs both Python suites, and builds/tests the app on a macOS
runner. The live evaluation stays **out** of CI on purpose: it costs Solar calls
and needs an ingested corpus.

### D33 · Live evaluation made corpus-independent (`ACTIVE`)
PR #7 (2026-08-22). Retrieval cases had pinned database **UUIDs**, so
regenerating the corpus invalidated the eval map. `SearchHit.filing_period` now
comes from the owning filing row and cases compare canonical periods instead.
The harness reports `MISSING_FILING_PERIOD` and exits nonzero rather than
silently passing an unverified case. The regression test was written to fail
first, against fresh UUIDs with correct periods.

### D34 · Read-only GitHub Pages walkthrough (`ACTIVE`)
PR #8 / `f3e8dda` (2026-08-22). A live hosted demo was rejected for the same
reasons deployment was: no auth, model cost, and a local embedding model. The
compromise is a static page built from captured sessions with **explicit
no-live-API disclosure**, enforced by `backend/tests/test_portfolio_demo.py`,
which asserts no image source is remote and both disclosure strings are present.

### D35 · Bilingual metric labels moved from backend to iOS (`ACTIVE`, reverses earlier ownership)
`3321951` (2026-08-26) deleted `backend/app/financials/presentation.py`, dropped
`label_ko`/`label_en` from the `MetricCard` wire contract, and moved the mapping
into `ios/FilingDigest/Models/FigureDisplay.swift`. The backend keeps what only
it can know (canonical vocabulary, digest eligibility, authoritative values)
and the client owns presentation. Drift is prevented by exhaustive contract
tests on both sides against `contracts/financial-vocabulary.json`.
This is the change that forced the API contract version bump (D39).

### D36 · Reporting Period selection became semantic (`ACTIVE`)
`7b56b89` and `b2a05c1` (2026-08-26). Digests had been picking the "latest"
period by sorting label strings, which put `2024Q4` after `2024-annual`.
Selection now uses fiscal year, fiscal scope, period kind, and available source
dates, with **annual reports ranking above Q4 of the same fiscal year**; labels
are a deterministic fallback only after the semantic fields agree.

### D37 · Filing identity left the chunking layer (`ACTIVE`)
`e579e1d` and `48c16b5` (2026-08-26), formalized as
[ADR 0002](adr/0002-separate-citations-from-filing-sources.md). Chunking now
produces source-neutral chunks whose `FilingChunkLocation` carries only section
title, section order, and part index. DART receipt numbers and SEC accession
numbers stay on the enclosing Corporate Filing and are joined when evidence
needs them. `backend/app/filings/persistence.py` is the only place a typed
location becomes JSONB.

### D38 · A Citation is not a Filing Source (`ACTIVE`)
[ADR 0002](adr/0002-separate-citations-from-filing-sources.md). A Citation
points at one Filing Chunk with a bounded excerpt; a Filing Source is the
deduplicated, openable Corporate Filing behind it, ordered by first appearance.
This replaced an overloaded citation interface plus **client-side metadata
heuristics**: the client was guessing at source identity, which is exactly
where an evidence chain should not have guesses.

### D39 · API contract renumbered v0.3 → v0.4 (`ACTIVE`)
`af765ed` (2026-08-27). Not a redesign: the version moved because D35 removed
two fields from `MetricCard`, which is a breaking wire change. The database
schema stayed at v0.3, so existing local data remained compatible. That pairing
(app v0.5.1 / API v0.4 / schema v0.3) is why three different version numbers
appear in the docs. The **v0.5.0 GitHub release notes still say API v0.3**;
they correctly describe that release's contract.

### D40 · v0.5.1 is the final release; the contract is frozen (`ACTIVE`, cleanup exception in D48)
`507692d`, tag `v0.5.1`, GitHub Release published 2026-08-27. The release note
is unambiguous: *"the final release… no new features, database schema changes,
API contract changes, or refactors."* The README now defines maintenance
narrowly: security patches, dependency vulnerability fixes, documentation
corrections, dead-link repairs. The original architecture and release wording
justified the freeze with a present-tense downstream caller, but `filing-agent`
was only planned (D43). On 2026-09-05 the owner confirmed that the maintenance
policy and contract freeze stand independently of that deferred project.

### D41 · Dependabot enabled, then narrowed to security only (`REVERSED`)
`0c941cb` (2026-08-22) enabled weekly version updates for pip and GitHub
Actions, which promptly opened seven PRs (#9–#15). Eight days later `43b172b`
set `open-pull-requests-limit: 0` for both ecosystems. The reasoning is written
into the config: *routine version bumps are not inside the stated maintenance
policy, so disable them rather than widen the policy to match what the bot was
doing.* Security updates are configured separately in repository settings and
still open PRs.

### D42 · `sentence-transformers` 6.x rejected (`EXPLICITLY REJECTED`)
PR #14, closed unmerged 2026-08-30, the only unmerged PR in the repository. The
reason posted on the PR: `sentence-transformers` is the KURE-v1 loader, and a
3.x→6.x jump **cannot be validated by CI**, because CI never loads the embedding
model (`EMBEDDING_WARMUP_ENABLED=false`) and its corpus is seeded SQL. Verifying
it would require re-embedding the corpus and re-running the live evaluation.
`requirements.txt` still pins `>=3.0,<6.0`.

### D43 · `filing-agent` as a separate repository (`SUPERSEDED` by D49)
A downstream multi-turn agent that calls Filing Digest's five endpoints as
tools, keeping Filing Digest itself read-only. A 30 KB design document exists at
`~/Workspace/Projects/filing-agent/FOUNDATION.md` (written 2026-08-27, outside
this repository, not in version control). It records eight milestones,
three tool definitions mapped to the three read endpoints, and a set of
constraints derived from the frozen contract, notably that the closed
seven-metric vocabulary means a router must **refuse** out-of-vocabulary metrics
rather than hallucinate them, and that KO/EN labels are not transported so the
consumer must own its own display mapping.
The 2026-09-05 audit found only `FOUNDATION.md` in the adjacent directory, no
local Git repository or implementation, and a 404 for the expected GitHub
repository. The owner approved keeping the project deferred until explicitly
chosen for implementation. It remains a planned consumer; D40's contract freeze
does not depend on it. **(owner approval + local audit; design rationale from
conversation context and the local design file)**

### D44 · iOS simulators are resolved at runtime, never pinned by name (`ACTIVE`)
`fdb728b` (2026-08-30). `ci.yml` had pinned `name=iPhone 16 Pro`, which was not
installed on either the GitHub runner image or this Mac; two dependency PRs were
red for that reason alone, with nothing wrong in the code. CI now picks the
first available iPhone simulator and passes its UDID.
The workflow originally had string-assertion tests; D48 replaces those checks
with execution of the shared verification commands in CI.

---

## 2026-09 · Landing page polish and takeover

### D45 · One fluid scale between two approved layouts (`ACTIVE`)
`5be287e` → `b4c536f` (2026-09-01/02). Size tokens on the Pages landing page had
been split across a base rule and two breakpoints, so a 681px window rendered a
*smaller* headline than a 402pt phone. Every size token is now derived as a
single straight line through the two layouts that were signed off (the 402pt
phone and the 1700px desktop), clamped at both ends, with breakpoints changing
arrangement only. Both anchors still render pixel-identically to the approved
designs. The follow-up commit fixed the overflows this surfaced, found by
sweeping renders across 28 viewports.

### D46 · `CLAUDE.md` trimmed of dated measurements (`SUPERSEDED` by D47)
`4b8855d` (2026-09-02). Removed one-off measurements
(startup timings, HF request counts, a specific PostgreSQL patch version,
a migration-date row count) and collapsed duplicated port rules. Rationale: a
measurement taken once becomes a false claim the moment the environment moves;
rules should be stated once. Those numbers are preserved in this file's D24 and
in git history, which is where dated facts belong.

### D47 · Clean-slate Codex takeover and retirement of `CLAUDE.md` (`ACTIVE`)
*Partly superseded by D50 (handoff location and `CLAUDE.md`).*
Owner-approved on 2026-09-05 after independent source, Git, test, database, and
GitHub inspection. Retire `CLAUDE.md` and remove its redundant release-version
assertion; the existing package, README, architecture, SEC user-agent, and iOS
checks remain. Track a minimal root `AGENTS.md` containing verified project
commands and invariants.

Evidence precedence is current source/tests, current Git state/history, this
ledger, ROADMAP, PROJECT_HANDOFF, then historical Claude material when needed.
The Claude environment inventory remains an archive. No additional Claude
instructions, skills, MCP servers, hooks, subagents, or preferences are migrated
without an explicit request. Persistent configuration is considered only for a
repeated, demonstrated limitation, using the smallest suitable mechanism.

This ledger records significant decisions and reversals; ROADMAP records material
roadmap changes; PROJECT_HANDOFF changes only with material high-level project
state or architecture changes. Routine implementation details do not belong in
these documents.

### D48 · Bounded engineering cleanup (`ACTIVE`)
Owner-requested on 2026-09-05. This pass explicitly permits safe refactoring,
performance improvements, deletion of unused implementations, and improvements
to local/CI verification despite D40's earlier no-refactors rule. The API v0.4
and schema v0.3 contracts, local-only deployment, and deferred feature scope
remain unchanged. This does not reopen routine dependency updates or authorize
new product features.

Run persistence behavior tests against disposable databases in CI and locally,
using the checked-in SQL schema. Prefer those checks over assertions about
private helpers and workflow text. Retire the unused operating-margin calculator;
keep its vocabulary value for wire compatibility. Financial numbers and source
provenance retain their existing contracts.

---

## 2026-09-09 · Release-readiness review

### D49 · Verify both sister projects before maintenance handoff (`ACTIVE`)
The owner approved a comprehensive release-readiness audit, review and merge
of pending work in both repositories, and a staged Digest coverage expansion.
First qualify one additional Korean and one US company in an isolated database;
expand toward ten additional companies only if the pilot succeeds without
substantial parser changes. Preserve the existing corpus and keep Agent's
qualified snapshot unchanged. Arbitrary-company discovery and in-app ingestion
remain optional proposals, not release requirements.

Filing Agent is now implemented and its recorded public replay is deployed.
It uses a separately qualified snapshot rather than five live Digest API tools.
This supersedes D43's deferral and proposed integration; D43 retains its dated
context. API v0.4 and schema v0.3 remain unchanged.

Audit findings precede general remediation. New feature proposals must explain
their portfolio value, cost and maintenance burden before approval. Resolve
critical/high defects and core-workflow failures before handoff; explicitly
accept or resolve medium findings and keep minor polish from extending the
project indefinitely. Record unavailable checks as unverified.

### D50 · Agent handoff in private memory; `CLAUDE.md` tracked (`ACTIVE`)
Owner decision on 2026-10-28, applied to every repository. `docs/PROJECT_HANDOFF.md`
moved to the private, git-ignored `.memory/` folder shared by Claude Code and Codex;
current state and the next step live in `.memory/handoff.md`. The evidence order is
current source/tests, current Git state/history, this ledger, ROADMAP, then
`.memory/handoff.md`. `CLAUDE.md` is tracked again as a single `@AGENTS.md` import so
both tools read the same rules; `AGENTS.md` stays the only source.

## D50 · Release remediation and ten-company expansion (`ACCEPTED`)

On 2026-09-09 the owner approved D49's remediation sequence and requested company
expansion immediately. The bounded SEC pilot succeeded after generic heading
repairs; LG Chem additionally exposed doubled XML attribute quotes. Ten new
companies passed regulator-value and bilingual retrieval checks in isolation,
then were added without changing original rows. See [coverage](COVERAGE.md).

The approved follow-up includes financial-expression guard regressions, loopback
network defaults, host validation, locked dependencies, migration/restore tests,
CI protection and native accessibility fixes. No API/schema change, public live
service or automatic Filing Agent snapshot expansion is introduced. Preserve the
recorded demos and document generation/accessibility limits honestly.

## D51 · Bilingual public walkthrough (`ACCEPTED`)

The owner selected the original-style Korean design after comparing five local
studies, then approved publication. The existing page structure and captured
app footage remain. Korean titles use Nanum Myeongjo ExtraBold, with the hero
sharing the English maximum display scale. Titles in both languages omit periods;
each scope-band cell centers its heading and supporting line.

The visible Korean/English toggle supports direct `?lang=ko` and `?lang=en`
links. An explicit link overrides the saved browser preference; otherwise the
browser language determines the first visit. Theme preference is also local.
Blocked browser storage does not prevent either control from working. Fonts are
bundled with their licenses. This is still a recorded walkthrough with no live
question API; it does not claim a new recording of the expanded corpus.

## Local browser request boundary · 2026-09-09

Reject requests with a foreign or invalid Origin, or cross-site/same-site Fetch Metadata,
before route dependencies can access PostgreSQL, embeddings or Solar. Compare
scheme, host and effective port; retain TrustedHost validation. This applies to
GET routes too, because a digest cache miss can initiate model work.

Sibling origins are not trusted, including another port on localhost.
Native iOS and command-line requests without browser headers remain supported.
Same-origin browser requests remain supported. This is browser request hardening,
not authentication: the API remains a single-owner local service and must not be
exposed publicly. No database schema, corpus, financial contract or iOS change is
needed. Regression tests cover rejection before dependencies and successful
native/same-origin routing.

## D52 · The digest language toggle also drives app chrome (`ACCEPTED`)

2026-09-29. D19 stands: there is no device-locale localization and no String
Catalog. The digest's existing KO/EN toggle is still the only language control;
it now also switches the answer screen, evidence sheet, figure rows and company
header, and is passed into `AnswerView`. English mode suggests English
questions because `/answer` narrates in the question's language. Korean output
is unchanged. The search screen has no toggle and stays Korean, and transport
and evidence-validation error text is still Korean.

## D53 · Filing family walkthrough alignment (`ACCEPTED`)

Date: 2026-10-01. The walkthrough adds a “Works with Filing Agent” section that
mirrors Filing Agent's family block: Digest reads a filing as a whole, Agent
follows one figure back to its cell. The Agent card carries Agent's brown rule
(`--agent`), as Agent's site carries Digest's green.

Interface text sizes move onto steps shared with Filing Agent
(`--text-caption` .75, `--text-xs` .8125, `--text-sm` .875, `--text-base` 1,
`--text-md` 1.125, `--text-lg` 1.375 rem). The fitted `--step-*` display lines
are unchanged. Distinct rendered sizes per screen drop from 17–19 to 12–13.
Korean evidence-section translations are scoped to `#evidence` so they cannot
overwrite other card grids. Device-frame radii remain because they depict
hardware, not interface.

## D54 · Shared family number rules, search language and glossary (`ACCEPTED`)

2026-10-01. Approved with the Filing family revamp report. Supersedes D52's
sentence that the search screen has no toggle and stays Korean.

- Numbers follow Filing Agent's rules. Negatives use U+2212. Korean dollar
  amounts read in whole 억 달러 (`3,910억 달러`). The Korean fiscal-year label
  is `2025 회계연도`. When an exact won figure is abbreviated, a third line
  restates it in 조/억/만 units without rounding (`258조 9,354억 9,400만 원`).
- The search screen gains a toggle that names the other language. Search owns
  the language state and passes it to the digest as a binding, so a choice
  carries in both directions. The choice is not persisted; each launch starts
  in Korean, as before. D19 stands: no device-locale localization.
- `contracts/family-glossary.json` holds metric and company names in both
  languages and is kept identical to Filing Agent's `slice/web/src/glossary.json`.
  A contract test checks `FigureDisplay` and `Company` against it. English
  metric names move to sentence case (`Operating income`) to match.

## D55 · Links into Filing Agent's ledger (`ACCEPTED`)

2026-10-02. G2 from the Filing family revamp report.

- When a company is covered by Filing Agent's public ledger, the digest's
  Filing Sources section and the answer evidence sheet show a "Filing Agent
  수치 장부 / ledger" row. It opens `https://filing-agent.vercel.app/?lang=<ko|en>#ledger/ledger-<ticker>`
  in Safari, in the reader's current language.
- The ledger holds earlier fiscal years (2022–2024) than Digest's latest
  annual filings, so the row names the years it covers instead of claiming
  the same figure. Citations are text passages, so the link goes to the
  company's ledger section, not to a single row.
- `ledger_years` in `contracts/family-glossary.json` lists the covered
  companies and years. Filing Agent's test derives it from its ledger;
  Digest's contract test checks `AgentLedger.years` against it.

## D56 · Gemini Flash-Lite replaces Upstage Solar (`ACCEPTED`)

2026-10-03. The Upstage free credit ran out and every Solar call returned 403.

- The narrative model is now `gemini-3.5-flash-lite` through Gemini's
  OpenAI-compatible endpoint. The adapter was already provider-neutral in
  behavior, so it was renamed to match: `app/llm/chat_completions.py`,
  `ChatCompletionsClient`, and `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`.
  Prompts, schemas and guards are unchanged.
- Flash-Lite was chosen over the full Flash models because of the free limits
  shown in AI Studio that day: Flash allowed 5 requests a minute and 20 a day,
  Flash-Lite 15 a minute and 500 a day.
- The 24-case golden set passed 24/24 on Flash-Lite, with all 14 full cases
  returning a cited narrative.
- The eval harness now fails any case blocked with `narrative_unavailable`,
  and takes `--delay` to pace full cases. Before this, a rate-limited call
  could pass as a safe `blocked` state.
- Earlier entries and reports that name Solar describe runs made on Solar and
  are left as written.

## D57 · Close the portfolio baseline for maintenance · 2026-10-06

The owner approved finishing both Filing projects and moving to interview study.
v0.5.2 is a claim-accuracy/documentation patch release. API v0.4 and schema v0.3
remain frozen. The local single-user backend remains private; GitHub Pages keeps
the recorded walkthrough. Maintenance fixes/security/documentation remain allowed;
new features or wider coverage need owner reopening. Independent semantic review,
fresh live rehearsal and physical-device/full accessibility are explicitly deferred,
not release claims. Current API description and README now match the bounded checks.

## Standing non-goals (`EXPLICITLY REJECTED`)

Each was considered and declined on the record, not merely skipped:

| Non-goal | Why |
|---|---|
| Authentication, rate limiting, multi-tenancy | Single-user local demo; adding them would be theater |
| Production deployment / Kubernetes | The story is local Docker + host uvicorn; a hosted instance costs money and leaks an unauthenticated API |
| Alembic | D4: one schema source |
| DART `xforms` parsing and attachment ingestion | Detected and skipped deliberately; a different parser project |
| Financial and holding companies in the corpus | D15: IFRS financial-sector account mapping is its own project |
| An in-app conversational chat surface | D8: removed once `/answer` was real, and never reinstated |
| Device-locale localization | D19: the in-app KO/EN toggle is the bilingual mechanism (extended to chrome by D52) |

## D58 · Same-end SEC durations and maintenance qualification · 2026-11-04

SEC 10-K company facts can include annual and quarterly durations ending on the
same date. For one accession/metric/end, prefer the earliest valid known start
before the existing tag preference. This prevents quarterly input order from
silently winning over an available annual fact. Keep existing comparative-year
selection and missing-date fallback; this does not certify quarter-only data as
annual or invent dates. No corpus re-ingestion, schema migration or API change.

The authorized maintenance audit also hardens provider/evidence failure paths,
finite Financial Facts and DART exception redaction, qualifies four security
pins, and improves the recorded site's accessibility, truthful scope copy and
lossless font delivery. The local single-user boundary and deferred semantic
qualification remain. See [audit evidence](audits/2026-11-04-product-audit.md).

## D59 · Filing Footnote: event filings in scope · 2026-11-17 (`PROPOSED`)

Filing Footnote, the merger of Filing Digest and Filing Agent, covers annual
reports and event filings with a deterministic category list and structured
facts only. See [ADR 0004](adr/0004-event-filings-in-scope.md).

## D60 · Filing Footnote: neutrality guards · 2026-11-17 (`PROPOSED`)

Generated prose has no digits, no banned evaluative words, no predictions and
no advice; statements are attributed to the company; failures are withheld;
the LLM reviewer is advisory; the owner approves what ships. See
[ADR 0005](adr/0005-neutrality-guards.md).

## D61 · Filing Footnote: bundled SQLite with exact decimals · 2026-11-17 (`PROPOSED`)

A read-only SQLite file built on the owner's Mac replaces the PostgreSQL
service at run time, and exact decimals supersede the floating-point
year-over-year path. See
[ADR 0006](adr/0006-bundled-sqlite-with-exact-decimals.md).

## D62 · Filing categories accepted · 2026-11-17 (`ACCEPTED`)

D59 is accepted with the owner's changes from the M1 sample: a separate unit-sales
category, subsidiary filings kept and flagged, and no per-company limit. The list
and rules are in `contracts/filing-categories.json`. See
[ADR 0004](adr/0004-event-filings-in-scope.md).

## D63 · Neutrality word lists accepted · 2026-11-17 (`ACCEPTED`)

D60 is accepted. The owner reviewed the M5 lists and approved the recommended
additions: more hype words, forecast endings, advice phrases and spelled figures.
"Will", "would", "set to", "outstanding", "accumulated" and "half" stay allowed,
because factual filing lines use them. The lists, each narrowing and each
extension are in `contracts/neutrality-lexicon.json`. See
[ADR 0005](adr/0005-neutrality-guards.md).

## D64 · v0.1 build defaults · 2026-11-17 (`ACCEPTED`)

Summary model superseded by D68.

The owner accepted the build plan's defaults:
- SEC event filings show only what code can verify, with a link to the original
  for figures.
- The build database is a fresh Compose PostgreSQL on port 5433, re-ingested from
  the regulators.
- Annual "at a glance" passages are chosen by section heading, not embedding
  search.
- CI runs the backend job on every PR; the macOS job is manual only.
- The bundle covers the latest 12 months with no per-company cap. Summaries use
  `gemini-2.5-flash-lite` on the paid tier, so filing text is not used for product
  improvement.
- SEC Item 1.05 (cybersecurity incident) stays in the legal category (소송).

## D65 · DART correction chains · 2026-11-17 (`ACCEPTED`)

A DART correction states the original's name and first filing date, but not its
receipt number. Ingest links a correction to the one in-scope, non-correction
filing that matches it on four things: company, base report name, subsidiary
flag and that date. Otherwise the correction is stored as unlinked, with a note,
and no link is guessed. Excluded corrections are not resolved. Only the newest
member of a chain is shown, and never when DART's `rm` field marks it 정 (since
replaced). A run that cannot read a body keeps the stored link and
classification. Structured facts attach to the filing DART returns them for,
which is the newest version.

## D66 · Bundle scope for annual reports · 2026-11-17 (`ACCEPTED`)

PRODUCT.md promises "latest annual results" and lets a figure show "earlier
years". The bundle therefore includes every annual report, filed on or before
the build date, that is the source of an exported figure, keeping only the
newest version for each company and year. Only each company's latest annual
report needs owner-approved summaries; older annual reports serve as figure
sources only. Event filings follow D64 and D65. A release build re-checks every
figure and fact against pinned regulator responses and re-runs the neutrality
guard, and it never relies on the build's own flags. ADR 0006 is accepted with
this milestone; the file format is described in `docs/build-bundle.md`.

## D67 · Annual summary sections and their sources · 2026-11-17 (`ACCEPTED`)

The latest annual report's summaries cover four sections: `one_line`, `business`,
`changes` and `risks`. Each is written from the report's own text, picked by
section heading, never by search. `risks` uses only a heading the company gives
to its business or investment risks (SEC Item 1A; DART headings such as
투자위험 or 위험요소), never 위험관리 및 파생거래, which covers hedging. A report
without such a heading has no `risks` summary, and none is required for it; the
build does not write one from other text. One shared rule in
`backend/app/build/model.py` decides the sections for both the summary step and
the exporter. A summary's key covers its source text, prompt version, model,
section and lexicon version, and a release refuses an approved summary whose key
no longer matches the current source.

## D68 · Groq replaces Gemini for build-time summaries · 2026-11-18 (`ACCEPTED`)

The owner chose Groq `qwen/qwen3.8-27b` for the build-time summaries, replacing D64's
`gemini-2.5-flash-lite`. That Gemini model returned HTTP 404 for a new account, and
`gemini-3.5-flash-lite` returned HTTP 503. A three-filing pilot on Groq passed the
neutrality guard. Groq's data-use terms were not checked; the filings are public.

- The settings and the exporter default to Groq's OpenAI-compatible endpoint and this
  model. Prompts, schemas, the guard and the reviewer are unchanged.
- The free tier limits output tokens per minute to 1000 and checks `max_tokens` against
  that limit before it generates. Summaries ask for at most 768 tokens and reviews for 512.
  The command line waits 61 seconds between calls (`--call-interval`).
- A request refused with HTTP 429 waits 61 seconds and is sent once more. It does not count
  against `--max-calls`, because nothing was generated. A second refusal stops the run.
- Prompt version `m6-2026-11-18-a`: an event summary names the people the filing names
  (romanised in English, family name first), and no line repeats another line's fact.
- Groq has no price table here, so the cost reads "cost unknown".

## D69 · Source text cap per regulator · 2026-11-18 (`ACCEPTED`)

Groq's free tier refused the first Hyundai Motor annual-report request with HTTP 413: the
input-token limit is 7000 a minute, and the request needed 7274. In the pilot, Korean took
about 0.5 to 0.65 tokens a character and English about 0.22, on top of about 1200 prompt
tokens; a retry adds about 500.

- Source text is cut at 7000 characters for DART and stays at 12000 for SEC. A Korean
  request with a retry stays under about 6300 input tokens.
- A request refused with HTTP 413 skips that filing section and the run goes on; the
  command line lists it as `too_large`. Sending it again cannot succeed.
- The shorter DART text changes the cache key of every DART summary. None was approved.
- Groq's paid Dev Tier would raise the limit; that is the owner's call.

## D70 · Prompt version m6-2026-11-18-b · 2026-11-18 (`ACCEPTED`)

The second pilot (13 summaries) showed four prompt gaps. The owner agreed to fix them
before the full run, because a later prompt change would re-run every summary.

- Apple's earnings 8-K wrote 4분기 (N1). A line no longer says which quarter, half or year.
  Writing the number out in words would also fail N1.
- Apple's 10-K wrote 대만 for Greater China, and neither the guard nor the reviewer caught
  it. Names of places, regions, segments and products are kept as the filing gives them.
- Microsoft's director 8-K wrote ~할 것이라고 (N3). Anything the filing says will happen
  uses the plan forms.
- Apple's one-line summary ran past the length limit in both languages (N6). It now names
  at most three products or businesses.

## D71 · Output that never becomes valid JSON skips the section · 2026-11-18 (`ACCEPTED`)

On prompt `m6-2026-11-18-b`, the Samsung share-disposal summary (156 output tokens on the
previous prompt) ran past the 768-token cap, and Groq returned HTTP 400
`json_validate_failed`. Output varies from run to run, so this can happen to any section.
That error now skips the filing section and the run goes on; the command line lists it as
`invalid_output`. Nothing is cached, so the next run tries it again. Any other HTTP 400
still stops the run.

## D72 · Event scope: the latest five per company · 2026-11-18 (`ACCEPTED`)

The owner decided that the app shows the latest five events per company.

- One function, `app.build.export.event_scope`, picks the exported events. The exporter and
  `summaries.select_targets` both call it, so the summary targets and the bundle cannot
  disagree.
- The rule: filed in the 12-month window, not excluded, the shown version of its correction
  chain, with a stored body text, then at most five per company. The five are the newest
  by `filed_on`, ties broken by `filing_key` descending. A corrected chain counts once.
- An event with no stored body text can never get a summary. It is left out of the export,
  does not count toward the five, and the build report lists it
  (`event_filings_without_body`). Events dropped by the cap are counted per company in
  `event_filings_over_cap`.
- `PRODUCT.md` says "23 filings"; that line is now out of date. The owner approves
  product-truth edits, so it is not changed here.
- The exporter's default prompt version is the summary build's `PROMPT_VERSION`
  (previously the placeholder `none`, which a release refuses). The constant moved from
  `app/build/summaries.py` to `app/build/model.py` so the exporter can read it without
  importing the summary build, which imports the exporter. `summaries.PROMPT_VERSION` is
  still available as an import of that constant.
- A database build reads owner-approved rows from `backend/data/summaries/approved.jsonl`
  (`source.read_summaries`); a missing file means no approved summaries. A release names
  every approved row whose input hash no longer matches and fails.

## D73 · Ingest takes a corrected annual report · 2026-11-18 (`ACCEPTED`)

Ingest picked the newest title starting with 사업보고서, so a corrected report titled
[기재정정]사업보고서 was never ingested. DART's statements API (fnlttSinglAcntAll) returns
only the newest version's rows, so the original could never match its pinned figures.
On the real data, LG Electronics and Samsung Biologics failed the build.

- Ingest strips the DART correction prefix (`correction_prefix_pattern` in
  `contracts/filing-categories.json`) before it checks the title, so the newest version
  wins, as the export's annual scope already does (D66).
- The inherited test that rejected [기재정정] on purpose is replaced; a correction is
  marked `is_corrected` in the bundle rather than refused.
- Both companies were re-ingested; a development bundle now builds on the real data
  (18 companies, 108 filings, 127 figures).
