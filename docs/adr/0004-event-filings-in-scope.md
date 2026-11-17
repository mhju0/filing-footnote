# Event Filings in Scope

Status: Accepted · 2026-11-17

Filing Footnote covers annual reports and event filings, such as buybacks, dividends, earnings releases and executive changes, from DART and SEC. Each filing is assigned to one category from a fixed list by deterministic rules on the regulator's own form type and report name; no model picks the category. Only structured facts the filing states, such as an amount, a date or a share count, are extracted for event filings; free-text interpretation is out of scope. This was chosen over an annual-only scope because most of what companies file between annual reports is event filings, and over model-assigned categories because a fixed list can be tested and a wrong category cannot appear silently.

## Details settled in M2

- The list and its rules live in `contracts/filing-categories.json`; `backend/app/filings/categories.py` applies them. Categories in priority order: earnings, unit_sales, buyback, dividend, capital, deal, leadership, legal. A filing that matches several takes the first.
- `unit_sales` was added on the owner's decision for monthly unit-sales reports (Kia and Hyundai file them under the same DART name as preliminary results) and production and deliveries 8-Ks. A plain `영업(잠정)실적(공정공시)` is told apart from quarterly results by the reporting period in its body, so the classifier needs the body for that name and returns `needs_body` without it.
- Filings about a subsidiary (`종속회사의주요경영사항`) are kept, classified by their base name and flagged, on the owner's decision.
- There is no per-company limit on event filings; the window is the latest twelve months.
- Everything else is excluded with a named reason and counted, including names that match no rule (`no_rule`). SEC keyword rules read only the 8-K primary document and EX-99 exhibits.

Evidence: `docs/audits/2026-11-event-sources/README.md` and the fixtures under `backend/tests/fixtures/events/`.
