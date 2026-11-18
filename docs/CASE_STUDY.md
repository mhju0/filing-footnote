# Case study: Filing Footnote

Status on 2026-11-19: v0.1 in development. The pipeline, the app and the release gates are
built; no summary is approved yet, the release bundle is not built, and the walkthrough is
not recorded.

Walkthrough: **[placeholder: walkthrough link, added once it is recorded]**

## The problem

Listed companies publish what matters to shareholders as official filings: annual reports,
preliminary results, dividends, buybacks, outlooks, management changes. The filings are
public on DART in Korea and EDGAR in the US, but they are long, formal and in one language,
and the numbers sit in tables and XBRL feeds that a casual reader never opens.

Footnote picks 18 well-known companies (nine on DART, nine on SEC) and shows, for each one,
the latest annual report and up to ten recent filings in plain Korean and English. The
target is a first-time viewer who can say within seconds how a company did last year and
why they can trust the number ([PRODUCT.md](../PRODUCT.md)). That puts the hard part in
trust: a summary written by a language model must not change a number, invent a judgement or
read as advice.

## Constraints

- **Free tools only.** Summaries run on Groq's free tier, the app uses the system SQLite and
  no third-party Swift packages, and the macOS CI job runs only on manual dispatch so the
  repository spends no paid runner minutes.
- **Offline app.** The app reads a bundled, read-only SQLite file. There is no server, no
  account and no text generation on the device; only "open the original" needs a network.
- **The owner approves every summary.** Nothing the model or a template writes ships until
  the owner has approved it, filing by filing, in both languages.
- **No digits in generated prose.** Figures come from structured regulator data and are
  rendered by the app, so a model can never misquote one.
- **No currency conversion.** Korean and US companies are compared by growth rates and
  margins only. An exchange rate would decide the result, so the app refuses to compare
  amounts across currencies.

## Key decisions and their trade-offs

1. **One bundled SQLite file with exact decimals**
   ([ADR 0006](adr/0006-bundled-sqlite-with-exact-decimals.md), D61, D66). Every amount is a
   canonical decimal string, read into `Decimal` in Python and Swift; no column or code path
   uses binary floating point, and a FootnoteKit test fails if a source file names `Double`.
   The app costs nothing to run and a figure on screen equals the filed figure. In return the
   data is only as new as the last build, and every new filing means a rebuild and a new app
   build.

2. **Categories by rule, not by model** ([ADR 0004](adr/0004-event-filings-in-scope.md),
   [ADR 0007](adr/0007-notices-and-wider-event-scope.md), D62, D76). Each filing gets one
   category from a fixed list using the regulator's own form type and report name, or a named
   exclusion. A wrong category cannot appear silently and the rules can be tested. The cost is
   upkeep: a report name no rule knows is excluded as `no_rule` until someone adds a rule, and
   a few generic DART names needed the owner's call on where they belong.

3. **Guards on every generated line** ([ADR 0005](adr/0005-neutrality-guards.md), D60, D63,
   D74). Rules N1 to N8 reject digits and spelled numbers, judgement words, predictions,
   unattributed statements, bad links, the wrong shape, advice and the wrong language; N9
   only warns. The word lists live in `contracts/neutrality-lexicon.json` so the owner can
   read them. A line that still fails after one retry is withheld and the page shows the
   figures alone. The guard cannot prove a sentence is supported by the filing or that a
   neutral sentence is not misleading, which is why approval stays with a person.

4. **Owner approval, with the model reviewer advisory only** (ADR 0005, D60). A second model
   call flags problems but never approves or blocks, because it shares the writer's blind
   spots. Approved rows carry a hash of their source text, prompt, model and lexicon, and a
   release refuses an approval whose hash no longer matches. This makes the owner's time the
   release bottleneck: on 2026-11-19 zero summaries are approved, so no release bundle exists.

5. **Groq's free tier for summaries** (D68, D69, D71). The first choice, a Gemini model,
   returned errors for a new account, and Groq's `qwen/qwen3.8-27b` passed a pilot. The free
   tier shaped the build: an input limit per minute forced a cap on DART source text (seven
   thousand characters, since Korean costs more tokens per character), output that never
   becomes valid JSON skips the section instead of stopping the run, and a daily token limit
   spreads a full run over several days. Groq's data-use terms were not checked; the filings
   are public.

6. **Templates for filings that are tables** (D78). DART preliminary results, unit sales,
   dividends and outlooks are regular tables. Their figures are read from the table by header
   text, and their summary lines come from fixed Korean and English templates with no model
   call. Direction words compare the table's own current and prior values as `Decimal`. The
   wording is plainer and repetitive, but these filings never pass through a model, and
   template lines still go through the guard and the owner.

7. **Cross-company comparisons by rate only** (D84, D85). Comparing Samsung with Apple shows
   each company's growth rate or operating margin, with a caveat naming the two accounting
   standards and year-ends; an amount comparison is always refused with a reason and the
   comparisons that are possible instead. `scripts/check.sh` and a FootnoteKit test grep the
   app sources for conversion code. A reader cannot compare company sizes, which is the
   intended limit.

