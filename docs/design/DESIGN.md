# Filing Footnote Visual System

Direction: professional and friendly, standard native look. Apple's own apps
(Stocks, Wallet, Settings) and Stripe or Mercury are the quality bar. Each screen
shows less and offers one obvious next tap. There is no themed metaphor. This
replaces the Ledger system inherited from Filing Digest. Older files under
`explorations/` and `logos/` stay as history. Product rules are in `PRODUCT.md`.

## Palette

| Token | Hex | Use |
|---|---|---|
| Pine | `#10645B` | Primary: actions, links, selected tab, category marks |
| Saffron | `#E9A23B` | Accent: only the "새 공시" tag, plus at most one highlight per screen. Text on it is Ink |
| Ink | `#152A31` | Text |
| Tint | `#E7F0EE` | Category mark and selected-row background |
| Background | `#F5F6F8` | Screen background |
| Muted | `#5B6475` | Secondary text |
| Line | `#E6E9EE` | Separators |

Measured contrast: white on Pine 7.01, Ink on Saffron 6.89, white on Ink 14.92,
Pine on Tint 6.04.

Dark appearance (2026-11-19):

| Token | Light | Dark |
|---|---|---|
| Pine | `#10645B` | `#5CC2B2` (text on Pine is Background) |
| Saffron | `#E9A23B` | `#E9A23B` (text on it stays Ink) |
| Ink (text) | `#152A31` | `#E9EEF0` |
| Tint | `#E7F0EE` | `#173A35` |
| Background | `#F5F6F8` | `#0E1315` |
| Surface (grouped rows) | `#FFFFFF` | `#192024` |
| Muted | `#5B6475` | `#9BA5B3` |
| Line | `#E6E9EE` | `#2A3237` |

Measured dark contrast: text on Background 15.99, on Surface 14.10; Muted on Background
7.51, on Surface 6.62; Pine on Background 8.74, on Surface 7.71, on Tint 5.80; Background
on Pine 8.74; Ink on Saffron 6.89. Every pair meets WCAG AA for body text.

App icon: the bracketed F mark (`logos/`) in white on Pine, full bleed, no gradient.
Platforms: iPhone tab bar; iPad and Mac sidebar, content and detail columns
([ADR 0008](../adr/0008-native-multiplatform-app.md)).

## Rules

- SF system fonts only. Numbers use tabular figures.
- Layout floor is iPhone mini (375 pt wide). Targets are at least 44 pt.
- Korean wraps only between words (`keep-all` behaviour).
- Direction is always a sign plus a word ("+6.4% 늘었어요"), never colour alone.
  Korean markets read red as up, so up and down do not use red or green alone.
- Not used: cream backgrounds, pill buttons, italic accents, monospace labels.
- Dynamic Type, VoiceOver labels on every figure and control, light and dark.

## Tabs

기업 · 소식 · 용어

## Screens

The flow is filing-first (`PRODUCT.md`). Every limit below is a maximum; a part with no
data is removed, never shown empty. Picks are from the design canvas
(https://claude.ai/artifact/8zsRsVmN6gQrfzYWhJeYFh): G1 boards 1–10 all A (2026-11-18,
owner), boards 11A, 12A, 13 and 14–20 (2026-11-19, owner).

| Screen | Shows | One tap away | Never shown |
|---|---|---|---|
| Companies list | One line on what the app does, with the data date; the system search field (company or ticker, both markets); Korea / US browsing; sort as a toolbar menu showing the current order; company name, then its newest filing date and type (D98) | News | Newest event filings by date, with a filing-type filter | Filing page | Market commentary |
| Glossary | Term search and letter or initial jump; definitions expand on iPhone | Definition on iPad and Mac | |
| Company page | Up to 2 periodic reports with one figure each; six questions to ask (D99) as wrapping rounded-rectangle buttons, Pine on Surface with a Line border; up to 10 filings grouped by month (tag, date, title); notices row; insider row; data date | Notices sheet, insider screen, all filings on DART, an answer | Price, news, analyst views, scores, a preview line per filing row |
| Answer | Company and question; fixed sentences in a card; the company's business lines; the latest quarter's and year's figures against a year earlier, each block with its source filing; related questions after a deflection; how answers are made | Source filing, outlook filing, exact amounts on tap | Advice, estimates, judgement words, a figure for a future period |
| Filing page | Tag and status, title, date; outlook banner (outlook only); up to 3 sentences; how they were written; up to 6 numbers; up to 2 related filings; original | Glossary, other versions | Model confidence, judgement words, a gap against a forecast |
| Quarter report | 3 figures, each against the same quarter last year; related preliminary filing; IR materials link | Quarter figure detail leads with its amount and comparison period; exact amounts, dates and calculation are expandable | Quarter-on-quarter change, charts |
| Annual at a glance | One line, then 무슨 사업, 무엇이 바뀌었나, 회사가 꼽은 위험, 핵심 숫자 | Figure, compare | |
| Notices sheet | Medium-detent sheet: date, title, related filing, original link | | Summaries |
| Insider and ownership (later) | 12-month counts, then a dated list: person, role, shares | Each report on DART | Net buying or selling words, commentary |
| Figure | Meaning, earlier years as a list, calculation | Compare | |
| Compare | With last year or another company (growth and margin only, caveat on standards and year-ends); refusal says why and what is possible | Calculation | Currency conversion |

