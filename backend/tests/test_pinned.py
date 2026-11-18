"""``--save-pinned``: regulator responses saved in the layout ``app.build.verify`` reads.

Offline only. Each round trip saves through the real client code (an ``httpx`` mock transport
serves the saved fixtures byte for byte) and then lets M8's ``check_figure`` / ``check_fact``
re-read the ingested rows from the directory that was written.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.build.model import canonical_decimal
from app.build.verify import (
    FigureRef,
    PinnedResponses,
    VerifyError,
    check_fact,
    check_figure,
    dart_fiscal_period,
)
from app.clients.dart import DartClient, DocumentPayload
from app.clients.dart_events import endpoint_for_report_key
from app.clients.dart_tables import table_for
from app.clients.sec import (
    SecClient,
    SecDocumentPayload,
    SecFilingItem,
    parse_companyfacts_payload,
)
from app.config import Settings
from app.ingest import __main__ as annual_cli
from app.ingest import events as events_cli
from app.ingest import pinned as pinned_module
from app.ingest import sec_ingest
from app.ingest.dart import DartFilingAdapter
from app.ingest.events import collect_dart_events, run_dart_events, window_bounds
from app.ingest.pinned import PinnedError, PinnedStore, scan_for_key
from app.ingest.sec_events import collect_sec_events
from app.ingest.sec_ingest import SecFilingAdapter
from tests.build_seed import annual_filings
from tests.event_fakes import NAVER_RESULTS, FakeDartClient
from tests.sec_fakes import FakeSecClient

BUILD_PINNED = Path(__file__).parent / "fixtures" / "build" / "pinned"
TODAY = datetime.date(2026, 11, 17)
DART_ANNUAL = BUILD_PINNED / "dart/fnlttSinglAcntAll/00126380_2025_11011_CFS.json"
SEC_FACTS = BUILD_PINNED / "sec/companyfacts/CIK0000320193.json"
KEY = "0123456789abcdef0123456789abcdef01234567"  # key-shaped: 40 hex characters


def _settings() -> Settings:
    return Settings(_env_file=None, dart_api_key="test-key-not-real")


def _serve(path: Path) -> httpx.AsyncClient:
    body = path.read_bytes()
    return httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))
    )


def _tree(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


# -- DART annual ---------------------------------------------------------------------------------


def _dart_filing():
    return next(f for f in annual_filings() if f.identity.source.value == "dart")


def _sec_filing():
    return next(f for f in annual_filings() if f.identity.source.value == "sec")


class _AdapterDart(DartClient):
    """The real financials call (HTTP mocked); the other two adapter calls stubbed."""

    async def fetch_company_eng_name(self, corp_code: str) -> str | None:
        return None

    async def fetch_document(self, rcept_no: str) -> DocumentPayload:
        return DocumentPayload(rcept_no, "a.xml", b"<html><body>x</body></html>", ("a.xml",))


def test_annual_dart_is_saved_at_the_path_verify_reads_and_the_figures_check(tmp_path) -> None:
    source = _dart_filing()
    store = PinnedStore(tmp_path)
    client = _AdapterDart(_settings(), _serve(DART_ANNUAL))
    adapter = DartFilingAdapter(
        client=client,
        corp_code="00126380",
        filing_item=_item(source),
        bsns_year="2025",
        reprt_code="11011",
        pinned=store,
    )
    filing = asyncio.run(adapter.fetch())
    assert _tree(tmp_path) == []  # staged only: nothing is written before the rows are stored
    assert store.commit() == []

    assert _tree(tmp_path) == ["dart/fnlttSinglAcntAll/00126380_2025_11011_CFS.json"]
    assert store.saved == ["dart/fnlttSinglAcntAll/00126380_2025_11011_CFS.json"]
    saved = tmp_path / store.saved[0]
    assert saved.read_bytes() == DART_ANNUAL.read_bytes()  # as received

    pinned = PinnedResponses([tmp_path])
    assert filing.financial_facts
    for fact in filing.financial_facts:
        fiscal_year = int(fact.period.label[:4])
        start, end = dart_fiscal_period(filing.title, 2025, fiscal_year)
        ref = FigureRef(
            "dart:00126380", f"dart:{filing.identity.source_filing_id}", filing.title, 2025,
            fact.metric.value, fiscal_year, start.isoformat(), end.isoformat(),
            canonical_decimal(fact.value),
        )  # fmt: skip
        assert check_figure(pinned, ref).pinned == store.saved[0]
        wrong = FigureRef(**{**ref.__dict__, "value": canonical_decimal(fact.value + Decimal(1))})
        with pytest.raises(VerifyError):
            check_figure(pinned, wrong)


def _item(source):
    from app.clients.dart import _filing_item_from_row

    return _filing_item_from_row(
        {
            "corp_code": "00126380", "corp_name": "삼성전자", "stock_code": "005930",
            "corp_cls": "Y", "report_nm": source.title, "rcept_no": source.identity.source_filing_id,
            "flr_nm": "삼성전자", "rcept_dt": "20260310", "rm": "연",
        }
    )  # fmt: skip


def test_annual_dart_without_the_option_writes_nothing(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    source = _dart_filing()
    adapter = DartFilingAdapter(
        client=_AdapterDart(_settings(), _serve(DART_ANNUAL)),
        corp_code="00126380",
        filing_item=_item(source),
        bsns_year="2025",
        reprt_code="11011",
    )
    asyncio.run(adapter.fetch())
    assert _tree(tmp_path) == []


# -- SEC annual ----------------------------------------------------------------------------------


def test_annual_sec_is_saved_at_the_path_verify_reads_and_the_figures_check(
    tmp_path, monkeypatch
) -> None:
    source = _sec_filing()
    accession = source.identity.source_filing_id
    filing_item = SecFilingItem(
        accession_number=accession,
        form="10-K",
        filing_date=datetime.date(2025, 10, 31),
        report_date=datetime.date(2025, 9, 27),
        primary_document="aapl-20250927.htm",
    )

    class _AdapterSec(SecClient):
        async def resolve_company_by_cik(self, cik):
            return None

        async def list_filings(self, cik, filing_types=None):
            return [filing_item]

        async def fetch_document(self, cik, accession_number, document):
            return SecDocumentPayload(cik, accession_number, document, "https://x", b"x")

    monkeypatch.setattr(sec_ingest, "extract_10k_prose", lambda raw: [])
    store = PinnedStore(tmp_path)
    client = _AdapterSec(_settings(), _serve(SEC_FACTS))
    filing = asyncio.run(
        SecFilingAdapter(client=client, cik="320193", pinned=store).fetch()
    )
    assert _tree(tmp_path) == []
    assert store.commit() == []

    assert store.saved == ["sec/companyfacts/CIK0000320193.json"]
    assert _tree(tmp_path) == store.saved
    assert (tmp_path / store.saved[0]).read_bytes() == SEC_FACTS.read_bytes()

    pinned = PinnedResponses([tmp_path])
    assert filing.financial_facts
    for fact in filing.financial_facts:
        ref = FigureRef(
            "sec:0000320193", f"sec:{accession}", filing.title, 2025, fact.metric.value, 2025,
            fact.period.start_date.isoformat(), fact.period.end_date.isoformat(),
            canonical_decimal(fact.value),
        )  # fmt: skip
        assert check_figure(pinned, ref).pinned == store.saved[0]
        wrong = FigureRef(**{**ref.__dict__, "value": canonical_decimal(fact.value + Decimal(1))})
        with pytest.raises(VerifyError):
            check_figure(pinned, wrong)


# -- DART events ---------------------------------------------------------------------------------


def _dart_collect(client, store, stock_code="035420"):
    return asyncio.run(
        collect_dart_events(
            client, "00266961", window_bounds(TODAY), pinned=store, stock_code=stock_code
        )
    )


def test_dart_events_save_each_structured_endpoint_once_and_the_facts_check(tmp_path) -> None:
    store = PinnedStore(tmp_path)
    client = FakeDartClient("035420")
    records, summary = _dart_collect(client, store)
    assert summary.ok, summary.problems
    assert _tree(tmp_path) == []  # nothing before the commit
    assert store.commit() == []

    called = sorted(c[1] for c in client.calls if c[0] == "structured")
    assert called == ["piicDecsn.json", "tsstkDpDecsn.json"]  # one call per endpoint per company
    # The endpoint without data (status 013) is a response the parser consumed, so it is saved.
    structured = [p for p in store.saved if p.startswith("dart/structured/")]
    assert structured == [
        "dart/structured/piicDecsn_035420.json",
        "dart/structured/tsstkDpDecsn_035420.json",
    ]
    # The bodies whose table gave facts (D77) are saved as received.
    assert sorted(p for p in store.saved if p.startswith("dart/document/")) == [
        f"dart/document/{r}.xml" for r in NAVER_RESULTS
    ]
    assert _tree(tmp_path) == sorted(store.saved)
    fixture = Path(__file__).parent / "fixtures/events/dart/structured/piicDecsn_035420.json"
    assert (tmp_path / structured[0]).read_bytes() == fixture.read_bytes()
    assert json.loads((tmp_path / structured[1]).read_bytes())["status"] == "013"
    body = Path(__file__).parent / "fixtures/events/classifier/dart/document/20260807800028.xml"
    assert (tmp_path / "dart/document/20260807800028.xml").read_bytes() == body.read_bytes()

    pinned = PinnedResponses([tmp_path])
    checked = tabled = 0
    for record in records:
        endpoint = endpoint_for_report_key(record.base_key)
        table = table_for(record.classification.category, record.base_key)
        if table is not None:
            for fact in record.facts or []:
                kwargs = dict(
                    filing_id=f"dart:{record.key}", company_id="dart:00266961",
                    stock_code="035420", origin=f"dartdoc:{table}.{fact.key}", fact_key=fact.key,
                )  # fmt: skip
                expected = (canonical_decimal(fact.value_decimal) if fact.value_decimal
                            is not None else fact.value_date.isoformat())  # fmt: skip
                path = check_fact(pinned, **kwargs, value_text=expected)
                assert path == f"dart/document/{record.key}.xml"
                with pytest.raises(VerifyError):
                    check_fact(pinned, **kwargs, value_text=expected + "0")
                tabled += 1
            continue
        for fact in record.facts or []:
            if fact.error:
                continue
            expected = (
                canonical_decimal(fact.value_decimal)
                if fact.value_decimal is not None
                else fact.value_date.isoformat()
                if fact.value_date is not None
                else str(fact.value_text)
            )
            kwargs = dict(
                filing_id=f"dart:{record.key}", company_id="dart:00266961", stock_code="035420",
                origin=f"opendart:{endpoint}.{fact.source_field}", fact_key=fact.key,
            )  # fmt: skip
            assert check_fact(pinned, **kwargs, value_text=expected) == structured[0]
            with pytest.raises(VerifyError):
                check_fact(pinned, **kwargs, value_text=expected + "0")
            checked += 1
    assert checked == 5  # every structured fact the ingest extracted was re-read
    assert tabled == sum(len(r.facts or []) for r in records if r.key in NAVER_RESULTS) > 0
    # A directory that was not written to has nothing for verify to read.
    with pytest.raises(VerifyError, match="no pinned response"):
        check_fact(
            PinnedResponses([tmp_path / "elsewhere"]),
            filing_id=f"dart:{records[0].key}", company_id="dart:00266961", stock_code="035420",
            origin="opendart:piicDecsn.nstk_ostk_cnt", fact_key="x", value_text="1",
        )  # fmt: skip


def test_dart_events_without_the_option_write_nothing(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _dart_collect(FakeDartClient("035420"), None)
    assert _tree(tmp_path) == []


class _KeyedStructured(FakeDartClient):
    """A structured body that (wrongly) holds a key-shaped value."""

    async def _get(self, endpoint, params):
        response = await super()._get(endpoint, params)
        raw = response.content.replace(b'"status"', b'"echo": "' + KEY.encode() + b'", "status"', 1)
        response.content = raw
        assert json.loads(raw)["echo"] == KEY
        return response


def test_a_key_like_value_in_a_response_is_refused_and_reported_not_saved(tmp_path) -> None:
    store = PinnedStore(tmp_path)
    records, summary = _dart_collect(_KeyedStructured("035420"), store)
    assert store.commit() == []
    assert not any(p.startswith("dart/structured/") for p in store.saved)
    assert not any(p.startswith("dart/structured/") for p in _tree(tmp_path))
    assert any(p.startswith("pinned dart/structured/piicDecsn_035420.json") for p in summary.problems)
    assert not summary.ok
    assert any(r.facts for r in records)  # the ingest itself carried on


def test_only_the_documents_whose_table_gave_facts_are_saved(tmp_path) -> None:
    store = PinnedStore(tmp_path)
    client = FakeDartClient("035420")
    _dart_collect(client, store)
    store.commit()
    read = {c[1] for c in client.calls if c[0] == "document"}
    assert len(read) > len(NAVER_RESULTS)  # the run read many more bodies than it saved
    assert sorted(p for p in _tree(tmp_path) if not p.startswith("dart/structured/")) == [
        f"dart/document/{r}.xml" for r in NAVER_RESULTS
    ]


# -- SEC events ----------------------------------------------------------------------------------


def _sec_collect(client, store):
    return asyncio.run(
        collect_sec_events(
            client, "0000320193", "AAPL", "Apple Inc.", window_bounds(TODAY), None, store
        )
    )


def test_sec_events_save_submissions_and_the_facts_check(tmp_path) -> None:
    store = PinnedStore(tmp_path)
    records, summary = _sec_collect(FakeSecClient("AAPL"), store)
    assert _tree(tmp_path) == []
    assert store.commit() == []
    assert store.saved == ["sec/submissions/CIK0000320193.json"]
    assert _tree(tmp_path) == store.saved

    pinned = PinnedResponses([tmp_path])
    checked = 0
    for record in records:
        for fact in record.facts or []:
            expected = fact.value_date.isoformat() if fact.value_date else str(fact.value_text)
            kwargs = dict(
                filing_id=record.key, company_id="sec:0000320193", stock_code="AAPL",
                origin=fact.source_field, fact_key=fact.key,
            )  # fmt: skip
            assert check_fact(pinned, **kwargs, value_text=expected) == store.saved[0]
            with pytest.raises(VerifyError):
                check_fact(pinned, **kwargs, value_text=expected + "x")
            checked += 1
    assert checked > 10
    assert summary.ok or not any("pinned" in p for p in summary.problems)


def _submissions_transport(main: dict, pages: dict[str, dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        if name == "CIK0000320193.json":
            return httpx.Response(200, content=json.dumps(main, indent=1).encode())
        return httpx.Response(200, json=pages[name])

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _recent(rows: list[tuple[str, str]]) -> dict:
    return {
        "accessionNumber": [a for a, _ in rows],
        "filingDate": [d for _, d in rows],
        "reportDate": [d for _, d in rows],
        "form": ["8-K"] * len(rows),
        "items": ["8.01"] * len(rows),
        "primaryDocument": ["a.htm"] * len(rows),
    }


def test_the_real_client_saves_the_main_submissions_body_exactly_as_received(tmp_path) -> None:
    main = {"filings": {"recent": _recent([("0000320193-26-000001", "2026-02-01")]), "files": []}}
    expected = json.dumps(main, indent=1).encode()  # unusual spacing: not re-encoded on save
    store = PinnedStore(tmp_path)
    client = SecClient(_settings(), _submissions_transport(main, {}))
    items, problems = asyncio.run(
        client.list_filings_window(
            "320193", ["8-K"], datetime.date(2026, 1, 1),
            on_body=store.sink("sec/submissions/CIK0000320193.json"),
        )
    )  # fmt: skip
    assert len(items) == 1 and problems == []
    assert store.commit() == []
    assert (tmp_path / "sec/submissions/CIK0000320193.json").read_bytes() == expected


def test_a_response_that_needs_older_pages_is_not_saved_and_is_reported(tmp_path) -> None:
    older = "CIK0000320193-submissions-001.json"
    main = {
        "filings": {
            "recent": _recent([("0000320193-26-000002", "2026-06-01")]),
            "files": [{"name": older, "filingFrom": "2025-01-01", "filingTo": "2026-03-01"}],
        }
    }
    pages = {older: _recent([("0000320193-25-000009", "2025-12-01")])}
    store = PinnedStore(tmp_path)
    client = SecClient(_settings(), _submissions_transport(main, pages))
    items, problems = asyncio.run(
        client.list_filings_window(
            "320193", ["8-K"], datetime.date(2025, 11, 18),
            on_body=store.sink("sec/submissions/CIK0000320193.json"),
        )
    )  # fmt: skip
    assert {i.accession_number for i in items} == {"0000320193-26-000002", "0000320193-25-000009"}
    assert store.commit() == []
    assert _tree(tmp_path) == []
    assert any("older submissions pages" in p for p in problems)


# -- key scan and atomic writes ------------------------------------------------------------------


def test_the_key_scan_refuses_a_body_with_a_key_like_value_and_writes_nothing(tmp_path) -> None:
    store = PinnedStore(tmp_path)
    body = json.dumps({"status": "000", "x": KEY}).encode()
    with pytest.raises(PinnedError, match="key-like"):
        store.save("dart/structured/piicDecsn_035420.json", body)
    assert _tree(tmp_path) == [] and store.saved == []
    with pytest.raises(PinnedError, match="crtfc_key"):
        store.save("dart/structured/piicDecsn_035420.json", b'{"url": "?crtfc_key=abc"}')
    assert _tree(tmp_path) == []


def test_the_key_scan_refuses_the_configured_key_in_any_file_and_passes_clean_bodies(
    tmp_path,
) -> None:
    store = PinnedStore(tmp_path, ["a-short-configured-key"])
    with pytest.raises(PinnedError, match="configured API key"):
        store.save("sec/submissions/CIK0000320193.json", b'{"note": "a-short-configured-key"}')
    assert _tree(tmp_path) == []
    # A 40-hex value in an SEC file is not a DART key, and 14-digit receipt numbers are fine.
    store.save("sec/submissions/CIK0000320193.json", json.dumps({"hash": KEY}).encode())
    store.save("dart/structured/a_000660.json", b'{"rcept_no": "20261103000311"}')
    assert len(_tree(tmp_path)) == 2


def test_scan_for_key_ignores_longer_hex_runs_that_are_not_a_key() -> None:
    scan_for_key("dart/x.json", b'{"a": "' + b"ab" * 41 + b'"}')  # 82 hex characters
    with pytest.raises(PinnedError):
        scan_for_key("dart/x.json", b'{"a": "' + KEY.encode() + b'"}')


@pytest.mark.parametrize(
    "relative",
    ["../x.json", "dart/../../x.json", "/etc/x.json", "dart//x.json", "dart/a b.json", ""],
)
def test_a_path_outside_the_layout_is_refused(tmp_path, relative) -> None:
    with pytest.raises(PinnedError, match="unsafe"):
        PinnedStore(tmp_path / "root").save(relative, b"{}")
    assert not (tmp_path / "root").exists()


def test_a_failed_rename_leaves_no_partial_file_and_keeps_the_old_one(tmp_path, monkeypatch) -> None:
    store = PinnedStore(tmp_path)
    relative = "dart/structured/piicDecsn_035420.json"
    store.save(relative, b'{"status": "013"}')
    target = tmp_path / relative

    def failing_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(PinnedError, match="disk full"):
        store.save(relative, b'{"status": "000", "list": []}')
    assert target.read_bytes() == b'{"status": "013"}'  # the earlier file is intact
    assert _tree(tmp_path) == [relative]  # no temporary file left behind


def test_a_failed_write_leaves_no_file_at_the_target(tmp_path, monkeypatch) -> None:
    def failing_fsync(fd):
        raise OSError("io error")

    monkeypatch.setattr(os, "fsync", failing_fsync)
    store = PinnedStore(tmp_path)
    with pytest.raises(PinnedError, match="io error"):
        store.save("sec/companyfacts/CIK0000320193.json", b"{}")
    assert _tree(tmp_path) == [] and store.saved == []


def test_a_new_file_appears_complete_or_not_at_all(tmp_path, monkeypatch) -> None:
    """The bytes are in a temporary file before the name exists, so a reader sees all or none."""
    seen: list[tuple[bool, bytes]] = []
    real_replace = os.replace
    target = tmp_path / "sec/companyfacts/CIK0000320193.json"

    def watching_replace(src, dst):
        seen.append((target.exists(), Path(src).read_bytes()))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", watching_replace)
    PinnedStore(tmp_path).save("sec/companyfacts/CIK0000320193.json", b'{"complete": true}')
    assert seen == [(False, b'{"complete": true}')]
    assert target.read_bytes() == b'{"complete": true}'


# -- command line --------------------------------------------------------------------------------


def test_every_ingest_command_takes_save_pinned(tmp_path, monkeypatch) -> None:
    given: dict[str, PinnedStore | None] = {}

    async def fake_dart(ticker, pinned=None):
        given["annual-dart"] = pinned

    async def fake_sec(ticker, pinned=None):
        given["annual-sec"] = pinned

    async def fake_events_dart(ticker, pinned=None):
        given["events-dart"] = pinned
        return events_cli.EventIngestSummary("c", (TODAY, TODAY), documents_fetched=0)

    async def fake_events_sec(ticker, pinned=None):
        given["events-sec"] = pinned
        from app.ingest.sec_events import SecEventSummary

        return SecEventSummary("c", (TODAY, TODAY))

    monkeypatch.setattr(annual_cli, "_run_dart", fake_dart)
    monkeypatch.setattr(annual_cli, "_run_sec", fake_sec)
    monkeypatch.setattr(events_cli, "_run", fake_events_dart)
    monkeypatch.setattr("app.ingest.sec_events.run_sec_cli", fake_events_sec)
    out = str(tmp_path / "pinned")

    for source in ("dart", "sec"):
        monkeypatch.setattr(sys, "argv", ["x", "--source", source, "--ticker", "T", "--save-pinned", out])
        annual_cli.main()
        events_cli.main(["--source", source, "--ticker", "T", "--save-pinned", out])
    assert set(given) == {"annual-dart", "annual-sec", "events-dart", "events-sec"}
    assert all(isinstance(s, PinnedStore) and s.root == Path(out) for s in given.values())

    given.clear()
    monkeypatch.setattr(sys, "argv", ["x", "--source", "dart", "--ticker", "T"])
    annual_cli.main()
    events_cli.main(["--source", "dart", "--ticker", "T"])
    assert given == {"annual-dart": None, "events-dart": None}


def test_the_configured_key_is_scanned_for_without_being_printed(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DART_API_KEY", "configured-secret-value")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        store = pinned_module.open_pinned_store(str(tmp_path))
        with pytest.raises(PinnedError) as refused:
            store.save("sec/submissions/CIK0000320193.json", b"configured-secret-value")
        assert "configured-secret-value" not in str(refused.value)
    finally:
        get_settings.cache_clear()
    assert pinned_module.open_pinned_store(None) is None


# -- nothing is written before the rows are stored, and good files are never replaced ------------

STRUCTURED = "dart/structured/piicDecsn_035420.json"
NO_DATA = b'{"status": "013", "message": "no data"}'


class _Body(FakeDartClient):
    """A DART fake whose piicDecsn endpoint answers with the given bytes."""

    def __init__(self, stock_code: str, body: bytes) -> None:
        super().__init__(stock_code)
        self.body = body

    async def _get(self, endpoint, params):
        from tests.event_fakes import _Response

        if endpoint != "piicDecsn.json":
            return await super()._get(endpoint, params)
        return _Response(json.loads(self.body), self.body)


def _run_events(monkeypatch, client, store, persist):
    """``run_dart_events`` with persistence replaced; returns the summary."""
    monkeypatch.setattr(events_cli, "persist_events", persist)
    return asyncio.run(run_dart_events(client, "035420", lambda: None, today=TODAY, pinned=store))


async def _persisted(factory, records):
    return []


async def _persist_fails(factory, records):
    raise RuntimeError("the transaction rolled back")


def test_the_stock_code_in_the_path_is_the_one_verify_reads_not_the_corp_code(
    tmp_path, monkeypatch
) -> None:
    seen: list = []

    async def capture(factory, records):
        seen.extend(records)
        return []

    store = PinnedStore(tmp_path)
    summary = _run_events(monkeypatch, FakeDartClient("035420"), store, capture)
    assert summary.ok, summary.problems
    # verify reads companies.ticker, which the export takes from the stored stock_code.
    assert {r.item.stock_code for r in seen} == {"035420"}
    assert {r.item.corp_code for r in seen} == {"00266961"}  # a different value
    assert set(store.saved) == {
        "dart/structured/piicDecsn_035420.json",
        "dart/structured/tsstkDpDecsn_035420.json",
        *(f"dart/document/{r}.xml" for r in NAVER_RESULTS),
    }
    assert set(_tree(tmp_path)) == set(store.saved)


def test_a_persist_failure_leaves_the_existing_pinned_file_byte_identical(
    tmp_path, monkeypatch
) -> None:
    _run_events(monkeypatch, FakeDartClient("035420"), PinnedStore(tmp_path), _persisted)
    before = (tmp_path / STRUCTURED).read_bytes()

    newer = json.dumps({"status": "000", "list": []}, indent=3).encode()
    with pytest.raises(RuntimeError, match="rolled back"):
        _run_events(monkeypatch, _Body("035420", newer), PinnedStore(tmp_path), _persist_fails)
    assert (tmp_path / STRUCTURED).read_bytes() == before
    assert not [p for p in tmp_path.rglob(".*") if p.is_file()]  # no temporary file either

    # The same run, persisted, does replace it.
    _run_events(monkeypatch, _Body("035420", newer), PinnedStore(tmp_path), _persisted)
    assert (tmp_path / STRUCTURED).read_bytes() == newer


def test_an_error_status_body_is_never_saved_and_an_existing_file_is_unchanged(
    tmp_path, monkeypatch
) -> None:
    _run_events(monkeypatch, FakeDartClient("035420"), PinnedStore(tmp_path), _persisted)
    before = (tmp_path / STRUCTURED).read_bytes()

    store = PinnedStore(tmp_path)
    refused = b'{"status": "020", "message": "request limit exceeded"}'
    summary = _run_events(monkeypatch, _Body("035420", refused), store, _persisted)
    assert any("piicDecsn" in p and "020" in p for p in summary.problems)
    assert STRUCTURED not in store.saved
    assert (tmp_path / STRUCTURED).read_bytes() == before


def test_a_no_data_answer_is_saved_only_when_no_file_exists(tmp_path, monkeypatch) -> None:
    first = PinnedStore(tmp_path)
    _run_events(monkeypatch, _Body("035420", NO_DATA), first, _persisted)
    assert (tmp_path / STRUCTURED).read_bytes() == NO_DATA  # nothing earlier to protect

    good = json.dumps({"status": "000", "list": []}).encode()
    (tmp_path / STRUCTURED).write_bytes(good)
    second = PinnedStore(tmp_path)
    summary = _run_events(monkeypatch, _Body("035420", NO_DATA), second, _persisted)
    assert (tmp_path / STRUCTURED).read_bytes() == good  # kept
    assert any(
        STRUCTURED in p and "existing file was kept" in p for p in summary.problems
    )  # and reported
    assert STRUCTURED not in second.saved


def _annual_dart(tmp_path, body: bytes, store: PinnedStore):
    source = _dart_filing()
    client = _AdapterDart(
        _settings(),
        httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))
        ),
    )
    adapter = DartFilingAdapter(
        client=client, corp_code="00126380", filing_item=_item(source), bsns_year="2025",
        reprt_code="11011", pinned=store,
    )  # fmt: skip
    asyncio.run(adapter.fetch())
    return store.commit()


def test_an_empty_or_error_annual_dart_body_never_replaces_a_good_file(tmp_path) -> None:
    relative = "dart/fnlttSinglAcntAll/00126380_2025_11011_CFS.json"
    store = PinnedStore(tmp_path)
    assert _annual_dart(tmp_path, DART_ANNUAL.read_bytes(), store) == []
    good = (tmp_path / relative).read_bytes()

    again = PinnedStore(tmp_path)
    assert _annual_dart(tmp_path, NO_DATA, again) == []  # status 013: parsed to no rows
    assert (tmp_path / relative).read_bytes() == good and again.saved == []
    empty_list = PinnedStore(tmp_path)
    assert _annual_dart(tmp_path, b'{"status": "000", "list": []}', empty_list) == []
    assert (tmp_path / relative).read_bytes() == good and empty_list.saved == []

    with pytest.raises(Exception, match="020"):
        _annual_dart(tmp_path, b'{"status": "020", "message": "x"}', PinnedStore(tmp_path))
    assert (tmp_path / relative).read_bytes() == good


def test_an_empty_companyfacts_body_never_replaces_a_good_file(tmp_path) -> None:
    def fetch(body: bytes, store: PinnedStore):
        client = SecClient(
            _settings(),
            httpx.AsyncClient(
                transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))
            ),
        )
        asyncio.run(
            client.fetch_company_facts("320193", on_body=store.sink("sec/companyfacts/CIK0000320193.json"))
        )
        return store.commit()

    relative = tmp_path / "sec/companyfacts/CIK0000320193.json"
    assert fetch(SEC_FACTS.read_bytes(), PinnedStore(tmp_path)) == []
    good = relative.read_bytes()
    empty = PinnedStore(tmp_path)
    assert fetch(b'{"facts": {}}', empty) == []  # parsed to no rows
    assert relative.read_bytes() == good and empty.saved == []


# -- SEC numbers: ingest and verify read a companyfacts body the same way ------------------------

_ENTRY = (
    '{"start": "2024-10-01", "end": "2025-09-27", "val": %s, "accn": "%s", "fy": 2025, '
    '"fp": "FY", "form": "10-K", "filed": "2025-10-31"}'
)


def _facts_body(values: dict[str, str]) -> bytes:
    entries = ",".join(_ENTRY % (value, accn) for accn, value in values.items())
    return (
        '{"facts": {"us-gaap": {"Revenues": {"units": {"USD": [' + entries + "]}}}}}"
    ).encode()


def test_ingest_and_verify_agree_on_decimal_amounts_in_a_companyfacts_body(tmp_path) -> None:
    values = {
        "0000000001-25-000001": "383285000000",  # an integer literal
        "0000000001-25-000002": "383285000000.0",  # whole, written as a decimal
        "0000000001-25-000003": "3.83285E11",  # whole, exponent form
        "0000000001-25-000004": "383285000000.5",  # fractional: refused
        "0000000001-25-000005": "12345678901234567.0",  # beyond binary float precision
    }
    body = _facts_body(values)
    client = SecClient(
        _settings(),
        httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))
        ),
    )
    store = PinnedStore(tmp_path)
    ingested = asyncio.run(
        client.fetch_company_facts("1", on_body=store.sink("sec/companyfacts/CIK0000000001.json"))
    )
    store.commit()
    verified = parse_companyfacts_payload(
        PinnedResponses([tmp_path]).load("sec/companyfacts/CIK0000000001.json")
    )

    def amounts(items):
        return {i.accession_number: i.value for i in items}

    assert amounts(ingested) == amounts(verified)  # the two never disagree
    assert amounts(ingested) == {
        "0000000001-25-000001": 383285000000,
        "0000000001-25-000002": 383285000000,
        "0000000001-25-000003": 383285000000,
        "0000000001-25-000005": 12345678901234567,  # exact: never rounded through a float
    }  # whole decimals are exact in both; the fractional amount is refused in both
