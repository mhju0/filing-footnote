# Event Filings in Scope

Status: Proposed · 2026-11-17

Filing Footnote covers annual reports and event filings, such as buybacks, dividends, earnings releases and executive changes, from DART and SEC. Each filing is assigned to one category from a fixed list by deterministic rules on the regulator's own form type and report name; no model picks the category. Only structured facts the filing states, such as an amount, a date or a share count, are extracted for event filings; free-text interpretation is out of scope. This was chosen over an annual-only scope because most of what companies file between annual reports is event filings, and over model-assigned categories because a fixed list can be tested and a wrong category cannot appear silently.