Details:

- Company page: periodic reports are pinned above the filings; the subtitle is the data
  date ("11월 18일까지 낸 공시 / Filings up to Nov 18"); the list ends with a note on what
  it covers and a link to every filing on DART or SEC.
- 새 공시 / New: only on event filings made within 7 days of the data date. Annual,
  half-year and quarterly reports never carry it, and the Companies list shows no tag (D98).
- Notices row: "안내 공시 N건 / N notices", counting notices filed in the same span as
  the listed filings; hidden when there are none.
- Filing page order is fixed for every type: sentences, then numbers, then the original. The Original section shows the filed date and regulator link first. Form and receipt number expand in Filing details.
- Company outlook: banner saying it is the company's forecast; a corrected forecast shows
  old and new values side by side; the filing's own prior-year target and result may be
  shown, but the app computes no gap.
- Clarification: the press report as quoted, the company's answer, its status and the
  re-filing due date, and earlier answers to the same report.
- Corrected filings: 정정됨 / Corrected tag; the corrected version shows, the first opens
  from "다른 버전 / Other versions".
- G1 picks: language switch is a globe "EN" button in the nav bar (on the Mac, one button
  at the trailing end of the window toolbar, D98); earlier years are a
  list; the compare-company picker is one list by market; direction is sign plus word with no
  colour; a restated figure has a 정정됨 / Restated tag beside the value and a note below.
- The quarter figure shows the original quarterly report before exact figures and calculation. The annual figure link stays labelled separately. Refusals have no calculation.
- State copy (board 19, approved): data date; "the 10 newest filings from the last 12
  months"; fewer than ten ("these are all N filings"); summary in review; numbers section
  hidden when empty; outlook without figures; corrected filing; notices row hidden.
  There is no loading or offline state because the app reads a bundled file.
- 2026-11-26 UX review and design picks (D98):
  - Glossary order: 자주 보는 용어 / Key terms (revenue, operating income, net income, EPS,
    operating margin) first, then the dictionary by initial, then the reasons a comparison
    is refused under their own heading. A jump menu of at least 44 pt is in the toolbar on
    every platform; current iOS also keeps the native index.
  - Figure screen: the headline is rounded as on the company page ("333조 6,059억원");
    the exact amount sits on a smaller line below ("정확한 금액 333조 6,059억 3,800만원" /
    "Exact amount …"). VoiceOver reads the exact amount.
  - A gap between two rates is written "4.18%포인트" / "4.18 percentage points", never
    "%p" or "pp", and links to its glossary entry.
  - Mac copy says 선택하면 / Select where touch screens say 누르면 / Tap. Section notes wrap.
  - Mac disclosure rows keep their chevron inside the row inset. Rows of full-width buttons
    have no separator.
  - Empty search and empty News use the system empty state with a magnifying glass and the
    app's own bilingual copy.

## First-run guide and tips (D104)

Owner picks of 2026-11-26 (first-run guide and tips study: q1 A, style D, reopen A,
tips E, timing B). The copy is the owner's and is not reworded.

- Guide: four pages, shown once on the very first launch, over 기업 / Companies. A
  full-screen cover on iPhone, a form sheet on iPad, a 520 × 620 sheet on Mac. Pages 1, 2
  and 4 are an SF Symbol in a Tint square, a title and a body; page 3 shows the real
  company page, drawn by the app's own views at a fixed text size and scaled down, so it
  follows the language, the appearance and the data. Every page has 건너뛰기 / Skip at the
  top trailing edge (Esc on a keyboard), page dots (one adjustable VoiceOver element,
  "페이지 2/4"), and a full-width Pine button: 다음 / Next, then 시작하기 / Get started.
  iPhone and iPad swipe between pages; ← and → work with a keyboard. Pages slide; with
  Reduce Motion, Next, the dots and the arrow keys change pages without animation. At accessibility sizes
  the page scrolls and the button stays pinned.
- Skip, Get started and closing the sheet mark the guide seen; quitting the app mid-guide
  does not. It reopens from "Footnote 안내 다시 보기 / Show the Footnote guide again", the
  last row of 용어 / Glossary, and from Help ▸ Footnote 안내 / Footnote Guide.
- Tips: TipKit popovers on the one control they explain, never a centred pop-up or a
  sheet. An inline TipView is for a tip about a whole screen; none of the kept tips is one.
  At most one new tip a day; none while the guide is up; ✕ or using the feature ends a tip
  for good, and one ignored on three visits retires.

| Tip | On | Shows from | Ends when |
|---|---|---|---|
| 숫자를 누르면 출처가 보여요 / Tap a figure to see its source | The company page's first report row (the figure) | Second company page | A figure or report is opened |
| 질문을 눌러 보세요 / Tap a question | The first question to ask | Third company page, after the figure tip ends | A question is tapped |
| 작년과 비교해 보세요 / Compare with last year | 작년과 비교 on the figure screen | Second figure screen | Either comparison is opened |
| 공시 종류로 골라 보기 / Filter by filing type | The News filter | Second visit to 소식 / News | A filing type is chosen |
