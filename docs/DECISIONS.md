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

## D74 · N1 catches named quarters and halves · 2026-11-18 (`ACCEPTED`)

The second pilot wrote "fourth quarter" (Apple) and "third quarter" (Tesla) in English, and
N1 let them through: it catches digits and spelled amounts, not ordinals. Prompt
`m6-2026-11-18-b` already says a line does not name the quarter, half or year (D70). The
owner approved adding them to the N1 lexicon.

- English: first, second, third or fourth followed by quarter or half, with a space or a
  hyphen. "second largest" and "first review" still pass.
- Korean: 일분기, 이분기, 사분기 written without a space (삼분기 was already listed),
  상반기 and 하반기. "이 분기" (this quarter) and plain 분기 still pass.
- Lexicon version 2. It is part of the summary cache key, so every summary is generated
  again; none was approved.
- Two bad fixtures that use 하반기 as prediction examples (N3) now trip N1 as well.

## D75 · US net income means the parent's share, as DART's does · 2026-11-18 (`ACCEPTED`)

SEC's `NetIncomeLoss` is net income attributable to the parent, but the mapper stored it as
`net_income`, while DART stores the consolidated total (`ifrs-full_ProfitLoss`) there and
the parent's share as `net_income_attributable`. The same key meant two things. Five US
companies also had no Korean name, so their `name_ko` fell back to the English name.
The owner approved the mapping and the names (2026-11-18, owner: "1 yes").

- SEC `NetIncomeLoss` now feeds `net_income_attributable` for all nine US companies.
- SEC `ProfitLoss` feeds `net_income` only where a company reports it. In the pinned data
  Walmart and Tesla report it for every year; Costco reports it through FY2025, but its
  FY2026 10-K does not, so Costco's latest year has no `net_income`. The other six have no
  `net_income` figure. There is no fallback between the two tags.
- The company digest's metric list (`backend/app/digests/metrics.py`) has `net_income` but
  not `net_income_attributable`, so after re-ingest its net income card disappears for
  those US companies.
- `net_income_attributable` was already in `contracts/financial-vocabulary.json` and the
  Swift enums; no vocabulary change.
- `contracts/family-glossary.json` gains 아마존, 코스트코, 알파벳, 메타 and 월마트; the iOS
  Korean display names match. A test asserts every glossary company has a Hangul name.
- Stored figures change only on re-ingest; the pinned files are untouched.

## D76 · Official company filings: wider event scope, ten per company, a notices row · 2026-11-19 (`ACCEPTED`)

The owner wants as many official company filings about outlook and decisions as the app can
show (2026-11-18/19, owner). Supersedes the cap of D72 (five); D72's other rules stand.
Detail in [ADR 0007](adr/0007-notices-and-wider-event-scope.md). The owner approved the
categories, the cap and the six mapping calls below (2026-11-19, owner: "I approve all
recommendations. Yes for all 1-5").

- `contracts/filing-categories.json` version 2. Seven new event categories, counted toward
  the cap and summarised later: 회사 전망 / Company outlook (`outlook`: 장래사업ㆍ경영계획,
  영업실적등에대한전망), 주주가치 / Shareholder value (`shareholder_value`: 기업가치제고계획,
  수시공시의무관련사항), 주주총회 / Shareholder meeting (`meeting`: 정기·임시주주총회결과,
  SEC Item 5.07), 생산·사고 / Operations (`operations`: 중대재해발생, 생산중단, 생산재개),
  대여·보증 / Loans and guarantees (`lending`: 금전대여결정, 타인에대한채무보증결정,
  타인에대한담보제공결정, 파생상품거래손실발생), 경영사항 / Management matters
  (`management`: 기타경영사항, 투자판단관련주요경영사항, SEC Item 5.03), 해명 /
  Clarification (`clarification`: 풍문또는보도에대한해명, 조회공시요구에대한답변).
  매출액또는손익구조30%(대규모법인은15%)이상변경 joins `earnings`: it states the year's
  revenue and profit against the prior year.
- 수시공시의무관련사항(공정공시) is a generic name. The five read on DART (Kia, LG Chem,
  NAVER, Samsung Electronics, SK hynix) all announce shareholder-return plans, so it is
  `shareholder_value` (owner approved).
- Company outlook is always attributed to the company and labelled as its outlook, and is
  never used in a comparison.
- Notices form a separate kind (`notice_categories`), not an exclusion: IR events, record
  dates (including 기타경영사항 titled 배당기준일 변경 안내), shareholder-meeting notices,
  results-date notices, audit, governance and sustainability report notices, the compliance
  program, other notices and exchange inquiries. The bundle lists them in a new `notices`
  table (schema version 2): id, company, category, title, date, link. The app shows them as
  one grouped "안내 공시 N건 / N notices" row per company. They need no body, are never
  summarised and never count toward the cap. They follow the same window and shown-version
  rules as events; ingest does not chain them, so a notice marked 정 is hidden and its
  correction shown.
- The cap is ten events per company (`EVENT_CAP`), with D72's window, shown-version and
  body rules unchanged.
- Still out of the list: ownership reports (DART 소유상황·대량보유 reports) and SEC
  Rule 10b5-1 trading plans, which a later structured insider and ownership section covers;
  SEC exhibits-only, listing-standard (3.01) and rights-change (3.03) filings, 7.01/8.01
  text with no keyword, and proxy statements (not listed at all).
- Quarterly figures are a later structured section, not event summaries.
- Rows stored as excluded before this change carry old reason keys until the next ingest,
  which classifies every listed filing again and fetches the body of each one now in an
  event category. An export over a database not yet re-ingested fails on the unknown reasons.
- Approved mapping calls: the 30% change filing counts as `earnings` (a second results row
  can share a date with the preliminary results); 수시공시의무관련사항 is `shareholder_value`;
  기타경영사항(배당기준일변경안내) is a record-date notice; SEC 5.03 is `management` and
  5.07 wins over it; derivative losses sit under Loans and guarantees; a corrected notice
  shows only its corrected version.
- `PRODUCT.md` now says up to ten filings, with the filing-first flow and the company
  outlook rule (owner approved, 2026-11-19).

## D77 · Predecessor site removed · 2026-11-19 (`ACCEPTED`)

D59 to D61 were already accepted by D62, D63 and D64, so this entry records only the
removal. The public GitHub Pages site under `docs/` (`index.html`, `contact.html`, their
scripts, styles, fonts, favicon, social preview and captured screenshots) described
Filing Digest and linked to Filing Agent. A portfolio reviewer must see Filing Footnote
only, so the site and `backend/tests/test_portfolio_demo.py` (which asserted it) are
deleted; the repository history keeps them. `docs/screenshots/verification/` stays as a
dated record.

- `docs/ARCHITECTURE.md`, `DEVELOPMENT.md`, `ENGINEERING_AUDIT.md`, `COVERAGE.md` and
  `dart-api-notes.md` get a one-line history banner and nothing else; `CONTEXT.md` is
  retitled Filing Footnote.
- The README status section now says Filing Footnote is in development.
- `.github/dependabot.yml` drops the "closed for maintenance" wording.
- Not changed: the `filing_digest` database, user and password defaults in
  `docker-compose.yml`, `.github/workflows/ci.yml` and `backend/app/config.py`. They are
  local-development defaults that existing Compose volumes and local `.env` files depend
  on; a rename waits for the backend replacement.
- The `filing-agent.vercel.app` link in the iOS ledger row (`ios/`) is outside this
  change and remains until the app is replaced.

## D78 · Table filings get their figures from the table and a template summary · 2026-11-19 (`ACCEPTED`)

The owner approved the approach on 2026-11-19: a filing whose content is a regular table gets
its figures from that table and its summary lines from a fixed template, with no model call.
The owner then delegated the remaining calls to Claude (2026-11-19, owner: "Full permission to
keep going"); the lead accepted this entry under that delegation. Every template summary still
needs the owner's approval, filing by filing, before it ships.

- `contracts/filing-facts.json` version 2 adds a `documents` block: five tables read from the
  filing's own `document.xml` body by `app.clients.dart_tables`. `results` (잠정실적:
  연결재무제표기준영업(잠정)실적 and 영업(잠정)실적 classified `earnings`), `change`
  (매출액또는손익구조30%(대규모법인은15%)이상변경), `units` (영업(잠정)실적 classified
  `unit_sales`), `dividend` (현금ㆍ현물배당결정) and `outlook` (영업실적등에대한전망 and its
  연결 form, with each correction's before and after value). 장래사업ㆍ경영계획 is prose, not
  a table: it has no facts and the model summarises it.
- Values are exact `Decimal` in the unit the filing states (백만원, 조원, 억원, 천원, 원, 대,
  %, 대수). `-` gives no fact. A table without the expected shape, or a number cell that does
  not parse, gives no facts at all, and the model writes the summary. Facts go in
  `filing_facts` as today; no schema change and no migration.
- Columns are found by their header text, never by position: 당기실적, 전기실적 and
  전년동기실적 in the results and monthly sales tables, 당기누적 and 전년동기누적 in the
  cumulative sales table. The results table's second header row must account for every data
  column (a 대비 heading covers its 증감율 and any 흑자적자전환여부 column). A heading that is
  missing or listed twice, or a row whose width differs from its header, gives no facts.
- A correction's changed items (the 정정항목 | 정정전 | 정정후 block, up to the first row of
  fewer than three cells) are never read as the form: the 30% change and dividend forms are
  read after it, so a `-` in the form gives no fact rather than a value from that block.
- An outlook item's unit is a known unit (조원, 억원, 백만원, 천원, 원, 대, 대수, %) in its
  last parentheses, such as 대수 for 판매목표(대수), or the table's unit when the row is a
  results metric (매출액(연결)). Any other row, such as a ratio with no unit (영업이익률), is
  not stored. A table whose own unit is not known gives no facts.
- Origin in the bundle: `dartdoc:<table>.<key>`. The pinned check re-reads
  `dart/document/<rcept_no>.xml` with the same parser. Ingest with `--save-pinned` writes that
  file for each filing whose table gave facts. A release therefore needs one re-ingest with
  `--save-pinned` before it can verify these facts.
- Templates (`app.build.templates`, version `t1-2026-11-19`) are staged by `generate` with
  model `template`, `prompt_version` set to the template version and no reviewer flags, and
  logged to `calls.jsonl` with cache `template`. The guard (N1 to N8) decides staged or
  withheld. Only the owner approves them; `--all-reviewed` skips them because they have no
  reviewer result. The cache key is the template's input (table, category, title, correction
  flag, caveat flag, facts) with model `template` and the template version, so a wording
  change restages every template summary.
