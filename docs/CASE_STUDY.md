# Case study: Filing Footnote

Status on 2026-11-20: v0.1 in development. The pipeline, the app, the quarter report and the
release gates are built. The owner has approved the glossary, the screen copy and 38 summary
sections. The release bundle is not built, because 171 exported filings still lack an
approved summary. The [walkthrough video](https://github.com/mhju0/filing-footnote/releases/tag/walkthrough-2026-11-20) was recorded on 2026-11-20 from a
development bundle.

## The problem

Listed companies publish what matters to shareholders as official filings: annual reports,
preliminary results, dividends, buybacks, outlooks, management changes. The filings are
public on DART in Korea and EDGAR in the US, but they are long, formal and in one language,
and the numbers sit in tables and XBRL feeds that a casual reader never opens.

Footnote picks 18 well-known companies (nine on DART, nine on SEC) and shows, for each one,
the latest annual report, the latest quarter against the same quarter a year earlier, and up
to ten recent filings in plain Korean and English. The
target is a first-time viewer who can say within seconds how a company did last year and
why they can trust the number ([PRODUCT.md](../PRODUCT.md)). That puts the hard part in
trust: a summary written by a language model must not change a number, invent a judgement or
read as advice.

## Constraints

- Summaries run on Groq's free tier (D68), and the macOS CI job runs only on manual
  dispatch (`.github/workflows/ci.yml`).
- Offline app. The app reads a bundled, read-only SQLite file. There is no server, no
  account and no text generation on the device; only "open the original" needs a network.
- The owner approves every summary. Nothing the model or a template writes ships until
  the owner has approved it, filing by filing, in both languages.
- No digits in generated prose. Figures come from structured regulator data and are
  rendered by the app, so no figure on screen passes through a model.
- No currency conversion. Korean and US companies are compared by growth rates and
  margins only. An exchange rate would decide the result, so the app refuses to compare
  amounts across currencies.

## Key decisions and their trade-offs

### One bundled SQLite file with exact decimals

Recorded in [ADR 0006](adr/0006-bundled-sqlite-with-exact-decimals.md), D61, D66.

No bundle column and no FootnoteKit source file uses binary floating point; amounts are
stored as canonical decimal strings, and shortened amounts show the exact value one tap
away. In return the
data is only as new as the last build, and every new filing means a rebuild and a new app
build.

### Categories by rule, not by model

Recorded in [ADR 0004](adr/0004-event-filings-in-scope.md),
[ADR 0007](adr/0007-notices-and-wider-event-scope.md), D62, D76.

Categories come from rules that can be read and tested; a filing no rule knows is excluded
as `no_rule`.

### Guards on every generated line

Recorded in [ADR 0005](adr/0005-neutrality-guards.md), D60, D63,
D74.

Rules N1 to N8 reject digits and spelled numbers, judgement words, predictions,
unattributed statements, bad links, the wrong shape, advice and the wrong language; N9
only warns. The word lists live in `contracts/neutrality-lexicon.json` so the owner can
read them. A line that still fails after one retry is withheld and the page shows the
figures alone. The guard cannot prove a sentence is supported by the filing or that a
neutral sentence is not misleading, which is why approval stays with a person.

### Owner approval, with the model reviewer advisory only

Recorded in ADR 0005, D60.

A second model
call flags problems but never approves or blocks, because it shares the writer's blind
spots. Approved rows carry a hash of their source text, prompt, model and lexicon, and a
release refuses an approval whose hash no longer matches. No release bundle exists until the
owner approves the summaries.

### Groq's free tier for summaries

Recorded in D68, D69, D71.

The first choice, a Gemini model,
returned errors for a new account, and Groq's `qwen/qwen3.8-27b` passed a pilot. The free
tier shaped the build: an input limit per minute forced a cap on DART source text (seven
thousand characters, since Korean costs more tokens per character), output that never
becomes valid JSON skips the section instead of stopping the run, and the free tier's
output-token limit per minute sets the wait between calls. During the 2026-11-19 run Groq
also returned HTTP 429 errors for tokens per day. Groq's data-use terms were not checked; the filings
are public.

### Templates for filings that are tables

Recorded in D78.

DART preliminary results, unit sales,
dividends and outlooks are regular tables. Their figures are read from the table by header
text, and their summary lines come from fixed Korean and English templates with no model
call. Direction words compare the table's own current and prior values as `Decimal`. The
wording is plainer and repetitive, but these filings never pass through a model, and
template lines still go through the guard and the owner.

### Cross-company comparisons by rate only

Recorded in D84, D85.

Comparing Samsung with Apple shows
each company's growth rate or operating margin, with a caveat naming the two accounting
standards and year-ends; an amount comparison is always refused with a reason and the
comparisons that are possible instead. `scripts/check.sh` and a FootnoteKit test grep the
app sources for conversion code. A reader cannot compare company sizes, which is the
intended limit.

### One native SwiftUI app with a tested core

Recorded in [ADR 0008](adr/0008-native-multiplatform-app.md), D80.

One target builds for iPhone,
iPad and native Mac. Data access, the calculator and the screen models live in the
FootnoteKit package, so `swift test` covers what each screen shows without a simulator.
The project file is generated by XcodeGen and committed; the gate pins XcodeGen 2.47.0
because another version writes a different file.

## Failures caught along the way

### The guard caught model output, and the pilots showed where it was too narrow

In the
second pilot the model named the quarter a result belonged to, spelled out as a word rather
than a digit. N1 caught digits and spelled amounts but not ordinals, so it passed. The prompt
now tells the model not to name the period, and the lexicon blocks named quarters and halves
in both languages (D70, D74). Other pilot lines used a Korean future ending the prediction
rule rejects, and a one-line summary ran past the length limit; both led to prompt changes.
One pilot line replaced a region name from the filing with a different place, and neither
the guard nor the reviewer flagged it. That case is the clearest argument for owner review.
[Summary quality](#summary-quality) counts what the guard withheld in the current run, and
why.

### The 52/53-week rule

Apple, NVIDIA and Costco end their fiscal year on a weekday near a
date, so the end moves by a few days each year. The calculator required the same period end
and refused every one of their year-over-year pairs, and their pages showed revenue with no
change. The fix accepts consecutive full years whose ends sit within a week of the prior
end's anniversary, and labels the result when the ends or the lengths differ (D82). Review
then found three gaps: a February 28 and February 29 end pair, a gap between the two
periods, and a date past the year 9999 that crashed instead of refusing. All three became
contract cases.

### Unit boundaries

English amounts choose a unit from the value, and a value just under a
trillion rounded up to "1.00 trillion" in an early version; the unit is now chosen from the
unrounded value. DART outlook tables mix units per row, so an outlook item is stored only
when its unit is one the parser knows, and a ratio row with no unit is dropped (D78). On the
filing pages a shortened amount always has its exact value one tap away and in VoiceOver
(D83). A related semantic gap: SEC's `NetIncomeLoss` is the parent's share of net income,
while DART's net income is the consolidated total, so the same key meant two things until
the mapping was split (D75).

### False refusal reasons found in review

The refusal screen must say why a comparison is
refused, and review found several cases where it gave the wrong reason (D84, D85). An amount
request between two companies that both report in won borrowed the text for mismatched
periods and bases. Refusal sentences named the company the screen was opened from instead of
the company whose figures failed. A zero revenue in the margin comparison showed the growth
rate's title. An amount request across currencies with a missing figure reported the missing
figure rather than the currency. Each now has its own reason or a named culprit, and each of
the six refusal reasons is reached in the FootnoteKit and app tests.

### Approvals that went stale

The owner approved 38 sections on the review page. The first development export after that
shipped 24 of them and left out 5 whose filings are no longer among their company's ten
newest. It skipped the other 9: they had been written under the first version of the word
lists (three also under an earlier prompt), so their stored hash no longer matched the
current source text, prompt, model and word lists. A release export refuses them. The
export does not trust an approval made for a different input; the summary run writes those
sections again and they go back to the owner.

### Data that silently went missing

Ingest looked for titles starting with the annual report
name, so a corrected report never matched and two companies failed the build (D73). Four DART
companies file a single statement of comprehensive income, and the deduplication kept only
income-statement rows, which dropped their net income (D79). Both were found because the
export re-reads every figure from the pinned regulator files and reports every company and
metric without two years.

## Summary quality

Counted on 2026-11-20 with `python -m app.build.quality`, from `staged.jsonl`,
`approved.jsonl` and `calls.jsonl`. The call log runs from 2026-11-17 to 2026-11-19 and
includes the first Gemini attempts and calls made under earlier prompt versions. The summary
run is still going, so these counts grow.

| Filing sections | Count |
|---|---|
| In the summary files | 86 |
| Written by the model | 62 |
| Written by a template (no model call) | 24 |
| Approved by the owner | 38 |
| Approved, with a newer version staged or withheld | 0 |
| Approved with an owner edit | 0 |
| Passed the guard, awaiting the owner | 34 |
| Withheld by the guard | 14 |
| Withheld, by rule (a section can fail more than one) | N1 3, N3 1, N4 8, N6 3, json 1 |
| With a soft-intensity warning (N9, never blocks) | 3 |

| Model reviewer (advisory; model-written sections that passed the guard) | Count |
|---|---|
| No flags | 48 |
| Flagged something | 0 |
| Did not run | 0 |

| Calls | Count |
|---|---|
| First calls | 85 |
| Retries (first answer failed the guard) | 39 |
| Retries that ended in an API error | 8 |
| Sections the retry fixed (last writing call, now passing) | 18 |
| Sections whose last writing call was a failed retry (withheld) | 14 |
| Reviewer calls | 63 |
| Cache hits (no call made) | 217 |
| Template runs (no call made) | 24 |
| API errors | LLMApiError 400 ×1, LLMApiError 404 ×1, LLMApiError 413 ×1, LLMApiError 429 ×19, LLMApiError 503 ×1 |
| Median tokens in / out per writing call | 2311 / 154 |
| Total tokens in / out | 315745 / 18942 |

What the counts say:

- The guard rejected the model's first answer on at least 39 of 85 first calls; eight more
  retries ended in an API error before an answer came back. A retry with the guard's findings
  produced the final text of 18 sections. Fourteen sections stayed withheld, and their pages
  show the figures alone.
- The most common reason a section stayed withheld was attribution (N4, 8 sections): a line
  that states something without saying it is the company's statement. No template section was
  withheld.
- The model reviewer flagged nothing on the 48 sections that passed the guard. The owner
  then read and approved 38 sections without editing a line. The reviewer added no signal in
  this run, so the owner's read remains the check that matters.
- A writing call takes a median of about 2,300 tokens in and 150 out. Groq's HTTP 429
  responses during the run named a daily limit of 200,000 tokens. At the pace the run logged
  on 2026-11-19, about 45 sections a day, the remaining sections take several days, and then
  the owner's review.

## Faithfulness check

The guard reads how a line is written; it cannot tell whether the filing says it. A pilot line
that swapped the filing's region passed both the guard and the model reviewer. Since D97 a
deterministic aligner looks for the source sentences behind every line, and a release blocks
a line the source does not support unless the owner accepts it. It makes no model call.

Measured on 2026-11-26 on 73 lines labelled by the agent (22 cases, both languages, real
lines and synthetic edits of them), with `make faithfulness-eval`:

| Measure | Result |
|---|---|
| Unsupported: precision | 14 of 14 |
| Unsupported: recall | 14 of 24 |
| Unsupported, held-out test split: precision, recall | 4 of 4, 4 of 9 |
| Flagged as partly or unsupported: precision, recall | 20 of 26, 20 of 28 |
| Faithful lines marked partly | 6 of 45 |

The recall is the weak part. The check catches a place, product, number or action the filing
never names. It misses a changed word that the same filing uses elsewhere, a media name the
lexicon does not hold, and a Korean-only edit whose English twin is faithful. A flipped
negation lands on partly, so it shows on the review page but does not block. The test split's
real lines came from the approved rows the lexicon was tuned on, so only its synthetic edits
are unseen. A rule that marked unfamiliar content words as partly found nothing new on the dev
split and would have moved about 150 approved lines to partly. It was dropped.

Over the 1,068 approved lines it found 4 unsupported, all faithful paraphrases of a list of
note tranches, which the owner can accept. It also found 62 partly lines and 30 lines from 5
filings that no longer have a summary target. In the staged rows it found one real error: an
English line that named Gyeongnam where the filing says 영남권.

## How it was built

Footnote merges two earlier projects of the same owner, Filing Digest and Filing Agent
(D59), and started from Filing Digest's backend. The Footnote work in this repository ran from
2026-11-17 to 2026-11-19:

| Measure | Count | Source |
|---|---|---|
| Pull requests merged | 40 | `gh pr list --state merged` |
| Commits, not counting merges, by 2026-11-20 | about 80 | `git log --since=2026-11-17 --no-merges` |
| Decision entries | D59 to D89 | [DECISIONS.md](DECISIONS.md) |

The code was written by an AI coding agent (Claude Code; each commit carries an `Agent:`
trailer) working to the owner's product decisions, design picks and approvals. A pull
request merged only after its checks passed; 38 of the 40 pull request bodies include a
`scripts/check.sh` run ending `GATE: PASS`. Larger pull requests also had a separate review
pass, and its fixes are recorded (for example D85 for the comparison screens, and commit
`90146f2` for the quarter report). The owner kept three things: product scope, visual picks, and approval of every
summary, glossary entry and piece of screen copy.

## What Footnote dropped from the earlier projects

Filing Digest answered questions with retrieval and a generated narrative. Filing Agent used
a local model inside a LangGraph workflow. Footnote keeps neither. Each removal rests on a
recorded result or decision.

**Retrieval and embeddings.** Digest embedded filing chunks with KURE-v1 and searched them
with pgvector (D3), and Gemini wrote the answer. Its last live evaluation, on 2026-10-03,
passed 24 of 24 cases about three companies. Its hit and rank measures covered retrieval,
not general financial accuracy ([MAINTENANCE.md](MAINTENANCE.md)). Footnote has no server:
the app reads one bundled file ([ADR 0006](adr/0006-bundled-sqlite-with-exact-decimals.md)).
Nothing in the ingest, build, export or verify path imported Digest's FastAPI service, so
[D94](DECISIONS.md) deleted the service, search, embeddings and the eval harness that called its API. The
lock lost 41 packages, among them torch and transformers.

**The local model.** Filing Agent's 2026-09-07 benchmark ran qwen3:8b and gemma4:e4b through
Ollama on the owner's Mac, three trials per case
([bench/results.md](https://github.com/mhju0/filing-agent/blob/a2b01cdc7e42ba019d9b6e4c1727cc13091d2fe7/bench/results.md)).
Samsung Electronics' FY2023 revenue changed by −14.33%. qwen3:8b consistently returned
−14.38% and gemma4:e4b −14.45%. In a later run both models picked the right evidence and
still wrote that revenue had increased, and qwen3:8b reported an absent R&D expense as zero
([run notes](https://github.com/mhju0/filing-agent/blob/a2b01cdc7e42ba019d9b6e4c1727cc13091d2fe7/bench/runs/2026-09-07/README.md)).
Agent's [ADR 0005](https://github.com/mhju0/filing-agent/blob/a2b01cdc7e42ba019d9b6e4c1727cc13091d2fe7/docs/adr/0005-local-intent-and-deterministic-financial-answers.md)
then let the model read only the question's intent; code picks the evidence, calculates with
Decimal and writes the answer. Under that split, Agent's release evaluation passed 120 of 120
scenario runs over 138 local turns with no source or value mismatch, on paraphrases an agent
wrote, not independent review
([evals/RESULTS.md](https://github.com/mhju0/filing-agent/blob/a2b01cdc7e42ba019d9b6e4c1727cc13091d2fe7/evals/RESULTS.md)).
Footnote keeps the split without Ollama. Groq writes summaries at build time, and each
passes the guards and the owner's approval before it ships (D68). On iPad and Mac, Apple's on-device model only maps a
typed question to one of six fixed questions or to none; it never writes an answer or a
figure (D108).

**The LangGraph agent.** Agent ran each investigation through three LangGraph stages
(interpretation, evidence and arithmetic, answer persistence) with FastAPI and PostgreSQL, so
an interrupted stage could be retried
([ADR 0006](https://github.com/mhju0/filing-agent/blob/a2b01cdc7e42ba019d9b6e4c1727cc13091d2fe7/docs/adr/0006-persisted-local-workflows-and-release-scope.md)).
Footnote has no accounts or servers, and the app does not chat ([PRODUCT.md](../PRODUCT.md)).
Each fixed question maps straight to an intent, and code answers it from the bundle with
fixed sentences that contain no digits (D99). A typed question gets a fresh model session
each time (D108).

## Measured results

Counted on 2026-11-20 on branch `docs/portfolio-values`. The bundle counts are from the local
development bundle, exported from commit `44b787f` (its `build_meta.source_revision`).

| Measure | Result | How it was counted |
|---|---|---|
| Backend offline tests | 1714 passed, 57 skipped (a checkout without the local pinned files skips more) | `scripts/check.sh` (the `make test` step) |
| FootnoteKit tests | 140 tests in 22 suites, all passed | `scripts/check.sh` (`swift test`) |
| App unit tests | 38 `@Test` functions | Counted in `ios/FootnoteTests/`; not run for this count |
| UI tests | 26 test methods | Counted in `ios/FootnoteUITests/`; not run for this count |
| Comparison contract cases | 112 | `contracts/comparison-cases.json`, passed by both calculators |
| Gate | `GATE: PASS` | `scripts/check.sh` |

The app and UI tests were last run in pull request #39 on an iPhone 13 mini simulator, where
every non-audit UI test and the audits it touched passed.

Development bundle (data date 2026-11-19, `allow_unapproved = 1`, counted with `sqlite3`):

| Table | Rows |
|---|---|
| Companies | 18 (9 DART, 9 SEC) |
| Filings | 214 (19 annual reports, 18 quarterly reports, 177 event filings) |
| Notices | 177 |
| Figures | 193, of which 4 are marked restated |
| Quarter figures | 130 |
| Filing facts | 878 |
| Summaries | 48 (24 filings, Korean and English; only approved summaries are written) |
| Glossary rows | 94 (47 entries in two languages; 46 approved, `category_quarterly` waits for the owner) |

Release readiness: the export lists 195 filings that need summaries, and 24 have approved
ones. Of the rest, some are written and wait for the owner (34 sections on 2026-11-20), and
the summary run is still writing the others. A release export refuses until all of them do. Pilot summary text is not quoted here.
