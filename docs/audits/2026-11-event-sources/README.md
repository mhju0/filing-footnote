# Event-filing source spike, 2026-11-17

Milestone M1 of Filing Footnote v0.1. This record answers what the DART and SEC
event-filing sources return before any ingest is built on them. It is a sample, not a
coverage claim.

Tags: [Verified] = seen in a live response saved as a fixture or run on 2026-11-17;
[Inferred] = reasoning from those responses; [Unknown] = not established.

## How it was run

- Script: `backend/scripts/sample_event_sources.py` (read-only; no database writes).
  Run from `backend/`: `../.venv/bin/python scripts/sample_event_sources.py --report`.
- Window: filings received 2025-11-18 to 2026-11-17 inclusive (`--as-of 2026-11-17`).
- Companies: the nine DART companies (005930, 000660, 035420, 005380, 000270, 006400,
  051910, 066570, 207940) and the nine SEC companies (AAPL, MSFT, NVDA, TSLA, AMZN,
  COST, GOOGL, META, WMT) of the existing corpus.
- Requests in the final run: DART 51, SEC 19. Two earlier development runs (46 and
  45 DART calls) and 12 hand-made DART calls came before it; one hand check (Kia's monthly filing,
  below) is not saved as a fixture.
- Fixtures: `backend/tests/fixtures/events/` (61 files, 944 KB). Machine-readable
  results: `sample_summary.json` and `dart/report_nm_tally.json` in that folder.
- Secrets: the script scans every fixture for the DART key after writing, also when a
  run fails, and printed
  `key leak check: clean`; `grep -rc crtfc_key backend/tests/fixtures/events/` found
  no matches.

## Counts

[Verified] DART `list.json`, one page per query (`total_page` was 1 in all 18):

| Company | Stock code | B (주요사항보고) | I (거래소공시) |
|---|---|---:|---:|
| Samsung Electronics | 005930 | 10 | 71 |
| SK Hynix | 000660 | 13 | 87 |
| NAVER | 035420 | 7 | 57 |
| Hyundai Motor | 005380 | 4 | 81 |
| Kia | 000270 | 2 | 81 |
| Samsung SDI | 006400 | 1 | 43 |
| LG Chem | 051910 | 1 | 61 |
| LG Electronics | 066570 | 3 | 35 |
| Samsung Biologics | 207940 | 7 | 62 |
| **Total** | | **48** | **578** |

[Verified] SEC submissions, forms 8-K and 8-K/A filed in the window: 114 rows
(8-K/A: Apple 1, Walmart 2).

| Ticker | Rows | Items |
|---|---:|---|
| AAPL | 10 | 2.02 ×4, 5.02 ×4, 5.07, 8.01, 9.01 ×6 |
| MSFT | 11 | 2.02 ×4, 5.02 ×4, 5.07, 7.01, 8.01 ×2, 9.01 ×8 |
| NVDA | 14 | 1.01, 2.02 ×4, 2.03, 5.02 ×6, 5.07, 7.01, 8.01 ×2, 9.01 ×7 |
| TSLA | 9 | 1.01, 1.02, 2.02 ×8, 2.03, 9.01 ×9 |
| AMZN | 16 | 1.01 ×2, 2.02 ×4, 2.03, 5.02, 5.07, 7.01 ×3, 8.01 ×7, 9.01 ×14 |
| COST | 10 | 2.02 ×4, 5.02 ×2, 5.07, 8.01 ×5, 9.01 ×9 |
| GOOGL | 16 | 1.01 ×2, 2.02 ×4, 3.03, 5.02 ×5, 5.03, 5.07, 7.01, 8.01 ×6, 9.01 ×12 |
| META | 13 | 1.01 ×2, 2.02 ×4, 3.03, 5.02 ×3, 5.03, 5.07, 8.01 ×5, 9.01 ×9 |
| WMT | 15 | 2.02 ×4, 3.01, 5.02 ×5, 5.03, 5.07, 7.01, 8.01 ×5, 9.01 ×10 |

Items 3.01 and 3.03 were not in the build plan's item list.

## DART report names

[Verified] Full per-company counts with one example `rcept_no` each are in
`dart/report_nm_tally.json`. Leading bracket prefixes are stripped and runs of spaces
collapsed; DART pads some names with spaces before a trailing parenthesis.