- Direction words compare the table's current value with the prior one as `Decimal`. When the
  prior value is zero or negative, the line states only that both figures were disclosed. No
  percentage is written. Outlook lines only attribute and never compare with results.
- The event prompt gains guidance for outlook filings no template covers, clarification,
  management, shareholder_value, meeting, operations and lending. The outlook guidance tells
  the model to write outlook, target or plan, never forecast.
- The event prompt is versioned apart: `EVENT_PROMPT_VERSION` `m6-2026-11-19-a` keys event
  summaries and `PROMPT_VERSION` stays `m6-2026-11-18-b` for annual sections, so this change
  keeps every annual summary. The exporter takes `--event-prompt-version` beside
  `--prompt-version`, and a release refuses `none` for either. The bundle's `build_meta`
  still records only `prompt_version`.
- Exported DART scope on 2026-11-19 after a re-ingest: earnings 17 templated, unit_sales 7,
  dividend 4, outlook 2 templated and 4 by the model (장래사업ㆍ경영계획).

Template wording. {M} is 매출액/revenue or 영업이익/operating income; base is 전년 같은 기간 /
the same period a year earlier (results, units) or 직전 사업연도 / the previous fiscal year
(change).

| Line | Korean | English |
|---|---|---|
| Results 1 | 회사는 [연결 기준 ]잠정 실적을 공시했어요 | The company disclosed preliminary results[ on a consolidated basis]. |
| Results 1, correction | 회사는 [연결 기준 ]잠정 실적을 고쳐 다시 공시했어요 | The company filed corrected preliminary results[ on a consolidated basis]. |
| Change 1 | 회사는 [연결 기준 \| 별도 기준 ]매출액 또는 손익구조 변동을 공시했어요 | The company disclosed a change in revenue or profit structure[ on a consolidated basis \| on a separate basis]. |
| Change 1, correction | 회사는 [연결 기준 ]매출액 또는 손익구조 변동 내용을 고쳐 다시 공시했어요 | The company filed a corrected disclosure of a change in revenue or profit structure[ on a consolidated basis]. |
| Results and change 2, 3: up | 회사는 {M}이 {base}보다 늘었다고 밝혔어요 | The company said {M} increased from {base}. |
| down | 회사는 {M}이 {base}보다 줄었다고 밝혔어요 | The company said {M} decreased from {base}. |
| same | 회사는 {M}이 {base}와 같았다고 밝혔어요 | The company said {M} was unchanged from {base}. |
| prior zero or negative | 회사는 {M}과 {base}의 {M}을 함께 공시했어요 | The company disclosed {M} together with the figure for {base}. |
| Units 1 | 회사는 잠정 판매 실적을 공시했어요 | The company disclosed preliminary unit sales. |
| Units 1, correction | 회사는 잠정 판매 실적을 고쳐 다시 공시했어요 | The company filed corrected preliminary unit sales. |
| Units 2 | 회사는 전체 판매 대수가 전년 같은 기간보다 늘었다고 / 줄었다고 밝혔어요; 같았다고; or 회사는 전체 판매 대수와 전년 같은 기간의 판매 대수를 함께 공시했어요 | The company said the total number of units sold increased / decreased / was unchanged from the same period a year earlier; or The company disclosed the total number of units sold together with the figure for the same period a year earlier. |
| Units 3 | The same with 누적 판매 대수 (the year to date) | The same with the cumulative number of units sold |
| Dividend 1 | 회사는 [분기 \| 중간 \| 결산 ]현금 배당을 결정했어요 (현물 배당 for 현물배당) | The company decided on a [quarterly \| interim \| year-end ]cash dividend. (dividend in kind) |
| Dividend 1, correction | 회사는 [분기 ]현금 배당 결정을 고쳐 다시 공시했어요 | The company filed a corrected decision on a [quarterly ]cash dividend. |
| Dividend 2 | 회사는 보통주[와 종류주]의 주당 배당금[과 시가배당률]을 밝혔어요 | The company stated the dividend per share[ and the dividend yield] for common shares[ and other share classes]. |
| Dividend 3 | 회사는 배당금 총액, 배당 기준일과 지급 예정일을 밝혔어요 (the items present) | The company stated the total dividend, the record date and the planned payment date. (the items present) |
| Outlook 1 | 회사는 [연결 기준 ]영업실적 전망을 공시했어요 | The company disclosed its outlook for results[ on a consolidated basis]. |
| Outlook 1, correction | 회사는 [연결 기준 ]영업실적 전망을 고쳐 다시 공시했어요 | The company filed a corrected outlook for results[ on a consolidated basis]. |
| Outlook 2 | 회사는 {매출액, 영업이익, 세전이익, 당기순이익, 판매 목표, 기타 항목} 전망치를 밝혔어요 | The company stated outlook figures for {revenue, operating income, pre-tax income, net income, sales targets, other items}. |
| Outlook 3, correction with figures | 회사는 고치기 전과 고친 후의 전망치를 함께 밝혔어요 | The company stated the outlook figures before and after the correction. |
| Outlook 3, otherwise | 회사는 이 전망이 예측 정보로서 실제 결과와 다를 수 있다고 밝혔어요 | The company said the outlook is projected information and actual results may differ. |

