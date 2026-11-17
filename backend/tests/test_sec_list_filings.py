"""Tests for SEC ``submissions/CIK##########.json`` parsing and ``format_cik``.

All tests here are offline: ``parse_submissions_payload`` is driven with an
inline JSON fixture modeled on the public submissions API shape (column-oriented
``filings.recent`` arrays), and ``SecClient.list_filings`` is exercised via an
``httpx.MockTransport`` so the URL/User-Agent are checked without any network
call. The response shape (field names, array layout) is [Inferred] -- not
verified against a live fetch in this offline step.
"""

import asyncio
import datetime
import json
import logging
from pathlib import Path

import httpx
import pytest

from app.clients.sec import (
    SecApiError,
    SecClient,
    SecClientError,
    SecIndexDocument,
    format_cik,
    parse_filing_index_html,
    parse_submissions_payload,
)
from app.config import Settings

logger = logging.getLogger(__name__)

# Trimmed, real-shaped submissions payload (Apple Inc., CIK 0000320193): two
# 10-K rows and one 10-Q row so form filtering has something to exclude.
_SUBMISSIONS_PAYLOAD = {
    "cik": "320193",
    "entityType": "operating",
    "sic": "3571",
    "name": "Apple Inc.",
    "tickers": ["AAPL"],
    "exchanges": ["Nasdaq"],
    "filings": {
        "recent": {
            "accessionNumber": [
                "0000320193-23-000106",
                "0000320193-23-000077",
                "0000320193-22-000108",
            ],
            "filingDate": ["2023-11-03", "2023-08-04", "2022-10-28"],
            "reportDate": ["2023-09-30", "2023-07-01", "2022-09-24"],
            "form": ["10-K", "10-Q", "10-K"],
            "primaryDocument": [
                "aapl-20230930.htm",
                "aapl-20230701.htm",
                "aapl-20220924.htm",
            ],
        },
        "files": [],
    },
}

_FAKE_SETTINGS = Settings(sec_user_agent="filing-digest-test test@example.com")


# -- format_cik ---------------------------------------------------------------


def test_format_cik_zero_pads_int_and_str() -> None:
    assert format_cik(320193) == "0000320193"
    assert format_cik("320193") == "0000320193"
    assert format_cik("0000320193") == "0000320193"


def test_format_cik_rejects_non_numeric() -> None:
    with pytest.raises(SecClientError):
        format_cik("AAPL")


def test_format_cik_rejects_too_long() -> None:
    with pytest.raises(SecClientError):
        format_cik("12345678901")


# -- parse_submissions_payload --------------------------------------------


def test_parse_submissions_payload_filters_10k() -> None:
    items = parse_submissions_payload(_SUBMISSIONS_PAYLOAD, filing_types=["10-K"])
    assert len(items) == 2
    assert all(it.form == "10-K" for it in items)
    first = items[0]
    assert first.accession_number == "0000320193-23-000106"
    assert first.filing_date == datetime.date(2023, 11, 3)
    assert first.report_date == datetime.date(2023, 9, 30)
    assert first.primary_document == "aapl-20230930.htm"


def test_parse_submissions_payload_case_insensitive_filter() -> None:
    items = parse_submissions_payload(_SUBMISSIONS_PAYLOAD, filing_types=["10-k"])
    assert len(items) == 2


def test_parse_submissions_payload_no_filter_returns_all() -> None:
    items = parse_submissions_payload(_SUBMISSIONS_PAYLOAD)
    assert len(items) == 3


def test_parse_submissions_payload_missing_recent_raises() -> None:
    with pytest.raises(SecApiError):
        parse_submissions_payload({"filings": {}})


def test_parse_submissions_payload_non_dict_raises() -> None:
    with pytest.raises(SecApiError):
        parse_submissions_payload(["not", "a", "dict"])


def test_parse_submissions_payload_missing_arrays_returns_empty() -> None:
    # status-000-equivalent "nothing here" -- defensive empty result, not a raise.
    assert parse_submissions_payload({"filings": {"recent": {}}}) == []


# -- SecClient.list_filings offline (httpx.MockTransport) ---------------------