B, 10 distinct names. Every one is `주요사항보고서(<name>)`: 자기주식처분결정 20,
유상증자결정 9, 자기주식취득결정 7, 타법인주식및출자증권양수결정 4,
자기주식취득신탁계약체결결정 2, 해외증권시장주권등상장결정 2, 감자결정 1,
자기주식취득신탁계약해지결정 1, 타법인주식및출자증권양도결정 1, 해외증권시장주권등상장 1.

I, 69 distinct names. The names the build plan needed, exactly as filed:

| Plan category | Exact `report_nm` | Rows |
|---|---|---:|
| earnings | 연결재무제표기준영업(잠정)실적(공정공시) | 49 |
| earnings (see below) | 영업(잠정)실적(공정공시) | 28 |
| dividend | 현금ㆍ현물배당결정 | 18 |
| buyback | 주식소각결정 | 8 |
| deal | 단일판매ㆍ공급계약체결 / 단일판매ㆍ공급계약체결(자율공시) | 13 / 4 |
| leadership | 대표이사(대표집행임원)변경(안내공시) | 7 |
| legal | 소송등의제기ㆍ신청(경영권분쟁소송) / 소송등의판결ㆍ결정 | 1 / 1 |

The most frequent I names fall outside the plan's categories: 기업설명회(IR)개최(안내공시) 99,
최대주주등소유주식변동신고서 60, 풍문또는보도에대한해명(미확정) 19, 장래사업ㆍ경영계획(공정공시) 17,
기타경영사항(자율공시) 15, 주주총회소집결의 15, 현금ㆍ현물배당을위한주주명부폐쇄(기준일)결정 13,
감사보고서제출 12, 타법인주식및출자증권취득결정 11, 정기주주총회결과 10. The tally file lists all 69.

[Verified] Prefixes seen: only `[기재정정]` and `[첨부추가]`. `rm` values: B rows `''` 38
and `정` 10; I rows `유` 514 and `유정` 64. Every row has `corp_cls = Y`. Three I rows
were filed by 유가증권시장본부 (the exchange), not the company.

### Monthly sales reports filed as 영업(잠정)실적

[Verified] Kia files `영업(잠정)실적(공정공시)` every month (16 rows in the window
including four quarterly `연결재무제표기준…` ones). The 2026-11-02 filing
(`20261102800493`) reports 판매대수 (units sold, domestic and overseas) for October;
its 매출액, 영업이익 and 당기순이익 rows are all `-`. [Verified] Hyundai Motor's 16 rows
have the same shape: 12 plain `영업(잠정)실적` filed early each month and four quarterly
`연결재무제표기준…` ones. [Inferred] Hyundai's monthly ones are also sales reports; none
was opened. These are monthly sales-volume reports, not earnings
results, so matching on `잠정)실적` alone would misfile them.

[Inferred] Tesla's eight Item 2.02 8-Ks include four filed on the second day of a
quarter (2026-01-02, 04-02, 07-02, 10-02), which matches its quarterly delivery
reports. Not opened.

## `pblntf_detail_ty`

[Verified] When `pblntf_ty` is also sent, `pblntf_detail_ty` is ignored: Samsung
Electronics `pblntf_ty=I&pblntf_detail_ty=I002` returned the same 71 rows as plain
`pblntf_ty=I`. Sent without `pblntf_ty`, it filters (fixtures in `dart/detail_ty/`):
I001 29, I002 17 (공정공시), I003 5 (기업설명회), I004 20, I005 none (status `013`),
B001 10, E001 10 (자기주식취득/처분 결과보고서). I001 to I005 add up to the 71 plain I rows.

## `document.xml`

[Verified] All seven requests returned HTTP 200 and a ZIP holding one member,
`<rcept_no>.xml`. No status `014` or other error came back.

| Sample | `rcept_no` | Format | ZIP / decoded | `extract_dsd_prose` |
|---|---|---|---|---|
| 자기주식취득결정 (B) | 20260821000616 | DSD | 6 KB / 33 KB | 2 sections |
| 자기주식처분결정 (B) | 20261029000539 | DSD | 5 KB / 30 KB | 2 sections |
| 연결…(잠정)실적 (I) | 20261029800087 | xforms | 3 KB / 22 KB | not applicable |
| 현금ㆍ현물배당결정 (I) | 20261029800101 | xforms | 2 KB / 10 KB | not applicable |
| 주식소각결정 (I) | 20260331800004 | xforms | 3 KB / 10 KB | not applicable |
| 단일판매ㆍ공급계약체결 (I) | 20261103800043 | xforms | 2 KB / 7.5 KB | not applicable |
| 대표이사 변경 (I) | 20251128800894 | xforms | 2 KB / 5 KB | not applicable |