A template is used only when its facts are there: results and change need current and prior
revenue and operating income; units need the total and the cumulative total with their
year-earlier values; a dividend needs its kind, type, the common per-share amount and one
line-three item; an outlook needs one figure, and line three needs either a correction with
figures or the filing's 예측정보 caveat. Otherwise the model writes the summary.

Decided and left open:

- The lexicon blocks the word forecast in English (N3 `forecast*`). The lead decided to keep
  the outlook wording and not loosen N3: the templates and the outlook prompt write outlook,
  and the lexicon is unchanged.
- The new fact keys have no iOS labels yet; the app work is outside this change.

## D79 · Two fiscal years per figure; the prior annual report is the restatement source · 2026-11-19 (`ACCEPTED`)

The roadmap's two-years-per-figure item. The owner delegated the choices (2026-11-19, owner delegated): two fiscal years
per figure for every company, and the previous annual report as the source of the value a
later comparative may restate. A development export had two years for the nine DART
companies and one for the nine SEC companies, and four DART companies had no net income.

- Figures cover two fiscal years per company: the year of its latest annual filing and the
  year before. The newest filing that states a figure is its source. An older annual filing
  is the source only when the latest one does not state that year; values for earlier
  years are not exported (`figures_older_than_two_years` in the build report).
- SEC: a 10-K's prior-year comparative is stored and exported with its own period dates
  and fiscal year. It comes from companyfacts facts whose `accn` is that 10-K, from the
  same tag as the 10-K's own-year fact, with a full-year duration that ends the day before
  the own year starts (`parse_companyfacts_payload(..., with_prior=True)`, which ingest and
  verify both use). D75's mapping is unchanged: `NetIncomeLoss` feeds
  `net_income_attributable`, `ProfitLoss` feeds `net_income` only where reported, and
  there is no fallback between them.
- DART: SK hynix, Samsung SDI, NAVER and Samsung Biologics file one statement of
  comprehensive income (`sj_div` CIS) and no IS rows. The profit-loss dedup kept only IS
  rows, so their `ifrs-full_ProfitLoss` and `ifrs-full_ProfitLossAttributableToOwnersOfParent`
  were dropped. Dedup now keeps the IS row and falls back to the CIS row. Exact account ids
  only; no metric is derived.
- Restatement: `python -m app.ingest --source dart|sec --ticker T --prior` ingests the
  annual report before the latest one (DART: the newest version of the previous
  business year's 사업보고서 and its fnlttSinglAcntAll; SEC: the 10-K filed before the
  latest, skipped with its reason when it does not cover the latest 10-K's fiscal year
  minus one). The latest DART report is the newest version of the latest business year,
  so a late correction of an older year is not the latest. `is_restated` is 1 when the
  latest report's comparative for a year differs from the value that year's own report
  stated under the same regulator tag. The original value is also read from its own pinned
  response, and the build report lists each restated figure with both tags and its
  original (`restated_figures`).
- A different value under a different tag is not a restatement: the build report lists it
  as `tag_changed`, and the figure is exported with `is_restated` 0.
- A prior-year figure whose own year has no annual report stating it is
  `restatement_unchecked` in the build report, and a release build fails on it.
- Decided by the lead under the owner's delegation (2026-11-19): a DART report with no
  diluted EPS row whose basic EPS row is labelled as basic and diluted states its diluted
  EPS by that line, because the filing itself says the value is both. The label must be
  기본및희석주당이익 or 기본및희석주당순이익 exactly once whitespace is removed, optionally
  after the common-share qualifier 보통주 (Samsung SDI's FY2024 report labels the row
  보통주 기본및희석주당이익); a plain 기본주당이익 row does not count. The value is read from
  the pinned response and used only to check the later diluted comparative
  (`combined_eps_checks` in the build report); no diluted figure is exported from it.
- One basis per company and fiscal year: when a year has a restated figure, that year's
  figures that only the earlier report states are `mixed_basis` in the build report and
  are not exported.
- A previous DART report that is not well-formed XML (Kia's corrected 2024 사업보고서,
  rcept 20250313001390) is ingested with `--prior` for its figures only: its prose gives
  no chunks. A parse error on the latest report still fails the ingest.
- The build report names every company and reported metric without both years
  (`figure_gaps`), with the reason `not_stated` (the filings do not state it) or
  `mixed_basis`.
- Pinned responses stay git-ignored (`backend/data/pinned/`); the prior-year files were
  saved there with `--save-pinned`.
- Known limitation: `app.build.verify` re-reads each exported value and tag from its pinned
  response but does not re-check `is_restated`. The bundle does not carry the original
  filing and value, which are only in the build report; carrying them would change the
  bundle schema the app reads.

Development export on 2026-11-19 after the re-ingest: `figures=193`; all eighteen
companies have two fiscal years; `restated_figures` counts four (LG Chem and Samsung
Biologics, revenue and operating income for 2024); `tag_changed` none. `mixed_basis`
leaves out three FY2024 figures stated only by the earlier report: LG Chem diluted EPS,
Samsung Biologics EPS and diluted EPS. `restatement_unchecked` names none: Samsung SDI's
FY2024 diluted EPS is checked against the combined line of its FY2024 report (the same
value, so not restated; `combined_eps_checks` counts one). A release-mode export fails
only on the missing summary approvals. `figure_gaps` names fifteen:

- DART, not stated: diluted EPS for Kia and LG Electronics (both years) and LG Chem (2025);
  EPS and diluted EPS for Samsung Biologics in 2025, which reports only continuing and
  discontinued operations EPS.
- DART, mixed basis: the three FY2024 figures above.
- SEC, not stated: `net_income` (`ProfitLoss`) for Apple, Microsoft, Amazon, NVIDIA, Meta
  and Alphabet (both years) and Costco (the latest year).

## D80 · The Footnote app shell replaces the Filing Digest app · 2026-11-19 (`ACCEPTED`)

Roadmap I3 to I6. One SwiftUI target, "Footnote", builds for iPhone, iPad and native Mac
(iOS 18, macOS 15, Swift 6 strict concurrency) and reads only the bundled
`footnote.sqlite` through FootnoteKit (ADR 0008). The Filing Digest app, its Xcode
project, unit and UI tests and networking are deleted; the repository history keeps them.

- The project is generated by XcodeGen from `ios/project.yml`. The generated
  `ios/Footnote.xcodeproj` is committed, so a clean checkout opens in Xcode without
  XcodeGen, and `scripts/check.sh` regenerates it and fails when it differs.
- Data: a build phase copies `ios/Footnote/Resources/footnote.sqlite` (git-ignored, a
  dev bundle copied by hand) or, when absent, the FootnoteKit test fixture. Release builds
  call `requireRelease()` and show a plain error screen on a development bundle; debug
  builds accept one.
- Pure presentation logic sits in FootnoteKit so `swift test` covers it with no
  simulator: rule-based display titles (`Titles`), the company page (`CompanyPage`: two
  periodic reports at most, ten event filings by month, notices since the oldest listed
  filing, the new-filing rule of the data date and the six days before it) and extra
  date and number formatting.
- English company names come from a short-name table keyed by ticker, because the bundle
  holds registered names in capitals. Moving short names into the bundle is open.
- Fact names come from `contracts/filing-facts.json`, keyed by the fact's origin
  (endpoint plus source field), because one `fact_key` can name a different decision in
  each endpoint.
- Korean wraps only between words: SwiftUI has no keep-all setting, so app text puts a
  word joiner between the characters of each Hangul word.
- The 용어 tab and sidebar row appear only when the bundle has glossary rows (R-24). The
  current dev bundle has none, so the tab is hidden.
- iPhone: tabs 기업 · 소식 (· 용어). iPad and Mac: a three-column split view. A globe
  button switches the whole UI between Korean and English.
- CI's manual `ios` job now tests the Footnote scheme on a simulator and builds it for the
  Mac. `ios/scripts/screenshots.sh` captures the screen set in
  `docs/screenshots/footnote/`.
