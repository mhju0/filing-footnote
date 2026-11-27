# Product

<!-- impeccable:product-schema 1 -->

## Platform

ios

One SwiftUI multiplatform app for iPhone, iPad and Mac. The owner's devices are an
iPhone 12 mini and 13 mini (latest iOS), an iPad Pro 11-inch (3rd gen) and an M1 Pro Mac,
so the smallest screen (5.4-inch mini) is the layout floor.

## Users

- **Casual first-time viewers** of the recorded walkthrough and anyone handed the phone:
  people who know company names like Samsung or Apple but do not read annual reports.
  They must understand what to do and what a figure means without help.
- **Hiring reviewers** evaluating the project as a portfolio piece: they watch the
  walkthrough, then may open the repository to check the data pipeline and tests.

## Product Purpose

Filing Footnote summarises what well-known Korean and US companies officially filed (annual
reports and event filings such as buybacks, dividends, earnings releases and management
changes) in plain, neutral words, with every figure and statement traceable to the filing
it came from. It is a portfolio piece first and the owner's own daily reader second.
Success: a first-time viewer picks a company and, within seconds, can say how it did last
year and why they can trust the number.

## Positioning

Figures come from official filings (DART and SEC), are checked before they ship, and are
calculated with exact decimals. Every comparison shows its calculation and the checks it
passed, and the app says plainly when a comparison would be misleading instead of
guessing. It explains; it does not advise or trade.

## Operating Context

- Runs entirely on the device from a bundled, read-only data file. No accounts, servers,
  sign-in, or network needed to use it.
- Explanations are written in advance by a build step on the owner's Mac; the app does
  not chat or generate text on the phone. Its fixed questions ("Ask about this company")
  are answered on the device by code that picks approved fixed sentences and the bundled
  figures (D99).
- Primary demonstration is a recorded screen walkthrough, Korean first, then a one-tap
  switch to English.

## Capabilities and Constraints

- 18 companies (Korean and US): each company's latest annual report and up to ten recent
  filings from the last 12 months, with two years per figure (2026-11-19, owner; D72,
  D76). The filings are official company filings a shareholder would want to see: results,
  unit sales, company outlook, buybacks, dividends, capital, deals, leadership, legal
  matters, shareholder value, shareholder meetings, operations, loans and guarantees,
  management matters and answers to press reports. Notices (IR events, record dates and
  similar) are listed together on one row and are not summarised. Metrics: revenue,
  operating income, net income, net income attributable to owners, EPS, diluted EPS, and
  derived operating margin.
- Quarter report: each company's latest quarterly report shows the quarter's figures next to
  the same quarter a year earlier, with the change, as on design board 15. (2026-11-19,
  owner: quarter report in v0.1; D88)
- Company outlook ("회사 전망 / Company outlook") shows what the company forecast, always
  attributed to the company and never used in a comparison; the app does not compute a
  gap against a forecast. (2026-11-19, owner)
- Core flow is filing-first: pick a company → see its recent filings → open one to read
  what it says and the numbers it states → tap a figure for its meaning and earlier years →
  compare with last year or with another company → see the calculation → open the source
  filing. A glossary explains terms. (2026-11-18, owner: "they pick a company, and we list
  the recent filings and let them pick the filing and go from there")
- Comparisons: same company, metric, currency, basis and period end; no percentage when
  the baseline is zero or negative; cross-company comparisons use ratios and percentages
  only, never currency conversion, with a caveat about differing accounting standards
  (K-IFRS vs US GAAP) and year-ends. Restated figures are labelled.
- Refusal reasons the UI must explain: ambiguous request, unsupported basis, metric out of
  scope, missing period, incompatible currency, incompatible comparison.
- Ask about this company (2026-11-26, D99): six fixed questions on the company page,
  directly under its summary card (D106). Should I buy this? What are the fundamentals? What's the recent
  trend? Does it make or lose money? How is revenue doing? What's next quarter's revenue?
  Each answer uses only the bundle: the latest annual report's approved business lines and
  exact figures from the latest quarter and fiscal year, each against the same period a
  year earlier, with its source filing. A missing figure is said to be missing, never
  shown as zero. The buy and next-quarter questions say what the app does not do, then
  point to the reported facts and the company's own outlook filing when there is one.
- Korean and English throughout. Korean text wraps only between words.
- Typed questions on iPad and Mac only, where Apple's on-device model is available (D108):
  the model may only choose one of the fixed questions or none, and the same code answers
  it (D99). iPhone minis cannot run it, and the iPhone page is unchanged.

## Brand Commitments

- Name: Filing Footnote; home-screen name "Footnote".
- Professional, because it is a financial app, but very friendly so casual users are not
  scared off: modern, easy to use, easy to follow. Friendly means clear and approachable,
  not decoration such as sparkles. (2026-11-17, owner: "professional looking ... but we
  need aspects of friendly look and feel ... I'm not talking about like sparkles")
- Visual style stays standard and professional: no themed metaphor (report card,
  boarding pass, health app, streaming shelf were all rejected). "Easy" comes from the
  information and the flow: each screen spaced out and showing less, with an obvious next
  tap for a first-time user. (2026-11-17, owner: "I do want the theme to be very just kind
  of standard-ish ... show less information ... When I meant casual, I meant easy to
  understand and easy to navigate")
- Quality bar: Apple's own apps (Stocks, Wallet, Settings: native controls, large titles,
  grouped lists) and Stripe / Mercury (restrained colour, precise numbers, clean
  hierarchy). (2026-11-17, owner)
- Palette (2026-11-17, owner picked A): Pine #10645B for actions, links and category marks;
  Saffron #E9A23B only for "new" and one highlight per screen; Ink #152A31 for text and the
  dark latest-filing card. Up and down never use these colours alone.
- The previous "Ledger" look inherited from Filing Digest is rejected for this product as
  flat and unclear. (2026-11-17, owner)

## Evidence on Hand

- Verified figures: `docs/audits/2026-09-07-coverage/pilot-snapshot.json` (copied from
  Filing Agent's 2026-09-07 coverage audit), e.g. Samsung Electronics FY2023 revenue
  258.94조 원, −14.33% year over year.
- Data pipeline, guards and tests inherited from Filing Digest in `backend/`.
- No testimonials, users, ratings or usage numbers exist; never invent them.

## Product Principles

1. The first screen answers "how did it do?" before anything else.
2. Every number can show where it came from and how it was calculated.
3. Plain words first, the formal term kept nearby.
4. Say no clearly: a refused comparison explains why and what is possible instead.
5. Nothing on screen is advice to buy or sell.
6. Never exaggerate. Neutral, factual wording only: no hype or judgement words, no
   predictions; state what the filing says and attribute it to the company. (2026-11-17,
   owner: "never exaggerate anything ... be very neutral and give factual information")

## Accessibility & Inclusion

Dynamic Type, VoiceOver labels on every figure and control, 44 pt targets, light and dark
appearance, color never the only signal of up or down (Korean markets read red as up, so
direction is always shown as a ▲ or ▼ glyph with a word, and VoiceOver says 증가 / increased
or 감소 / decreased; D106).