[Verified] Exchange disclosures (I) come back as xforms: an HTML form whose body is a
table of labelled fields, for example 1주당 배당금 and 배당금총액 in the dividend filing.
They declare `charset=euc-kr` but decode as UTF-8, the trap already handled by
`decode_dart_bytes`. M3 needs an xforms field reader; the DSD prose extractor does not
apply. This answers the build plan's top risk: exchange disclosures do have a fetchable
body.

## Structured buyback endpoints

[Verified] `tsstkAqDecsn.json` (자기주식 취득 결정) returned rows for Samsung
Electronics (4), SK Hynix (2) and Hyundai Motor (1), and status `013` (no data) for the
other six. Those seven rows match the seven B rows named 자기주식취득결정 by `rcept_no`.
`tsstkDpDecsn.json` (자기주식 처분 결정) exists and returned rows for four companies;
16 of the 20 처분 B rows match a structured row. The four that do not are NAVER's
`[기재정정]` versions filed 2026-03-23 (20260323001206, …1224, …1243, …1314).
[Inferred] The structured endpoint does not return corrected versions, so a corrected
filing's facts must come from its document body or be shown without facts.

[Verified] Value formats in these responses: amounts and share counts are
comma-grouped strings (`3,572,800,000,000`), ratios are plain (`1.8`), dates are
Korean-formatted (`2026년 01월 30일`), and an absent value is `-`.
`parse_dart_decimal` parses the comma-grouped amounts exactly. M3 needs a date parser
for the Korean form and explicit handling of `-`.

## SEC filing directories and exhibits

[Verified] `www.sec.gov/Archives` accepted the configured contact-style User-Agent on
all 10 requests; `data.sec.gov` on all 9.

[Verified] A filing directory's `index.json` has `directory.item[]` with `name`,
`type`, `size` and `last-modified`, where `type` is an icon label such as `text.gif`,
never an exhibit type. The exhibit type (`EX-99.1`) appears only in the document table
of `<accession>-index.html` (columns Seq, Description, Document, Type, Size). The
primary document's link there is the inline-XBRL viewer form `/ix?doc=/Archives/…`.

[Verified] Apple's earnings 8-K (0000320193-26-000024, filed 2026-11-02, items 2.02 and
9.01): EX-99.1 is 172 KB with three tables; `_html_to_text` gives about 6,200 characters
of readable text. Eight dollar figures, such as quarterly revenue and diluted EPS,
appear in prose sentences; the tables hold 45 dollar figures and 246 numeric cells
(the full statements). 8-K primary documents are
38 to 41 KB.

## The build plan's [Unknown] items

| Plan item | Result |
|---|---|
| 3.1 exact `report_nm` of 배당결정, 잠정실적, 주식소각, 단일판매ㆍ공급계약, 대표이사 변경 | Settled, table above |
| 3.1 does `document.xml` serve I001/I002, or `014` | Settled: serves xforms bodies, no `014` |
| 3.1 per-minute DART throttle | Still unknown: about 50 requests at up to 3 per second drew no `020` |
| 3.1 endpoint names of the other DS005 APIs | `tsstkAqDecsn` and `tsstkDpDecsn` confirmed; the rest stay for M3, read from each guide page |
| 3.2 shape of `index.json`; where `EX-99.1` is readable | Settled: type only in `-index.html` |
| 3.4 DART `report_nm` patterns for the categories | Confirmed for all seven event categories, with the monthly-sales caveat above |

## What this changes for later milestones

- M2: the earnings rule must separate monthly sales reports (Kia, Hyundai) from
  quarterly results, and Tesla's delivery 8-Ks from its earnings 8-Ks. Corrections
  (`[기재정정]`, `rm` containing `정`) are common: 16 of Samsung Biologics' in-scope rows
  carry a prefix.
- M3: list without `pblntf_ty` when filtering by detail code; add an xforms field reader;
  parse Korean dates and `-`.
- M4: read exhibit types from `-index.html`, not `index.json`.
- Volume: by a provisional mapping of names to the plan's categories, the nine DART
  companies have 173 in-scope rows before corrections are collapsed and monthly sales
  reports removed (Samsung SDI 6 to Samsung Electronics and Samsung Biologics 28 each).
  The SEC side has 114 rows before exclusions. M2 replaces these with counts from the
  frozen category contract.
- Open question 1 (numbers on SEC event filings): headline figures do appear in EX-99.1
  prose, so a verbatim-quote check (option B) is technically possible. It does not
  change the recommendation to start with option A.