- Open: a company whose fiscal year ends on a different day each year (Apple's 52 or
  53 weeks) shows revenue without a change, because the calculator refuses periods whose
  ends differ; quarterly reports are not in the bundle; no summary is approved yet, so
  every filing shows the in-review state.

## D81 · Glossary contract and export, wording awaiting approval · 2026-11-19 (`PROPOSED`)

The roadmap's D4 item. The bundle already had a `glossary` table (`term_key`, `lang`,
`term`, `plain`, `formal`) that the exporter left empty. The design wording rule applies:
the plain word first, the formal term beside it. The drafting is the agent's; the owner has
not approved any wording.

- `contracts/glossary.json` holds one entry per `term_key` with a ko and an en
  `{term, plain, formal|null}` and an `approved` flag. Every entry is `approved: false`;
  only the owner sets it. The keys are `metric_<key>` for each reported and derived metric
  in `financial-vocabulary.json`, `category_<key>` for each event, notice and annual
  category in `filing-categories.json`, `refusal_<reason>` for each refusal reason in
  `comparison-cases.json`, and `notices`, `basis_consolidated`, `basis_separate`,
  `restated`, `k_ifrs`, `us_gaap` and `fiscal_year_end`. The annual report entry is
  `category_annual`; the form name "10-K" is left out of its text because the guard bans
  digits.
- Wording is one or two short sentences, plain Korean in 해요체, neutral, no digits. Every
  text passes the same neutrality guard as a summary line (`check_line`, run per sentence;
  N4 attribution does not apply to a definition, and a Korean term may be a Latin
  abbreviation). A test fails when a metric, category or refusal reason has no entry, when
  a category's term differs from the categories contract label, or when an entry lacks a
  language.
- Export: `app.build.glossary` turns the entries into rows. A development build
  (`--allow-unapproved`) writes every entry, as it does for summaries, and marks the file in
  `build_meta.allow_unapproved`. A release build refuses while any entry is unapproved.
  Until the owner approves the wording, no release build can pass.
- `research_and_development` is in `family-glossary.json` only; it is not in the financial
  vocabulary or any figure, so it has no glossary entry.
- Not done: `app.build.verify --release` does not re-check glossary rows in a finished
  file; the release export is the gate.
- Open: the owner reviews the wording (the pull request lists every entry) and approves
  entries by editing the `approved` flags.

## D82 · Consecutive 52/53-week fiscal years compare year over year · 2026-11-19 (`ACCEPTED`)

Decided by the lead under the owner's delegation. Reason: comparing consecutive 52/53-week
fiscal years is how these companies and the SEC present their own year-over-year figures.

Apple, NVIDIA and Costco end their fiscal year on a weekday near a date, so the end moves
by a few days each year. The calculator refused every such pair as `period_end_mismatch`,
and their periodic rows showed revenue with no change (the open item in D80).

- `PRODUCT.md` lists "same company, metric, currency, basis and period end" for a
  comparison. This decision reads "same period end" as the same fiscal-year end: a
  52/53-week year that ends a few days from the prior end's anniversary ends the same
  fiscal year. That reading is listed for the owner's final check.
- Two ends are the same day when their month-days match or both are the last day of
  February. Those pairs keep the earlier rules, and `period_ends_differ` is false.
- Other ends compare when, in this order: both periods run 357 to 371 days, counting both
  end days; the periods do not overlap; the later end is within seven days of an
  anniversary of the earlier end (February 29 read as February 28); that anniversary is
  the first one (otherwise `non_consecutive_years`); the ends are 357 to 371 days apart;
  and the current period starts the day after the prior one ends (a gap is
  `non_consecutive_years`). An anniversary past the year 9999 is not tested, so such a
  pair refuses instead of failing. Anything else refuses as `period_end_mismatch`.
- The drift accepted in practice is up to seven days before the anniversary and up to six
  days after it (five when a February 29 falls in between), because the ends are at most
  371 days apart. Only the prior period can be as short as 357 days, since the current
  period's length equals the step between the ends.
- The pinned SEC company facts fit these ranges without change. Apple, NVIDIA and Costco
  annual revenue periods run 364 or 371 days, with ends 364 or 371 days apart and at most
  six days from the anniversary. Walmart and Microsoft run 365 or 366 days on fixed
  month-days.
- The year-over-year result carries `period_ends_differ` (Swift `periodEndsDiffer`) and
  `period_lengths_differ` (`periodLengthsDiffer`). The second is true when the two
  lengths differ by seven days or more, as a 53-week year against a 52-week year does.
  The app's periodic row shows one note line: "한 해가 다른 해보다 한 주 길어요." / "One
  of the years is a week longer." when the lengths differ, and otherwise "회계연도
  마감일이 며칠 달라요." / "The fiscal years end a few days apart." when the ends differ.
- The rules for currency, basis, metric and unit are unchanged, and so are the
  cross-company rules. Cross-company growth runs each company's year-over-year check, so
  a 52/53-week company now gets a growth rate there too. That result has
  `same_period_end` and the caveat but no per-company flags.
- Rules: `docs/comparison-rules.md`; cases: `contracts/comparison-cases.json`.

## D83 · Filing page and annual page in FootnoteKit models · 2026-11-19 (`PROPOSED`)

Roadmap I7. The filing page (board 12A) and the annual report at a glance (board 4) are
built from two FootnoteKit models, `FilingPage` and `AnnualPage`, so `swift test` covers
what each page shows; the SwiftUI views only lay them out.

- Numbers come from `filing_facts` in their stated unit. `StatedUnit` maps the unit
  column (`백만원`, `억원`, `대`, `shares`, `%`, currency codes) to a scale.
