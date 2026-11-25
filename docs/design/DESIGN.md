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
| Companies list | Bilingual company or ticker search; Korea / US browsing with visible sort; company name and 새 공시 tag | News | Newest event filings by date, with a filing-type filter | Filing page | Market commentary |
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
- 새 공시 / New: only on filings made within 7 days of the data date.
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
- G1 picks: language switch is a globe "EN" button in the nav bar; earlier years are a
  list; the compare-company picker is one list by market; direction is sign plus word with no
  colour; a restated figure has a 정정됨 / Restated tag beside the value and a note below.
- The quarter figure shows the original quarterly report before exact figures and calculation. The annual figure link stays labelled separately. Refusals have no calculation.
- State copy (board 19, approved): data date; "the 10 newest filings from the last 12
  months"; fewer than ten ("these are all N filings"); summary in review; numbers section
  hidden when empty; outlook without figures; corrected filing; notices row hidden.
  There is no loading or offline state because the app reads a bundled file.