8. **One native SwiftUI app with a tested core**
   ([ADR 0008](adr/0008-native-multiplatform-app.md), D80). One target builds for iPhone,
   iPad and native Mac. Data access, the calculator and the screen models live in the
   FootnoteKit package, so `swift test` covers what each screen shows without a simulator.
   The project file is generated by XcodeGen and committed; the gate pins XcodeGen 2.46.0
   because another version writes a different file.

## Failures caught along the way

**The guard caught model output, and the pilots showed where it was too narrow.** In the
second pilot the model named the quarter a result belonged to, spelled out as a word rather
than a digit. N1 caught digits and spelled amounts but not ordinals, so it passed. The prompt
now tells the model not to name the period, and the lexicon blocks named quarters and halves
in both languages (D70, D74). Other pilot lines used a Korean future ending the prediction
rule rejects, and a one-line summary ran past the length limit; both led to prompt changes.
One pilot line replaced a region name from the filing with a different place, and neither
the guard nor the reviewer flagged it. That case is the clearest argument for owner review.
In the current staged set the guard withheld two filing sections, one for digits (N1) and one
for shape (N6).

**The 52/53-week rule.** Apple, NVIDIA and Costco end their fiscal year on a weekday near a
date, so the end moves by a few days each year. The calculator required the same period end
and refused every one of their year-over-year pairs, and their pages showed revenue with no
change. The fix accepts consecutive full years whose ends sit within a week of the prior
end's anniversary, and labels the result when the ends or the lengths differ (D82). Review
then found three gaps: a February 28 and February 29 end pair, a gap between the two
periods, and a date past the year 9999 that crashed instead of refusing. All three became
contract cases.

**Unit boundaries.** English amounts choose a unit from the value, and a value just under a
trillion rounded up to "1.00 trillion" in an early version; the unit is now chosen from the
unrounded value. DART outlook tables mix units per row, so an outlook item is stored only
when its unit is one the parser knows, and a ratio row with no unit is dropped (D78). On the
filing pages a shortened amount always has its exact value one tap away and in VoiceOver
(D83). A related semantic gap: SEC's `NetIncomeLoss` is the parent's share of net income,
while DART's net income is the consolidated total, so the same key meant two things until
the mapping was split (D75).

**False refusal reasons found in review.** The refusal screen must say why a comparison is
refused, and review found several cases where it gave the wrong reason (D84, D85). An amount
request between two companies that both report in won borrowed the text for mismatched
periods and bases. Refusal sentences named the company the screen was opened from instead of
the company whose figures failed. A zero revenue in the margin comparison showed the growth
rate's title. An amount request across currencies with a missing figure reported the missing
figure rather than the currency. Each now has its own reason or a named culprit, and each of
the six refusal reasons is reached in the FootnoteKit and app tests.

**Data that silently went missing.** Ingest looked for titles starting with the annual report
name, so a corrected report never matched and two companies failed the build (D73). Four DART
companies file a single statement of comprehensive income, and the deduplication kept only
income-statement rows, which dropped their net income (D79). Both were found because the
export re-reads every figure from the pinned regulator files and reports every company and
metric without two years.

## Measured results

Counted on 2026-11-19 on commit `499ff40`.

| Measure | Result | How it was counted |
|---|---|---|
| Backend offline tests | 1669 passed, 66 skipped | `scripts/check.sh` (the `make test` step) |
| FootnoteKit tests | 129 tests in 21 suites, all passed | `scripts/check.sh` (`swift test`) |
| App unit tests | 37 `@Test` functions | Counted in `ios/FootnoteTests/`; not run for this count |
| UI tests | 12 test methods | Counted in `ios/FootnoteUITests/`; not run for this count |
| Comparison contract cases | 112 | `contracts/comparison-cases.json`, passed by both calculators |
| Gate | `GATE: PASS` | `scripts/check.sh` |

The app and UI tests were not run for this count because the one simulator slot was in use.
Pull request #35, the last one merged before this count, reports all 37 app tests passing on
an iOS simulator and on the Mac, and all 12 UI tests passing on an iOS simulator.

Development bundle (data date 2026-11-19, `allow_unapproved = 1`, counted with `sqlite3`):

| Table | Rows |
|---|---|
| Companies | 18 (9 DART, 9 SEC) |
| Filings | 196 (19 annual reports, 177 event filings) |
| Notices | 177 |
| Figures | 193, of which 4 are marked restated |
| Filing facts | 878 |
| Summaries | 0 (only approved summaries can be written) |
| Glossary rows | 92 (46 entries in two languages, all drafts) |

Summaries:

| Measure | Count |
|---|---|
| Filing sections in scope (summary build dry run) | 240: 20 already generated on the current prompts, 21 by template, 199 still to generate |
| Staged in `staged.jsonl` | 35 filing sections (70 rows, Korean and English): 33 passed the guard, 2 withheld |
| Approved | 0 |
| Glossary entries approved | 0 of 46 |

Approval is the owner's step. Pilot summary text is not quoted here; whether pilot examples
may be quoted is the owner's decision.