- Lead decision (2026-11-19, PR #33 review, under delegation): on the filing and annual
  pages a money amount shows in the company page's compact form in both languages
  (`333조 6,059억원`, `₩333.61 trillion`; `Formatting.amount`), and each page with amounts
  carries one note: "금액은 줄여서 보여 줘요. 숫자를 누르면 정확한 값을 볼 수 있어요." /
  "Amounts are shortened. Tap a figure to see the exact value." The exact value
  (`Formatting.exactAmount`: Korean in full 조, 억 and 만 groups, English in full grouped
  digits) is on the figure screen, and on a filing page under the row when it is tapped;
  VoiceOver always reads the exact value. Shares, units and dates are never shortened. A
  percentage the filing states shows exactly as stated; a computed rate keeps two places.
- The figure screen compares the year of the report it was opened from with the year
  before (`Route.figure` carries that fiscal year), not the newest year in the bundle.
- Release wiring: `Library.requiresRelease(isDebugBuild:arguments:)` decides whether a
  launch calls `requireRelease`, and is unit tested; only the `#if DEBUG` constant fed
  into it is outside the Debug test build.
- A results, change or unit-sales table becomes a compared block: each figure with the
  base figure the filing itself states beside it (the same period a year earlier, or the
  previous fiscal year). The rate comes from `Calculator.percentage` and shows as sign
  plus word; a base of zero or below shows board 9's line. The filing's previous-quarter
  column is never shown (DESIGN.md: no quarter-on-quarter change).
- An outlook table becomes an outlook block, never compared with anything. A corrected
  outlook item shows the value before the correction, matched from the filing's own
  correction table by label and new value; no gap is computed.
- Other facts are label and value rows. Plain names live in `FactNames` (keyed by
  origin); a number or date with no plain name is still shown, named from
  `contracts/filing-facts.json`. A start and end date pair is one row. Free text is left
  out unless named (the SEC item list). The page shows six numbers at most, across blocks.
- The annual page shows every reported metric for the report's fiscal year and the year
  before on one basis (consolidated when present), with `Calculator.yearOverYear` and
  `Calculator.operatingMargin`; a refusal shows board 10's approved title. Restated
  figures carry the tag and the approved note. Each metric row opens a minimal figure
  screen (`Route.figure`): meaning from the glossary, every year, and the calculation.
  I8 replaces it.
- Clarification status is read from the DART report name (`(미확정)`), because the
  bundle holds no clarification facts.
- Debug builds only: `-FootnoteBundle <path>` opens another bundle (the UI tests open the
  FootnoteKit fixture) and `-FootnoteScroll center|bottom` scrolls a page for the
  screenshot script. The UI tests run in their own iOS-only scheme, `FootnoteUITests`.
- Open, needs data the bundle lacks: the original of a corrected filing (DESIGN.md "Other
  versions"), up to two related filings, a clarification's quoted report, answer, re-filing
  date and earlier answers, an outlook's prior-year target and result, and whether a
  sentence came from a template or the model (the "how written" note is generic until
  then).
- Open, owner review: the drafted copy the pull request lists.

## D84 · Figure, year and company comparison screens · 2026-11-19 (`PROPOSED`)

Roadmap I8 and I9. The figure screen (board 5A), compare with last year (board 6) and its
calculation (6b), the company picker (7A), compare with another company (7) and the
refusal screen (8 to 10) are built on three FootnoteKit models in `FigureCompare.swift`:
`FigurePage`, `YearComparePage` and `CompanyComparePage`. Each holds the figures it shows
and the `Calculator` outcome, so `swift test` reaches every result and refusal; the
SwiftUI views only lay them out.

- The accounting standard comes from the regulator (DART: K-IFRS, SEC: US GAAP). The
  bundle has no `accounting_standard` column; one is added only if a company's standard
  ever differs from its regulator's. The year-end month comes from
  `companies.fiscal_year_end`. The caveat under a cross-company result names both;
  board 7's wording covers two standards and two year-ends, the other three cases are
  drafts.
- Companies compare by growth rate or operating margin only. An amount comparison is
  always refused (`incompatible_currency` when the currencies differ, else the
  calculator's own refusal), and no code path converts a currency: a FootnoteKit test
  greps the app sources, and `scripts/check.sh` runs the same grep.
- A refusal is a `RefusalExplanation`: the calculator's reason and detail, the companies,
  the missing year or the zero-or-below baseline, and "what is possible instead" actions.
  Two overrides make the reason name the real cause: a single company with no inputs is
  `missing_period`/`missing_fact`, and an amount request across currencies is
  `incompatible_currency` even when a figure is missing. Each of the six reasons is
  reached through the screen models in FootnoteKit tests and in the app's copy tests.
- Compare with another company shows each company's rate with a grey bar only when every
  rate is zero or above (a bar for a negative rate would read as a ranking), and the
  difference as the absolute gap in percentage points with the formula
  `|a − b| = d%p`. No "higher", "better" or ordering words; the companies keep the order
  they were chosen in.
- The peer's year is its newest fiscal year, because year-ends differ; each rate row
  names its own fiscal year, year-end month and standard.
- Navigation: screens push through an environment `navigate` action. iPhone pushes onto
  the tab's stack; iPad and Mac push onto a detail-column stack that resets when the
  filing changes. Debug launch routes (`figure`, `picker`, `yearcompare`, `yearcalc`,
  `compare`, `companycalc`) open any of these screens for the UI tests and screenshots.
- Tests edit copies of the fixture: Samsung's figures moved to the separate basis
  (`unsupported_basis`) and Samsung's FY2024 EPS set to a negative value
  (`nonpositive_baseline`). The fixture itself is unchanged.
- Screenshots come from `ios/scripts/screenshots.sh` on the real dev bundle. The
  unsupported-basis shot opens a temporary copy with Samsung's figures on the separate
  basis; the other refusals use real data (LG Chem's negative FY2024 EPS, Costco's single
  year of net income, Samsung and Apple amounts).
- Open, owner review: the drafted copy the pull request lists.

## D85 · Comparison review fixes: amounts, culprits, periods and year-ends · 2026-11-19 (`PROPOSED`)

Follows D84 after the PR #34 review.

- An amount request between two companies that report in the same currency
  (`absolute_amount_across_companies`) has its own title (board 8's "금액은 비교하지
  않아요" / "Amounts are not compared"), body and reason line. It no longer borrows
  `incompatible_comparison`'s period, basis and unit text.
- `RefusalExplanation` carries `culpritID`: the company whose own figures caused the
  refusal. The basis and conditions sentences name it, not the company the screen was
  opened from. For an amount request, which the calculator refuses before any company's
  own check runs, a basis refusal falls back to the company with a figure off a supported
  basis.
- A zero or negative revenue in the operating-margin compare has a margin title, not the
  growth rate's.
- The margin picks the peer's newest year that has both revenue and operating income.
- The caveat leads with a sentence saying the two years are not the same period when
  their fiscal-year labels differ or their period ends are more than thirty-one days
  apart. That is a month, which leaves out 52/53-week drift of a few days.
- `fiscalYearEndMonth` is nil unless `fiscal_year_end` is a valid `MM-DD`. An unknown
  month leaves the year-end part out of the caveat, the rate line and the picker. Bad data
  no longer turns into December.
- The two-year check reads "이어지는 두 해" / "Consecutive years" when the two lengths
  differ. The English rounding line follows board 6b: "rounded to two decimals".
- `scripts/check.sh` and the FootnoteKit test share one no-conversion pattern, which now
  also catches `usd_to_krw`-style names and a bare `fx`. The step fails on a match, on a
  grep error (exit 2) and on a missing source folder.
- Known limit, not changed: the figure screen picks its basis per metric, while the
  company compare picks it across all of a company's figures. The two can differ for a
  company with mixed bases.
- Open, owner review: the new drafted copy the pull request lists.

## D86 · News feed, glossary links and the iPad and Mac glossary columns · 2026-11-19 (`PROPOSED`)

Roadmap I10. Decided by the lead under the owner's delegation; the drafted copy is for the
owner's final check.

- 소식 / News is a FootnoteKit model, `NewsFeed`, built from each company's `CompanyPage`.
  A filing shows in the feed only when its company page lists it (the 12-month window and
  the ten-per-company cap), and 새 공시 uses the same `Freshness` rule: the data date and the
  six days before it (the owner's rule). The feed shows the thirty newest of those filings,
  grouped by the day they were filed, because DESIGN.md asks each screen to show less and
  the full set is about one hundred and eighty rows. A row is the company page's row (tag,
  title, no preview line) with the company's name in place of the date the day heading
  gives. A note under the feed says how many it shows; an empty feed shows board 19's "no
  filings in the last 12 months" line.
- Day grouping uses each filer's own filing date as the regulator records it (KST for DART,
  EDGAR's US Eastern date for SEC), with no time-zone conversion.
- There is no loading state: the app opens its bundled file before the first screen
  (DESIGN.md, board 19). The empty states are the feed above and, for the glossary, the
  existing rule that the tab, the sidebar row and every glossary link are hidden while the
  bundle has no rows in the language (R-24).
- 용어 / Glossary lists the bundle's rows in dictionary order of the term the reader sees
  (Korean or English collation): the plain word, the meaning, then the formal term. DESIGN.md
  calls for neither search nor sections there, so there are none, and so no ⌘F.
- Links: the figure screen's "용어 풀이 더 보기" and a new link at the end of each filing and
  annual page open the glossary scrolled to the matching entry (`metric_<key>`,
  `category_<key>`), with that row in Tint, the selected-row colour. Board 20 lists
  "Glossary for a tagged term" one tap from a filing page; the link sits after the original
  so the approved order (sentences, numbers, original) is unchanged.
- iPad and Mac: the glossary gets the split view's two columns, terms in the content column
  and the chosen term in the detail column. A new sidebar item clears the filing or term
  and anything pushed over it; a new filing or term clears what was pushed over the old one.
- A news or glossary list that opens with a row already chosen (a launch route) scrolls
  that row into view once; later choices are rows the reader can already see, so the list
  does not move.
- Mac keyboard: the company page, news and glossary lists are selection lists, so the arrow
  keys move the selection and the detail column follows; Return or a double click selects
  the focused row. The sidebar was already a selection list. iPhone and iPad rows stay
  buttons.
- `Copy.dot` is now a no-break space, the middle dot, then an ordinary space, so the dot
  stays with the word before it and never starts a line. The only break is after the dot.
  A no-break space on both sides was not chosen: it would join both neighbours into one
  unbreakable run, which at accessibility sizes forces a break inside a word. Display titles
  with a detail (`… 공시 · 2025년 재공시`) use the same separator.
- Not changed: glossary wording (every entry is still `approved: false`) and the release
  gate that refuses a development bundle.
- Open, owner review: the drafted copy the pull request lists, and the thirty-filing size of
  the feed.

## D87 · Accessibility audit in UI tests, its filters, and figures that never break · 2026-11-19 (`PROPOSED`)

Roadmap Q1. Decided by the lead under the owner's delegation.

- `FootnoteUITests` runs Apple's `performAccessibilityAudit()` on twenty-one screens in
  Korean and English, at the default size, at Accessibility XL and in dark mode, at the top
  of each screen and after each swipe. A finding fails the test unless a filter in
  `AccessibilityAuditUITests.falsePositive` names its audit type and the elements it
  applies to, with the reason in a comment. Two filters are broad: Dynamic Type findings on
  every static text and button, and contrast, Dynamic Type and clipping findings that name no
  element. Dynamic Type is therefore checked only by `testTextGrowsAtAccessibilitySizes` (five
  elements, Korean, two screens) and the AX5 screenshots, and text clipping only on the first
  pass of each screen.
- Filters, each checked against screenshots: contrast on text under the translucent
  navigation and tab bars (only real bars count; iOS 27 also reports a toolbar element the
  size of the window), on text laid out below the screen, and on text after a swipe (every
  text colour is a palette token measured at 4.9:1 or more; the first pass of each screen is
  checked as it stands); Dynamic Type on SwiftUI text and buttons (they scale: a separate
  test measures them growing at Accessibility XL) and on the language button (a bar item,
  which shows the large content viewer instead); clipped text on a number that shrinks to
  fit, on the navigation bar's inline title, on the notices sheet's introduction, on the
  comparison's "Compare by" header and its rows on iPad, on the iPad sidebar's
  `News` and `Glossary` labels, and on text after a swipe; contrast on the `원문` header and
  on text in or under the iPad's floating sidebar glass; contrast, Dynamic Type and
  clipped-text findings that
  name no element; and "Potentially inaccessible text" with no element. The log prints each
  filtered finding as `FILTERED|<reason>|`. Element-less findings of other types still
  fail.
- Figures in full digits (the calculation's equation, the year-over-year difference, the
  value in a fact row, a receipt number) wrap only at their spaces. A number wider than the
  whole line shrinks to fit (down to 40%) rather than breaking inside its digits. A word
  without digits keeps its size and wraps as before.
- Section headers use Muted instead of the system header grey, which the audit measured
  just under the contrast threshold.
- The companies list puts the ticker under the name when the name and ticker do not fit
  on one line, so a name never breaks inside a word.
- The compare screen's segmented control uses the extra-large control size, so each
  segment is at least 44 points tall.
- A filing tag keeps its own width unless that is wider than the row; then it wraps inside
  the row. Before, `Management matters` at the accessibility sizes pushed the whole row past
  both edges of its card on the company page and in News.
- The iPad sidebar's selected company row draws its name and ticker in the system's primary
  style, like the labels beside it: light on the Pine fill while the sidebar has focus, dark
  on the grey fill while another column has it. Before, they stayed Ink and Muted on Pine
  and were hard to read. The audit did not report it; the iPad screenshots did.
- Not changed: the release gates and the wording of approved copy. One no-break space now
  joins `보여 줘요` in D83's amounts note; the owner confirms or reverts it.

## D88 · The owner's final check: glossary, drafted copy, D78–D86, and v0.1 scope · 2026-11-19 (`ACCEPTED`)

The owner reviewed the final-check page and returned their picks on 2026-11-19.

- Accepted: D78, D79, D80, D81, D82, D83, D84, D85 and D86, as written. Their status lines
  are not edited; this entry records the acceptance.
- Glossary: the owner approved the wording of all 46 entries in `contracts/glossary.json`,
  which now carry `"approved": true`. `test_glossary_contract.OWNER_APPROVED` lists the keys;
  only the owner adds one.
- Drafted copy: the owner approved the 27 drafted items listed on the page (PRs #33–#35:
  filing page, annual page, figure, compare, refusal, news and glossary wording). Their
  `Draft:` markers in `PageCopy.swift` and `Copy.swift` now read `D88`.
- Still for the owner: the no-break space D87 added inside the approved `보여 줘요` in D83's
  amounts note (wording unchanged).
- Summaries: the owner approved 38 staged sections; approval itself goes through
  `app.build.approve`, run by the owner. Seven sections the guard withheld are not approved
  and get rewritten in a later run.
- Scope: the quarter report screen (board 15) is in v0.1. PRODUCT.md now says so. It needs
  same-quarter-last-year figures for DART (`frmtrm_q_amount`) and quarterly SEC figures.
- Other calls: summaries keep running on the free tier only; the news feed shows thirty
  filings; the walkthrough is recorded on the iPhone mini simulator and hosted as a GitHub
  release asset; the README keeps its one Filing Digest line; the case study stays English
  and quotes no pilot summary; the repository goes public only after the walkthrough is in
  the README, and the owner flips it.

## D89 · Quarter report: quarter figures, the bundle's schema 3, and the screen · 2026-11-19 (`PROPOSED`)

Roadmap I11 (board 15; in v0.1 since D88). Decided by the lead under the owner's delegation.

- Figures: revenue, operating income, and net income attributable to owners, or net income
  when the report states no attributable figure. Each is the quarter's own three months
  next to the same quarter a year earlier; consolidated only; exact decimals end to end.
- DART: `fnlttSinglAcntAll` for the latest 분기·반기보고서. Only income statement rows (IS,
  CIS) are read: `thstrm_amount` is the quarter and `frmtrm_q_amount` the same quarter a year
  earlier. Cash-flow rows are year to date and are never read. The ingest refuses a response
  whose `thstrm_nm` names another quarter, and after the first quarter it leaves out a row
  without `thstrm_add_amount`, since such a row does not show whether its amount is the
  quarter or the year to date. It also leaves out a row whose quarter equals its year to
  date, and does not read a year-earlier quarter equal to that year's year to date
  (`frmtrm_add_amount`): after the first quarter the two match only when one amount was
  filed in both columns. A 반기보고서 gives the second quarter, titled as DART names it
  (`2026년 반기보고서` / `H1 2026 report`). DART states no dates, so
  the export derives them from the title's month (`분기보고서 (2026.09)`: July to September),
  as it does for annual reports.
- A quarter is 12 to 14 weeks long, counting both ends: 84 to 98 days. Calendar quarters
  run 90 to 92 days, 52/53-week filers' quarters 13 or 14 weeks, and Costco's first three
  quarters 12 weeks (84 days). The backend's `sec._QUARTER_DAYS` and FootnoteKit's
  `QuarterComparison.quarterDays` use this one rule.
- SEC: the latest 10-Q's companyfacts three-month entries with that accession number. The
  own quarter must end on the 10-Q's latest date for that tag; otherwise the next tag for
  the metric is tried. The prior quarter is the same tag ending 357 to 371 days earlier.
  Nine-month entries are left out; entries that disagree give no figure.
- `python -m app.ingest --quarter` ingests them, additively. The bundle's schema 3 adds
  `quarterly` filings, which carry no summary, and the `quarter_figures` table. Export and
  `app.build.verify` re-read every quarter figure from the pinned responses with the
  ingest's own selection. A missing metric is listed in the report's `quarter_gaps`.
- Comparison: `QuarterComparison` in FootnoteKit checks company, metric, basis, currency,
  unit, two quarter-long periods and ends a year apart, then takes the rate from
  `Calculator.percentage`. A base of zero or below shows board 9's line and no rate. The
  shared calculator is unchanged: its year-over-year check accepts only full fiscal years
  when the period ends differ, which 13-week quarters do. The change from the quarter before
  is never computed.
- Screen and company page: the company page shows the newest quarterly report above one
  annual report (still two periodic reports at most). The related section shows the newest
  earnings filing made after the quarter ended and on or before the report, and the newest
  investor event notice in the same span. The notice opens on DART or SEC; the bundle holds
  no IR site links, so board 15's "opens the company's IR site" row is drafted as a notice
  row instead. A figure opens the Figure screen, which shows annual years. An earnings
  filing made on the report's own day is described as filed the same day, not before it:
  DART's exchange and FSS receipt numbers are separate sequences, so the order within a day
  is unknown.
- Not built: the year-to-date figures DESIGN.md puts one tap away, and a quarter
  calculation screen. The bundle does not hold year-to-date figures yet.
- The FootnoteKit fixture keeps every row it had and gains only the quarterly filings and
  quarter figures. Regenerating it whole also changes rows from earlier generator changes
  (an Apple prior-year revenue figure, results facts, summaries), which other Swift tests
  rely on; that refresh is separate work.
- For the owner: the drafted wording listed in the I11 pull request, and the glossary entry
  `category_quarterly`, which is `"approved": false` until the owner approves it; a release
  export refuses it until then.

## D90 · Preview bundle for internal TestFlight, and the bundle's schema 4 · 2026-11-20 (`PROPOSED`)

Decided by the lead under the owner's delegation. The owner on 2026-11-20: "add preview bundle".

- A preview is a data bundle the owner can put on TestFlight (internal testing only) before
  every summary is approved. Only owner-approved summaries ever ship, in every mode; the
  exporter still writes no other summary.
- `export --preview` (and `make data-preview`) relaxes two release refusals only: a filing
  without approved summaries and a stale approved row are left out and listed in the report
  (`filings_without_approved_summaries`, `stale_approved_rows_skipped`). The neutrality guard,
  `prompt_version` `none`, `restatement_unchecked` and every figure and fact check stay on.
- Unapproved glossary entries are omitted from a preview, not written, and do not refuse the
  build. A development build still writes them; a release still refuses them.
- Schema 4 adds `build_meta.preview` (0 or 1). A preview records `allow_unapproved = 0` and
  `preview = 1`, a development build 1 and 0, a release 0 and 0. The report's `mode` is
  `development`, `preview` or `release`. `verify --release` refuses `preview = 1`;
  `verify --preview` runs every release check except required-summary coverage and refuses
  `allow_unapproved = 1`. `BundleStore.requireRelease()` is unchanged, so a Release app build
  opens a preview.
- The companies list ends with a quiet line, `자료 기준 <date> · DART·SEC 공시` /
  `Data as of <date> · DART and SEC filings`, and for a preview a second line, `미리보기: 아직
  승인되지 않은 요약은 빠져 있어요.` / `Preview: summaries not yet approved are left out.`
- Glossary links: every place that links to an entry already hides the link when the entry is
  absent (`GlossaryLinkSection`, the figure screen's meaning section), so a preview without
  `category_quarterly` shows no dead link. A FootnoteKit test covers the absent lookup.
- The FootnoteKit fixture is migrated as in D89: its rows are kept and only the schema 4
  column is added (`preview = 0`); regenerating it whole would change rows other Swift tests
  rely on.
- For the owner: the two drafted copy lines above (`Copy.dataFooter`, `Copy.previewNote`).

## D91 · Owner approval of quarterly glossary, screen copy, and amounts-note spacing · 2026-11-21 (`ACCEPTED`)

The owner replied “I approve all” after opening the review snapshot on 2026-11-21.

- The `category_quarterly` glossary wording is approved.
- The eight quarter-report copy items in PR #39 and the two companies-list footer lines from
  D90 are approved as written.
- The owner approved the nonbreaking space in `보여 줘요` in the amounts note (D87).

## D92 · Company discovery and comparison continuity · 2026-11-23

The owner requested quick glossary navigation in both languages, clearer news
rows, consistent original-filing controls, a market selector, and company
sorting by recency, name or market cap.

- The directory shows company names and the New filing tag. The market selector
  applies to all three sorts. Filing recency uses the newest available filing
  or notice for each company. Ties use the localized company name.
- Market cap uses a dated, within-market snapshot as described in ADR 0009.
- The glossary groups English by letter and Korean by initial consonant, with
  Latin-letter sections for Latin headwords. Current iOS uses a native list
  index. Older iOS and macOS use a jump menu.
- The quarter tap opens the same filing's figure and comparison. Its two
  quarter periods and exact amounts are visible, and an explicitly labelled
  link opens the annual figures where available. This supersedes the figure route
  in D89.
- News rows lead with the company. The original-filing link uses the same
  grouped row surface as the other filing sections.

## D93 · Adopt the five design-review proposals · 2026-11-23 (`ACCEPTED`)

The owner marked all five comparisons “Adopt proposal” in the local HTML review
based on the unofficial [Toss Design Skill v2](https://github.com/Ilbie/Toss-Design-Skill/tree/af3d3dd54eab795b300967d98d64a2a94deeec86).

- Companies searches both markets by bilingual name or ticker. Browsing keeps
  its market and shows the selected sort. Clearing the query restores browsing.
- Quarterly figure detail puts the amount and comparison period together.
  Its original report remains directly available. Exact dates, amounts and
  the calculation expand on demand. The calculation uses the existing Decimal
  comparison; a refusal exposes the figures that exist and omits the formula.
- News adds a filing-type filter to the existing event feed. The selected type
  applies before the feed cap. Rows stay newest-first and grouped by filing date.
- The original-filing section places the regulator action beside the filing date.
  Form and receipt number expand in Filing details.
- Glossary search matches both languages and formal terms. The native jump
  index remains. Definitions expand on the phone; larger layouts keep a
  separate detail pane.

## D94 · Filing Digest's server, search and embedding code removed · 2026-11-26

Filing Footnote has no server: the app reads a bundled file (ADR 0006). Nothing in the ingest,
build, export or verify path imported Filing Digest's FastAPI service; an import graph from
`app.ingest` and `app.build` confirmed it before anything was deleted. The finish-line audit of
2026-11-26 asked for the removal.

- Deleted from `backend/app/`: `main.py` (FastAPI), `api/`, `answers/`, `digests/`, `search/`,
  `evidence/`, `embeddings/`, `figures/`, `schemas.py`, `digest_narrative.py`,
  `financials/calculations.py` and `llm/{answer,citation_guard,narrative,deps}.py`, 25 files
  and 2,509 lines. `figures/`, `schemas.py`, `digest_narrative.py`, `financials/calculations.py`
  and `llm/deps.py` were imported only by the other deleted modules.
- Deleted with them: their 14 test files and the smoke seed (3,009 lines), the live eval
  harness `backend/evals/` (it called the HTTP API), `backend/Dockerfile`, `.dockerignore`, and
  the Compose `backend` service with its `hf_cache` volume. So are the FastAPI dependency
  `db.session.get_db_session` and the settings `allowed_hosts`, `embedding_model`,
  `embedding_offline_first` and `embedding_warmup_enabled`.
- Annual ingest no longer embeds chunks. `ingest_filing` persists the snapshot and returns;
  `IngestResult` loses `embeddings_backfilled`. Chunks are still stored, because the summary
  build reads them.
- Kept, although the app does not call it: `compare/calculator.py`, the reference calculator
  that `contracts/comparison-cases.json` holds FootnoteKit's port to. Kept in the schema:
  `filing_chunks.embedding`, its HNSW index and `filings.indexed_at`. New rows leave them
  empty; dropping them needs a migration and is outside this change.
- `llm/number_guard.py` scans plain strings instead of `/answer` objects; the neutrality guard
  still imports its spelled-number patterns. `_ANY_DIGIT_RE` moved from `digest_narrative.py`
  into `neutrality_guard.py`, and rule N1's `sources` in the lexicon name its new place. The
  lexicon version is unchanged, so no summary cache key or approval changes.
- Removed from `requirements.txt`: fastapi, uvicorn[standard], httpx2, sentence-transformers,
  and PyYAML (used only by the eval harness). The lock, regenerated with
  `uv pip compile --universal --no-header --no-annotate` constrained to the previous pins,
  drops 41 packages, among them torch, transformers, scikit-learn and scipy. No remaining pin
  changed. CI no longer installs CPU torch.
- The local database defaults D77 kept are renamed from `filing_digest` to `filing_footnote`
  (user, password `filing_footnote_dev`, database) in `docker-compose.yml`, CI and `config.py`.
  PostgreSQL reads them only when a volume is first created, so an existing volume keeps its
  `filing_digest` role and data. On such a volume, a command that relies on the default URL
  needs `DATABASE_URL` in `backend/.env` or a `filing_footnote` role.
- `contracts/family-glossary.json` no longer asks to be kept identical with the partner
  repositories.
- Not changed: `backend/.env.example` still names the old database URL and the `EMBEDDING_*`
  variables (settings ignore unknown variables). ADR 0006 mentions a small read-only API that
  serves the bundle; none exists, and this entry neither builds nor drops it.

## D97 · Every summary line is checked against its source text before release · 2026-11-26

The guard (ADR 0005) checks how a line is written, not whether the filing says it. A pilot
line swapped the filing's region for another place, and neither the guard nor the model
reviewer flagged it. `app.build.faithfulness` finds the source sentences behind
each Korean and English line and gives one verdict per line: `supported`, `partly` or
`unsupported`. It is deterministic and local: no model call and no Groq tokens, and the same
rows and source text give the same report.

- **Method.** The source text (the same text the summary step sent to the model) is cut into
  sentences with their offsets: at line breaks, sentence ends and DART list markers. Korean
  words match by stem after particles and endings are stripped (이천시에 → 이천시). English
  words match on a six-letter prefix. Places, products, currencies, numbers and acronyms are
  strict entities. Places, products and currencies come from
  `contracts/faithfulness-lexicon.json`, one id per entry with its Korean and English forms
  (파운드리 and Foundry are the same id). A line's support is the best span of up to two
  sentences, scored by weighted overlap (entities count twice). From 0.7 the line is
  supported, from 0.4 partly, below that unsupported. A strict entity the source never names
  makes a line unsupported, and so does a rival action (acquire, dispose or cancel; appoint
  or resign; quarterly or special). A flipped negation or direction caps the line at partly.
  An English line over a Korean source, or a Korean line over an English one, takes the
  verdict and span of its other-language twin, and its own strict entities are still checked
  against the source.
- **Report.** `make faithfulness AS_OF=<the summary run's --as-of>` checks `approved.jsonl`
  and `staged.jsonl`. It writes `backend/data/summaries/faithfulness.jsonl` (git-ignored,
  regenerable), one record per line. Each record holds the verdict, the overlap, the reasons,
  the span offsets and text, the line and approval hashes, and the aligner and lexicon
  versions.
- **Gate.** `verify --release` reads the report. Every summary line in the bundle needs a
  record from the current aligner version for its exact text and approval hash. An edited
  line, a new approval or a new aligner version therefore needs a fresh check.
  `--faithfulness-policy` is `off`, `warn`, `unsupported` or `partly`. **The default is
  `unsupported`:** unsupported lines and lines without source text block; partly lines are
  shown on the review page but do not block. In the eval, unsupported had no false flags,
  while partly flagged 6 of 45 faithful lines. Blocking partly would also hold back 62 lines
  the owner has already approved.
- **Owner override.** `python -m app.build.faithfulness accept --filing … --section … --lang …
  --line … --note …` records that the owner read a flagged line and keeps it. It writes
  `backend/data/summaries/faithfulness_accepted.jsonl`, which is tracked. Each entry is bound
  to the line and approval hashes, so an edit voids it. Agents never run it.
- **Review page.** `app.build.review --database-url` shows each line's verdict, overlap and
  support sentence, and puts flagged summaries first.
- **Eval.** `make faithfulness-eval` scores 73 hand-labelled lines (22 cases, both
  languages) in `backend/tests/fixtures/faithfulness/`. The cases are real approved lines and
  synthetic edits of them (a swapped region, product, action, number or negation). Claude
  labelled them; the owner has not reviewed the labels. All 73: unsupported precision 14/14,
  recall 14/24. Flagged (partly or unsupported): precision 20/26, recall 20/28. The held-out
  test split: unsupported precision 4/4, recall 4/9. The test split's real lines come from
  the approved rows the lexicon was tuned on, so only its synthetic edits are unseen. A test
  pins these numbers.
- **What it misses.** A changed word that appears elsewhere in the same source (system
  semiconductors in an SK hynix line whose filing names both), a media name the lexicon does
  not hold, a Korean-only edit whose English twin is faithful, and a flipped negation that
  lands on partly instead of unsupported. It flags faithful lines that paraphrase a list
  ("multiple tranches with varying maturities").
- **Tried and dropped.** A rule that marked a line partly when it held content words found
  nowhere in the source added no catches on the dev split. It cost two false flags there and
  would have moved about 150 approved lines to partly.
- **Results on 2026-11-26** (as-of 2026-11-19, aligner `f1-2026-11-26`). Tracked
  `approved.jsonl`: 376 rows, 1,068 lines: supported 792, partly 62, unsupported 4, template
  180, no source 30. The 4 unsupported lines are line 3 of `sec:0001193125-26-216986` and
  `sec:0001193125-26-234488` in both languages, the tranche paraphrase above; they read
  as faithful and need the owner's `accept`. The 30 no-source lines are 5 approved filings
  for which the build selects no summary target at that date. Staged (all withheld): 90 rows,
  252 lines: one unsupported, an English line that names Gyeongnam where the filing and the
  Korean line say 영남권. No approval was changed.
- **Not changed.** The bundle schema and the app. Showing the support sentence in the app
  needs a bundle table; the proposal is in the pull request, not built.

## D99 · Ask about this company: fixed questions answered from the bundle · 2026-11-26 (`ACCEPTED`)

Requested by the owner through the Orca coordinator, which had full UI control and
reviewed the screenshots. PRODUCT.md's "the app does not chat" still holds: nothing is
generated on the device.

- The company page gets six fixed questions below the quarterly results, in this order:
  Should I buy this? What are the fundamentals? What's the recent trend? Does it make or
  lose money? How is revenue doing? What's next quarter's revenue? The bundle can answer
  all six for every company, so none was cut.
- The flow is question → `QuestionIntent` → `CompanyAnswerer` (FootnoteKit) → `Answer`.
  A button maps straight to an intent. A later typed-question router may only choose an
  intent; it never writes an answer or a figure.
- Answers use only the bundle: the newest annual report's approved business lines, and
  exact `Decimal` figures from the newest quarterly report and annual report, each
  against the same period a year earlier through the existing comparisons. Each block
  cites its filing.
- Sentences are fixed text with no digits (`contracts/company-questions.json`). Code picks
  them from the figures: revenue up, down or about the same (the change rounds to
  0.00%), not compared, or not stated; a net profit, a net loss, neither, or not stated.
  The backend's neutrality guard checks every sentence for digits, judgement words,
  predictions, advice and language. Attribution (N4) and summary shape (N6) are not
  applied, because the sentences describe the app in its own voice.
- "Should I buy this?" says the app does not tell anyone to buy or sell, then offers the
  fundamentals, profit and trend questions. "What's next quarter's revenue?" says the
  app shows ended periods only and does not estimate. It points to the company's newest
  outlook filing when there is one, and never shows a figure for a future period.
- A missing summary, report or figure is said to be missing, never shown as zero.
- iPhone pushes the answer. iPad and Mac show it in the detail column and keep the
  question filled. Amounts use the app's formatter, so Korean USD reads `1,094억 달러`.