def test_list_filings_offline_sends_user_agent_and_builds_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/submissions/CIK0000320193.json"
        assert request.headers["User-Agent"] == _FAKE_SETTINGS.sec_user_agent
        return httpx.Response(200, json=_SUBMISSIONS_PAYLOAD)

    async def _run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        sec = SecClient(settings=_FAKE_SETTINGS, client=client)
        try:
            return await sec.list_filings(320193, filing_types=["10-K"])
        finally:
            await client.aclose()

    items = asyncio.run(_run())
    assert len(items) == 2
    assert all(it.form == "10-K" for it in items)


# -- 8-K fields: items, primaryDocDescription ---------------------------------

_EVENTS = Path(__file__).parent / "fixtures" / "events" / "sec"


def test_parse_submissions_payload_reads_items_and_primary_doc_description() -> None:
    payload = {
        "filings": {
            "recent": {
                "accessionNumber": ["a", "b", "c"],
                "form": ["8-K", "8-K/A", "10-K"],
                "items": ["2.02,9.01", "5.02", ""],
                "primaryDocDescription": ["8-K", "8-K/A", "10-K"],
                "primaryDocument": ["a.htm", "b.htm", "c.htm"],
            }
        }
    }
    rows = parse_submissions_payload(payload, ["8-K", "8-K/A"])
    assert [(r.accession_number, r.items, r.primary_doc_description) for r in rows] == [
        ("a", "2.02,9.01", "8-K"),
        ("b", "5.02", "8-K/A"),
    ]
    # A payload without the columns still parses, with empty values.
    bare = parse_submissions_payload(_SUBMISSIONS_PAYLOAD)
    assert {(r.items, r.primary_doc_description) for r in bare} == {("", "")}


def test_saved_m1_submissions_carry_items_for_every_8k_row() -> None:
    rows = json.loads((_EVENTS / "submissions_8k" / "AAPL.json").read_text())["rows"]
    recent = {k: [r[k] for r in rows] for k in rows[0]}
    parsed = parse_submissions_payload({"filings": {"recent": recent}}, ["8-K", "8-K/A"])
    assert len(parsed) == len(rows) == 10
    by_accession = {p.accession_number: p for p in parsed}
    assert by_accession["0000320193-26-000024"].items == "2.02,9.01"
    assert by_accession["0001140361-26-035325"].form == "8-K/A"
    assert by_accession["0001140361-26-035325"].primary_doc_description == "8-K/A"


# -- filing index (-index.html) ------------------------------------------------


def test_parse_filing_index_html_uses_the_type_column_not_index_json() -> None:
    html = (_EVENTS / "index" / "0000320193-26-000024-index.html").read_text()
    assert parse_filing_index_html(html) == [
        SecIndexDocument("aapl-20261102.htm", "8-K", "8-K"),  # unwrapped from /ix?doc=
        SecIndexDocument("a8-kex991q4202609262026.htm", "EX-99.1", "EX-99.1"),
        SecIndexDocument("aapl-20261102_g1.jpg", "GRAPHIC", ""),
    ]  # no "Complete submission text file" row (no type) and nothing from the Data Files table


def test_parse_filing_index_html_without_a_document_table_is_empty() -> None:
    assert parse_filing_index_html("<table><tr><td>x</td></tr></table>") == []


def test_fetch_filing_index_offline_builds_the_index_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == (
            "/Archives/edgar/data/320193/000032019326000024/0000320193-26-000024-index.html"
        )
        assert request.headers["User-Agent"] == _FAKE_SETTINGS.sec_user_agent
        return httpx.Response(
            200,
            text='<table class="tableFile"><tr><th>Description</th><th>Document</th>'
            '<th>Type</th></tr><tr><td>x</td><td><a href="/Archives/e/ex.htm">ex.htm</a></td>'
            "<td>EX-99.1</td></tr></table>",
        )

    async def _run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        sec = SecClient(settings=_FAKE_SETTINGS, client=client)
        try:
            return await sec.fetch_filing_index(320193, "0000320193-26-000024")
        finally:
            await client.aclose()

    docs = asyncio.run(_run())
    assert [(d.document, d.doc_type) for d in docs] == [("ex.htm", "EX-99.1")]


