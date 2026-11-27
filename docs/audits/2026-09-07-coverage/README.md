# Coverage audit snapshot · 2026-09-07

`pilot-snapshot.json` is copied byte for byte from Filing Agent's
[2026-09-07 coverage audit](https://github.com/mhju0/filing-agent/tree/a2b01cdc7e42ba019d9b6e4c1727cc13091d2fe7/docs/audits/2026-09-07-coverage)
at commit `a2b01cd`. SHA-256:
`9afc83471e3876cd5885fb8eb6b1d4b85883757bfbfcd7b92ad8292f9262c96a`.

It holds fifteen figures, each checked by an agent against its DART or EDGAR source:
revenue, operating income and net income for Samsung Electronics FY2022 and FY2023,
NAVER FY2023, and Microsoft FY2023 and FY2024. Every value is public filing data. The
file's `limitations` list says what the check does not cover.

[PRODUCT.md](../../../PRODUCT.md) cites it as evidence, and the verified-figure cases in
`backend/scripts/generate_comparison_cases.py` use its values.

The `sources/` and `excerpts/` paths inside the file are relative to the audit folder in
Filing Agent. The captured filings, excerpts and
[`fact-checks.json`](https://github.com/mhju0/filing-agent/blob/a2b01cdc7e42ba019d9b6e4c1727cc13091d2fe7/docs/audits/2026-09-07-coverage/fact-checks.json)
stay there and were not copied.
