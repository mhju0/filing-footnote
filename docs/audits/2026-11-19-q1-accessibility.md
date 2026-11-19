# Q1 accessibility and QA pass, 2026-11-19

Roadmap Q1, on branch `qa/accessibility-pass` from `main` `499ff40`. Checked against
PRODUCT.md (Accessibility & Inclusion), `docs/design/DESIGN.md` and the shared UI checklist.

## How it was checked

- Simulators made for this pass and deleted afterwards: "Audit Footnote iPhone 13 mini"
  (iOS 27.0, 375 × 812 points) and "Audit Footnote iPad Pro 11" (11-inch, 3rd generation,
  iOS 27.0, landscape). One simulator job at a time was the rule; it slipped twice (see "Run
  discipline" below). The iPad run was narrowed for time (item 34).
- `FootnoteUITests/AccessibilityAuditUITests`: Apple's `performAccessibilityAudit()` on
  twenty-one screens, in six configurations (Korean and English × default size,
  Accessibility XL, dark mode). Each screen is audited at the top and again after each
  swipe up. The tests run on the FootnoteKit fixture with glossary rows added under the D81
  keys.
- `AccessibilityLabelsUITests`: every hittable button has a label and is at least 44 × 44
  points; figures read their values and directions in words; the figure screen's reading
  order runs top to bottom.
- `CoreFlowUITests`: the core flow in Korean and in English (below).
- `testTextGrowsAtAccessibilitySizes`: section headers, body text, action buttons, filing
  rows and the periodic-report header are at least 1.4 times taller at Accessibility XL.
- Screenshots on the development bundle (data as of 2026-11-19), `docs/screenshots/footnote/q1-*`,
  each looked at. Audit screenshots of every pass were looked at where the audit reported a
  finding without an element.

The Mac screen was locked (`CGSSessionScreenIsLocked`) for the whole pass, so nothing on the
Mac display was checked; see the last section.

## Results

Screenshots are in `docs/screenshots/footnote/` (`q1-mini-…` on the iPhone mini,
`q1-ipad-…` on the iPad). "AX" is Accessibility XL; "AX5" is the largest size.

Counts: 36 items. 19 pass, 8 fixed, 8 open with a reason (3 of them minor), 1 partly run
(the iPad suite, item 34). Six Mac and VoiceOver items are not verified (last section).

| # | Item | Result | Screenshot |
|---|---|---|---|
| 1 | Audit, Korean, default size, every screen and scroll position | Pass (mini, 21 screens). iPad: not run, see 34 | q1-mini-compare-samsung-apple-margin-ko-light |
| 2 | Audit, Korean, Accessibility XL | Pass (mini, rerun on the final code) | q1-mini-company-samsung-ko-ax |
| 3 | Audit, Korean, dark | Pass (mini). iPad: the audit timed out ("Audit failed to complete in time", load average about 10); see 34 | q1-mini-company-samsung-ko-dark |
| 4 | Audit, English, default size | Pass (mini). iPad: not run, see 34 | — |
| 5 | Audit, English, Accessibility XL | Pass (mini, rerun on the final code). iPad: a full pass over all 21 screens left one finding (the compare picker's `Amount` row, shown in full), now filtered; the rerun after that filter timed out under load | q1-mini-news-en-ax-tags, q1-mini-yearcompare-samsung-revenue-en-ax, q1-mini-filing-outlook-hyundai-en-ax |
| 6 | Audit, English, dark | Pass (mini) | q1-mini-compare-samsung-apple-margin-en-dark |
| 7 | Text grows at the accessibility sizes (headers, body, buttons, rows) | Pass (mini) | q1-mini-figure-samsung-revenue-ko-ax |
| 8 | Every hittable button has a label, Korean and English, all 21 screens | Pass (mini, rerun on the final code) | — |
| 9 | Tap targets at least 44 × 44 points (content controls) | Fixed: the compare screen's segmented control was 32 points tall; now extra large. Checked by the labels test (mini) | q1-mini-compare-samsung-apple-margin-ko-light, q1-mini-compare-samsung-apple-margin-ko-ax-bottom |
| 10 | Tap targets in the navigation and tab bars | Pass (system sized). The language button reports a 36-point content frame; iOS sizes its glass capsule and touch area, and the audit's hit-region check passes | — |
| 11 | Figures read values and directions in words (`전년보다 16.20퍼센트 늘었어요`, `percentage points`) | Pass (mini, rerun on the final code) | — |
| 12 | Reading order on the figure screen (value, meaning, glossary, years, actions) | Pass (mini, rerun on the final code) | — |
| 13 | Decorative images hidden from VoiceOver | Pass (code review): every `Image(` is `accessibilityHidden` or inside a labelled control. XCUITest lists hidden images too, so this is not a UI test | — |
| 14 | Contrast of every text colour | Pass (measured): lowest pair Muted on Line, 4.9:1 light, 5.23:1 dark; Muted on Background 5.51:1; Pine on Tint 6.04:1 light, 5.8:1 dark | — |
| 15 | Section headers contrast | Fixed: system header grey replaced by Muted | q1-mini-company-samsung-ko-ax |
| 16 | Selected company in the iPad sidebar | Fixed: Ink and Muted on the Pine fill; now the system's primary style (light on Pine, dark on the grey fill while another column has focus). Checked on screenshots and frames of the test video | q1-ipad-company-samsung-ko-light |
| 17 | Long tag pushes a row past its card at AX (`Management matters`, company page and News) | Fixed: the tag wraps inside the row | q1-mini-news-en-ax-tags |
| 18 | Company names break inside a word at AX (`SK하/이닉/스`) | Fixed: the ticker moves under the name | q1-mini-companies-ko-ax |
| 19 | Numbers break inside their digits at AX (equation, difference, fact rows, receipt number) | Fixed: wrap only at spaces; a number wider than the line shrinks to fit. VoiceOver still reads each as one text | q1-mini-calc-samsung-revenue-ko-ax |
| 20 | Orphan word on the figure line (`늘었어요 · 작년보다`) | Fixed: phrase lines `+16.20%` / `늘었어요 · 작년보다` | q1-mini-figure-samsung-revenue-ko-ax |
| 21 | Orphan `줘요.` in the amounts note | Fixed: one no-break space, `보여 줘요`; wording unchanged | q1-mini-annual-samsung-ko-ax-numbers |
| 22 | Figure line at AX5 | Open: `늘었어요 ·` / `작년보다`; no single phrase fits the line at that size, so it wraps between words | q1-mini-figure-samsung-revenue-ko-ax5 |
| 23 | Annual report rows `+10.88%` / `늘었어요` at AX | Open: a two-word line whose only break is between the rate and its direction; both halves are full words | q1-mini-annual-samsung-ko-ax-numbers |
| 24 | Subtitle `… · 연결` / `기준` breaks at AX | Open, minor: breaks between words; joining would need a no-break space inside approved copy | q1-mini-calc-samsung-revenue-ko-ax |
| 25 | English company title truncates at AX and AX5 on iPhone (`Samsung Ele…`, `Samsung E…`) | Open: the system navigation large title truncates long names; VoiceOver reads the full name. A fix means a custom title in place of the system one. On the iPad it shows in full | q1-mini-company-samsung-en-ax5 |
| 26 | English inline title truncates on scroll (`Samsung Elec…`) | Open: system navigation bar title, same cause as 25 | — |
| 27 | English titles with a hyphen break at it at AX (`(8-` / `K)`) | Open, minor: English line breaking at a hyphen, no Korean rule involved | q1-mini-news-en-ax |
| 28 | English periodic row ends `+10.88%,` / `up` at AX | Open, minor: English wording ends on one short word; fixing it needs a no-break space in approved copy or a layout like the Korean figure line | — |
| 29 | Notices sheet at AX | Pass: introduction and rows show in full | q1-mini-notices-hyundai-ko-ax |
| 30 | Refusal screens at AX (missing baseline, currency, period, year, ambiguous) | Pass: reason and alternatives show in full; audited in all six configurations on the mini | q1-mini-refusal-baseline-ko-ax, q1-mini-picker-samsung-ko-ax |
| 31 | Glossary and News tabs at AX | Pass | q1-mini-glossary-en-ax, q1-mini-news-en-ax |
| 32 | Core flow in Korean and English on the iPhone mini (company → filing → figure → years → last year → other company with caveat → calculation → source → glossary → refused comparison → English) | Pass (both languages) | — |
| 33 | Core flow on the iPad Pro 11, landscape split view | Open: passes company → filing → original → annual report → figure; then the tap on `작년과 비교` in the detail column does not open the comparison in the UI test. The existing `FigureCompareUITests` fails at the same step on `main` 499ff40 on the same iPad, so it predates this pass. Cause not found; no hands-on tapping was possible | q1-ipad-figure-samsung-revenue-en-light |
| 34 | Full UI test suite on the iPad Pro 11 | Partly run, narrowed for time. Passed: filing pages (annual, approved summary); News by day, tags, empty state, no glossary; filing to glossary link. Failed, each also failing or untestable before this pass: the detail-column comparison (33, figure compare); the test helpers' `swipeUp` scrolls the window centre, which on the iPad is the content column (event filing's original button, figure link to the glossary); the glossary test taps the iPhone tab bar. Audits: see 3 and 5. Not run on the iPad: Korean and English default, Korean AX and English dark audits, the labels suite, text growth | q1-ipad-company-samsung-ko-light |
| 35 | Unit tests, iOS and macOS | Pass: iOS 38 tests in 9 suites; macOS 38 tests in 9 suites | — |
| 36 | `scripts/check.sh` | Pass: `GATE: PASS` (backend tests, FootnoteKit 129 tests in 21 suites, project.yml match, no currency conversion) | — |


## Findings and fixes

- **Bars hid everything.** The first filter version treated any element inside a
  navigation, tab or toolbar frame as "under the bar". iOS 27 reports one toolbar the size of
  the window, so every element matched. Only strips at the top or bottom count now, and the
  audits were rerun.
- **Contrast after a swipe.** After a swipe the audit reports text that is plainly legible
  in that pass's screenshot (`Oct 29, 2026` in Ink on white, 13.8:1), at frames that do not
  match where the text is drawn. Every text colour was measured instead (item 14); text after
  a swipe is filtered for contrast, and the first pass of each screen is checked as it
  stands.
- **Clipped text after a swipe.** The same mismatch reports text near the end of a list as
  clipped (`금액은 줄여서 보여 줘요.`, `2 notices`, `See every filing on DART`); each shows in
  full in its pass's screenshot. Filtered after a swipe only.
- **`원문` header.** The short header on the filing pages is reported at low contrast at the
  top of the page; it is Muted on Background (5.51:1) like `공시 내용` above it, which passes.
  Filtered by name.
- **Language switch in tests.** The UI tests launch with `-language`, which pins the stored
  language for the run, so a tap on the switch could not change it there. The core flow now
  opens the figure again without that argument and switches there and back. In the app the
  switch works (the existing behaviour, unchanged).
- **Figures read as one text.** Splitting a figure line into tokens so it never breaks
  inside a number first made VoiceOver read each token separately (an existing UI test caught
  it: `정확한 값 11억 3,498만원`). The line is one accessibility element again.
- **Element-less findings.** Some contrast, Dynamic Type, clipped-text and (English only)
  "Potentially inaccessible text" findings name no element. Each such pass was checked
  against its screenshot; the log prints them as `FILTERED|…|`.
- **Dynamic Type.** The audit flags most SwiftUI text as not supporting Dynamic Type. The
  growth test measures the same text more than 1.4 times taller at Accessibility XL, so the
  finding is filtered for static text and buttons.
- **Selected sidebar row on iPad.** The selected company in the iPad sidebar kept its Ink
  name and Muted ticker on the Pine selection fill, hard to read in every language and size.
  The audit did not report it (it measured the sidebar glass instead); the iPad screenshots
  showed it. The row now uses the system's primary style while selected, as the labels
  beside it do: light on Pine, dark on the grey fill iOS draws while another column has
  focus (a fixed OnPine was tried first and was white on grey there).
- **iPad sidebar glass.** On iOS 27 the sidebar floats over the content column, which starts
  at the leading edge underneath it. The audit measures sidebar text (`Korea`, `Glossary`)
  and content headers whose frame starts under it (`Periodic reports`) against the blurred
  glass, and reports `News` and `Glossary` as clipped although they show in full. Filtered
  by the sidebar's frame (contrast) and by name (the two labels).
- **Run discipline.** Twice in this pass a second simulator job started while a UI test run
  was still going (a build, and once the screenshot script with a test). Both overlapping runs
  were thrown away and rerun alone. Once more, `scripts/check.sh` (no simulator, but backend
  and Swift tests) ran beside the final mini audit; the load rose to about 28 and the English
  AX audit stopped with "Audit failed to complete in time". It was rerun alone. The same
  timeout ended the iPad audits under a load of about 10.

Run the audit with the filters off to see every finding:
`TEST_RUNNER_FOOTNOTE_AUDIT_RECORD=1` prints each finding as `AUDIT|…` without failing, and
`TEST_RUNNER_FOOTNOTE_AUDIT_SHOTS=<folder>` saves a screenshot of each pass.
`TEST_RUNNER_FOOTNOTE_AUDIT_ONLY=company,news` limits the screens.


## Not verified (screen locked)

The Mac's screen was locked during the whole pass. These need a person at the Mac:

| Item | Result | Why |
|---|---|---|
| Mac window screenshot (split view, light and dark) | Not verified | No window server session to capture. |
| Mac arrow keys move the selection in the sidebar, company, news and glossary lists; Return opens | Not verified | Needs keyboard input on an unlocked screen. |
| Mac selection highlight (Tint) and focus ring | Not verified | Needs the screen. |
| Live VoiceOver on the Mac | Not verified | VoiceOver needs an unlocked session. |
| Live VoiceOver on an iPhone | Not verified | The simulator has no VoiceOver; no device was attached. Labels and order are checked through the accessibility tree instead. |
| macOS UI test | Not run | The `FootnoteUITests` target is iOS only, and a Mac UI test needs an unlocked screen. The macOS unit tests ran and passed. |