# -- a short filings.recent window: follow filings.files --------------------------------------

_PAGE = "CIK0000320193-submissions-001.json"
SINCE = datetime.date(2025, 11, 18)


def _recent(dates: list[str], forms: list[str] | None = None, prefix: str = "r") -> dict:
    return {
        "accessionNumber": [f"{prefix}-{i}" for i in range(len(dates))],
        "filingDate": dates,
        "form": forms or ["8-K"] * len(dates),
        "items": ["5.02"] * len(dates),
        "primaryDocument": ["x.htm"] * len(dates),
    }


def _main(recent: dict, files: list[dict]) -> dict:
    return {"filings": {"recent": recent, "files": files}}


def _window(main: dict, pages: dict[str, object], since: datetime.date):
    """Run ``list_filings_window`` on ``main``; ``pages`` maps a file name to a body or a status."""
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        requested.append(name)
        if name == "CIK0000320193.json":
            return httpx.Response(200, json=main)
        page = pages.get(name)
        if isinstance(page, int):
            return httpx.Response(page)
        return httpx.Response(200, json=page) if page is not None else httpx.Response(404)

    async def _run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        sec = SecClient(settings=_FAKE_SETTINGS, client=client)
        try:
            return await sec.list_filings_window(320193, ["8-K", "8-K/A"], since)
        finally:
            await client.aclose()

    items, problems = asyncio.run(_run())
    return items, problems, requested


def test_a_recent_block_that_reaches_the_window_start_follows_no_files() -> None:
    main = _main(_recent(["2026-05-01", "2025-11-18"]), [{"name": _PAGE, "filingTo": "2025-11-01"}])
    items, problems, requested = _window(main, {}, SINCE)
    assert [i.accession_number for i in items] == ["r-0", "r-1"]
    assert problems == [] and requested == ["CIK0000320193.json"]


def test_a_short_recent_block_follows_older_pages_and_merges_their_8k_rows() -> None:
    main = _main(
        _recent(["2026-05-01", "2026-03-01"]),
        [{"name": _PAGE, "filingFrom": "2020-01-01", "filingTo": "2026-02-28"}],
    )
    page = _recent(["2026-02-01", "2025-12-01", "2025-12-02"], ["8-K", "10-Q", "8-K/A"], "p")
    items, problems, requested = _window(main, {_PAGE: page}, SINCE)
    assert [i.accession_number for i in items] == ["r-0", "r-1", "p-0", "p-2"]  # 10-Q filtered
    assert problems == [] and requested == ["CIK0000320193.json", _PAGE]


def test_a_page_entirely_before_the_window_is_not_fetched() -> None:
    main = _main(_recent(["2026-05-01"]), [{"name": _PAGE, "filingTo": "2025-11-17"}])
    _, problems, requested = _window(main, {}, SINCE)
    assert problems == [] and requested == ["CIK0000320193.json"]


def test_an_unreadable_older_page_is_a_problem_not_a_silent_gap() -> None:
    main = _main(_recent(["2026-05-01"]), [{"name": _PAGE, "filingTo": "2026-01-01"}])
    items, problems, _ = _window(main, {_PAGE: 503}, SINCE)
    assert [i.accession_number for i in items] == ["r-0"]
    assert len(problems) == 1 and problems[0].startswith(f"0000320193 {_PAGE}: ")


def test_an_unexpected_page_name_is_a_problem_and_is_not_requested() -> None:
    main = _main(_recent(["2026-05-01"]), [{"name": "../../evil.json", "filingTo": "2026-01-01"}])
    _, problems, requested = _window(main, {}, SINCE)
    assert len(problems) == 1 and "unexpected name" in problems[0]
    assert requested == ["CIK0000320193.json"]


def test_a_company_whose_history_simply_starts_late_has_no_problem() -> None:
    items, problems, _ = _window(_main(_recent(["2026-05-01"]), []), {}, SINCE)
    assert problems == [] and len(items) == 1
