"""Event ingest logic without a database: window, correction chains, and the collect step."""

from __future__ import annotations

import asyncio
import copy
import datetime
import zipfile
from decimal import Decimal

import pytest

from app.clients import sec_8k
from app.clients.dart import DartApiError
from app.clients.dart_events import CorrectionTarget, read_event_document
from app.filings.categories import classify_dart, is_event_category
from app.ingest import events
from app.ingest.events import (
    ChainInput,
    collect_dart_events,
    format_summary,
    resolve_chains,
    store_body_text,
    window_bounds,
)
from tests.event_fakes import DART, FakeDartClient

D = datetime.date


def entry(
    rcept_no: str,
    filed: datetime.date | None,
    *,
    corp: str = "C1",
    key: str = "유상증자결정",
    rm: str = "",
    correction: bool = False,
    in_scope: bool = True,
    target: CorrectionTarget | None = None,
    target_error: str | None = None,
    subsidiary: bool = False,
) -> ChainInput:
    return ChainInput(
        rcept_no, corp, key, filed, rm, correction, in_scope, target, target_error, subsidiary
    )


def test_window_is_twelve_months_inclusive() -> None:
    assert window_bounds(D(2026, 11, 17)) == (D(2025, 11, 18), D(2026, 11, 17))
    assert window_bounds(D(2028, 2, 29)) == (D(2027, 3, 1), D(2028, 2, 29))


# -- correction chains ---------------------------------------------------------------------------


def test_correction_links_to_the_original_by_first_filing_date() -> None:
    results = resolve_chains(
        [
            entry("A", D(2026, 7, 27), rm="정"),
            entry("B", D(2026, 10, 30), correction=True, rm="정",
                  target=CorrectionTarget("주요사항보고서(유상증자결정)", D(2026, 7, 27))),
            entry("C", D(2026, 11, 3), correction=True,
                  target=CorrectionTarget("주요사항보고서(유상증자결정)", D(2026, 7, 27))),
        ]
    )
    assert (results["B"].correction_link, results["B"].original_rcept_no) == ("linked", "A")
    assert (results["C"].correction_link, results["C"].original_rcept_no) == ("linked", "A")
    assert results["A"].correction_link == "none"
    # Newest version of the chain is shown; the others are kept but not latest.
    assert {k: v.is_latest for k, v in results.items()} == {"A": False, "B": False, "C": True}


def test_chain_latest_follows_filing_date_not_input_order() -> None:
    target = CorrectionTarget(None, D(2026, 1, 5))
    results = resolve_chains(
        [
            entry("C2", D(2026, 3, 1), correction=True, target=target),
            entry("O", D(2026, 1, 5)),
            entry("C1", D(2026, 2, 1), correction=True, target=target),
        ]
    )
    assert [k for k, v in results.items() if v.is_latest] == ["C2"]


def test_same_day_versions_order_by_receipt_number() -> None:
    target = CorrectionTarget(None, D(2026, 1, 5))
    results = resolve_chains(
        [
            entry("20260105000001", D(2026, 1, 5)),
            entry("20260110000002", D(2026, 1, 10), correction=True, target=target),
            entry("20260110000009", D(2026, 1, 10), correction=True, target=target),
        ]
    )
    assert [k for k, v in results.items() if v.is_latest] == ["20260110000009"]


def test_unlinked_reasons_are_recorded_and_nothing_is_guessed() -> None:
    first = D(2026, 7, 27)
    results = resolve_chains(
        [
            entry("A", first),
            entry("A2", first),  # two originals the same day
            entry("OTHER-CORP", first, corp="C2"),
            entry("no-body", D(2026, 8, 1), correction=True, target_error="document fetch failed"),
            entry("no-date", D(2026, 8, 2), correction=True),
            entry("two", D(2026, 8, 3), correction=True, target=CorrectionTarget(None, first)),
            entry("none", D(2026, 8, 4), correction=True,
                  target=CorrectionTarget(None, D(2020, 1, 1))),
            entry("renamed", D(2026, 8, 5), correction=True,
                  target=CorrectionTarget("주요사항보고서(감자결정)", first)),
        ]
    )
    for rcept in ("no-body", "no-date", "two", "none", "renamed"):
        assert results[rcept].correction_link == "unlinked", rcept
        assert results[rcept].original_rcept_no is None
        assert results[rcept].note
    assert "document fetch failed" in results["no-body"].note
    assert "2 originals" in results["two"].note
    assert "no original" in results["none"].note
    assert "differs" in results["renamed"].note
    # No chain was formed, so every original stays the latest of itself.
    assert results["A"].is_latest and results["A2"].is_latest


def test_a_different_report_or_company_is_never_an_original() -> None:
    results = resolve_chains(
        [
            entry("other-report", D(2026, 7, 27), key="감자결정"),
            entry("other-corp", D(2026, 7, 27), corp="C2"),
            entry("C", D(2026, 8, 1), correction=True, target=CorrectionTarget(None, D(2026, 7, 27))),
        ]
    )
    assert results["C"].correction_link == "unlinked"


def test_unlinked_correction_still_supersedes_via_rm_and_excluded_filings_are_not_chained() -> None:
    results = resolve_chains(
        [
            entry("old", D(2026, 1, 1), correction=True, rm="정", target_error="x"),
            entry("new", D(2026, 2, 1), correction=True, target_error="x"),
            entry("ex", D(2026, 3, 1), correction=True, in_scope=False),
            entry("plain", D(2026, 3, 2), rm="유"),
            entry("replaced", D(2026, 3, 3), rm="유정"),
        ]
    )
    assert results["old"].is_latest is False
    assert results["new"].is_latest is True
    assert results["ex"].correction_link == "not_resolved_excluded"
    assert results["ex"].is_latest is True
    assert results["plain"].is_latest is True
    assert results["replaced"].is_latest is False


def test_correction_of_an_excluded_original_is_not_linked_to_it() -> None:
    results = resolve_chains(
        [
            entry("orig", D(2026, 7, 27), in_scope=False),
            entry("c", D(2026, 8, 1), correction=True, target=CorrectionTarget(None, D(2026, 7, 27))),
        ]
    )
    assert results["c"].correction_link == "unlinked"


# -- exactly one latest per chain (reviewer item 2) ----------------------------------------------


def _latest(results) -> list[str]:
    return sorted(k for k, v in results.items() if v.is_latest)


def _target(first: datetime.date) -> CorrectionTarget:
    return CorrectionTarget(None, first)


def test_a_chain_has_exactly_one_latest_even_when_replaced_members_carry_rm() -> None:
    first = D(2026, 7, 27)
    results = resolve_chains(
        [
            entry("O", first, rm="유정"),
            entry("C1", D(2026, 8, 1), correction=True, rm="유정", target=_target(first)),
            entry("C2", D(2026, 8, 5), correction=True, rm="유", target=_target(first)),
        ]
    )
    assert [results[k].correction_link for k in ("O", "C1", "C2")] == ["none", "linked", "linked"]
    assert _latest(results) == ["C2"]


def test_an_unlinked_newest_correction_is_the_only_latest_when_linked_members_say_replaced() -> None:
    first = D(2026, 7, 27)
    results = resolve_chains(
        [
            entry("O", first, rm="유정"),
            entry("C1", D(2026, 8, 1), correction=True, rm="유정", target=_target(first)),
            entry("C2", D(2026, 8, 5), correction=True, rm="유", target_error="body unreadable"),
        ]
    )
    assert results["C1"].correction_link == "linked"
    assert results["C2"].correction_link == "unlinked"
    assert _latest(results) == ["C2"]


def test_a_replaced_member_is_never_latest_even_when_it_is_the_newest_of_its_chain() -> None:
    first = D(2026, 7, 27)
    results = resolve_chains(
        [
            entry("O", first, rm="유정"),
            entry("C1", D(2026, 8, 1), correction=True, rm="유정", target=_target(first)),
        ]
    )
    assert _latest(results) == []


# -- chains do not cross the subsidiary flag (reviewer item 6) -----------------------------------


def test_a_subsidiary_correction_never_links_to_the_parents_filing() -> None:
    first = D(2026, 7, 27)
    results = resolve_chains(
        [
            entry("parent", first),
            entry("sub", first, subsidiary=True),
            entry("sub-fix", D(2026, 8, 1), correction=True, subsidiary=True, target=_target(first)),
            entry("parent-fix", D(2026, 8, 2), correction=True, target=_target(first)),
        ]
    )
    assert results["sub-fix"].original_rcept_no == "sub"
    assert results["parent-fix"].original_rcept_no == "parent"
    assert _latest(results) == ["parent-fix", "sub-fix"]


def test_a_subsidiary_correction_with_only_a_parent_original_stays_unlinked() -> None:
    first = D(2026, 7, 27)
    results = resolve_chains(
        [
            entry("parent", first),
            entry("sub-fix", D(2026, 8, 1), correction=True, subsidiary=True, target=_target(first)),
        ]
    )
    assert results["sub-fix"].correction_link == "unlinked"
    assert "no original filed on 2026-07-27" in results["sub-fix"].note


# -- an impossible first-filing date is named in the note (reviewer item 10) --------------------


def test_an_impossible_first_filing_date_is_named_in_the_note() -> None:
    bad = CorrectionTarget("유상증자결정", None, "impossible first-filing date '2026년 13월 40일'")
    results = resolve_chains(
        [entry("O", D(2026, 7, 27)), entry("C", D(2026, 8, 1), correction=True, target=bad)]
    )
    assert results["C"].correction_link == "unlinked"
    assert "2026년 13월 40일" in results["C"].note


# -- collect step on the NAVER fixtures ----------------------------------------------------------

CORRECTION_BODY = DART / "correction" / "20261103000311.xml"


def collect(client: FakeDartClient):
    return asyncio.run(
        collect_dart_events(client, "00266961", (D(2025, 11, 18), D(2026, 11, 17)))
    )


def test_naver_corrected_rights_issue_chain_and_facts() -> None:
    client = FakeDartClient("035420", documents={"20261103000311": CORRECTION_BODY})
    records, summary = collect(client)
    by = {r.item.rcept_no: r for r in records}

    assert summary.listed == len(records) == len({r.item.rcept_no for r in records})
    original, middle, newest = by["20260727000001"], by["20261030000001"], by["20261103000311"]
    assert all(r.classification.category == "capital" for r in (original, middle, newest))

    assert newest.chain.correction_link == "linked"
    assert newest.chain.original_rcept_no == "20260727000001"
    assert newest.chain.first_filed_at == D(2026, 7, 27)
    # Its body names no original, so it is recorded as unlinked rather than guessed.
    assert middle.chain.correction_link == "unlinked"
    assert "no first-filing date" in middle.chain.note
    assert (original.chain.is_latest, middle.chain.is_latest, newest.chain.is_latest) == (
        False, False, True,
    )

    # The structured endpoint returns the newest version only; the facts attach to it.
    assert [r.item.rcept_no for r in records if r.facts] == ["20261103000311"]
    facts = {f.key: f for f in newest.facts}
    assert facts["new_shares_common"].value_decimal == Decimal("6558435")

    # 22 corrections in an event category have no saved body or name no original (D76 brought
    # seven of them into scope: outlook, lending, management); the one notice correction is
    # counted apart so it does not inflate ``unlinked``.
    assert (summary.linked, summary.unlinked, summary.not_resolved_excluded) == (1, 21, 1)
    assert summary.ok, summary.problems
    assert "not_resolved_excluded=1" in format_summary(summary)
    assert ("structured", "piicDecsn.json") in client.calls
    assert not any(c[0] == "structured" and "tsstkAq" in c[1] for c in client.calls)


@pytest.mark.parametrize("stock", ["035420", "000270"])
def test_excluded_filings_are_kept_with_a_reason_and_counted(stock: str) -> None:
    client = FakeDartClient(stock, documents={"20261103000311": CORRECTION_BODY})
    records, summary = collect(client)
    excluded = [r for r in records if r.classification.category is None]
    notices = [r for r in records if r.classification.kind == "notice"]
    assert notices
    assert excluded or stock == "035420"  # NAVER's sample has no ownership report
    for record in excluded:
        assert record.classification.excluded_reason
    assert sum(summary.excluded.values()) == len(excluded)
    assert sum(summary.notices.values()) == len(notices)
    assert sum(summary.by_category.values()) + len(notices) + len(excluded) == summary.listed
    # A body is fetched for every in-scope filing (its text is stored) and for names the
    # contract cannot decide without it (plain 영업(잠정)실적), never for another excluded one.
    fetched = {c[1] for c in client.calls if c[0] == "document"}
    in_scope = {r.item.rcept_no for r in records if is_event_category(r.classification.category)}
    needs_body = {
        r.item.rcept_no
        for r in records
        if classify_dart(r.item.report_nm).excluded_reason == "needs_body"
    }
    assert needs_body and fetched == in_scope | needs_body
    # The saved M2 bodies decide every one of them.
    for rcept in needs_body:
        record = next(r for r in records if r.item.rcept_no == rcept)
        assert record.classification.excluded_reason != "needs_body"
    assert summary.ok, summary.problems


def test_in_scope_filings_without_a_structured_endpoint_get_no_facts() -> None:
    client = FakeDartClient("035420", documents={"20261103000311": CORRECTION_BODY})
    records, _ = collect(client)
    assert all(not r.facts for r in records if r.base_key != "유상증자결정")


def test_partial_listing_is_a_problem_not_a_silent_drop() -> None:
    client = FakeDartClient(
        "035420",
        documents={"20261103000311": CORRECTION_BODY},
        list_errors={"I": ["page 2: list.json returned status 020: 제한"]},
    )
    records, summary = collect(client)
    assert summary.ok is False
    assert summary.problems == ["list I: page 2: list.json returned status 020: 제한"]
    assert "PROBLEM list I: page 2" in format_summary(summary)
    assert records  # what was fetched is still processed


def test_structured_failure_is_reported() -> None:
    class Failing(FakeDartClient):
        async def _get(self, endpoint, params):
            raise_status = {"status": "020", "message": "요청 제한"}
            return type("R", (), {"json": lambda self: raise_status})()

    _, summary = collect(Failing("035420", documents={"20261103000311": CORRECTION_BODY}))
    assert summary.ok is False
    assert any("piicDecsn" in p and "020" in p for p in summary.problems)


@pytest.mark.parametrize("ticker", ["999999"])
def test_unknown_ticker_exits(ticker) -> None:
    from app.ingest.events import run_dart_events

    with pytest.raises(SystemExit):
        asyncio.run(run_dart_events(FakeDartClient("035420"), ticker, lambda: None))


# -- per-filing failures are problems (reviewer items 3 and 9) ------------------------------------


def test_a_document_that_cannot_be_fetched_is_a_problem_and_is_listed() -> None:
    client = FakeDartClient("035420", missing="fail", use_classifier_documents=False)
    records, summary = collect(client)
    failed = {
        r.item.rcept_no
        for r in records
        if r.degraded
    }
    assert failed
    assert summary.ok is False
    listed = {p.split()[1].rstrip(":") for p in summary.problems if p.startswith("document ")}
    assert failed <= listed
    assert all("014" in p for p in summary.problems if p.startswith("document "))
    text = format_summary(summary)
    assert all(f"PROBLEM document {rcept}" in text for rcept in failed)


def test_a_needs_body_filing_whose_body_cannot_be_read_is_a_problem() -> None:
    client = FakeDartClient("035420", missing="fail", use_classifier_documents=False)
    records, summary = collect(client)
    stuck = [r for r in records if r.classification.excluded_reason == "needs_body"]
    assert stuck and all(r.degraded and r.errors for r in stuck)
    assert not summary.ok
    assert all(
        any(f"document {r.item.rcept_no}" in p for p in summary.problems) for r in stuck
    )


def test_a_bad_zip_or_unusable_member_is_recorded_per_filing_and_the_run_continues() -> None:
    broken = {
        "20261030000001": zipfile.BadZipFile("File is not a zip file"),
        "20260202801571": DartApiError("document.xml ZIP contained no members"),
    }
    client = FakeDartClient(
        "035420", documents={"20261103000311": CORRECTION_BODY}, broken=broken
    )
    records, summary = collect(client)
    by = {r.item.rcept_no: r for r in records}
    assert by["20261103000311"].chain.correction_link == "linked"  # the run went on
    assert by["20261030000001"].errors == ["document fetch failed: File is not a zip file"]
    assert by["20261030000001"].chain.correction_link == "unlinked"
    assert by["20260202801571"].degraded
    assert summary.ok is False
    assert sorted(p for p in summary.problems if p.startswith("document ")) == [
        "document 20260202801571: document fetch failed: document.xml ZIP contained no members",
        "document 20261030000001: document fetch failed: File is not a zip file",
    ]


def test_the_cli_exits_non_zero_when_a_body_could_not_be_read(monkeypatch, capsys) -> None:
    from app.ingest import events

    _, summary = collect(FakeDartClient("035420", missing="fail", use_classifier_documents=False))

    async def fake_run(ticker: str, pinned=None):
        return summary

    monkeypatch.setattr(events, "_run", fake_run)
    with pytest.raises(SystemExit) as stop:
        events.main(["--source", "dart", "--ticker", "035420"])
    assert stop.value.code == 1
    assert "PROBLEM document" in capsys.readouterr().out


def test_a_real_exchange_correction_links_to_its_original_end_to_end() -> None:
    # SK hynix 주식소각결정: the 2026-10-26 [기재정정] body (ISO date) names the 2026-08-19 filing.
    client = FakeDartClient(
        "000660",
        documents={"20261026800524": DART / "correction" / "20261026800524.xml"},
        missing="fail",
    )
    records, _ = collect(client)
    by = {r.item.rcept_no: r for r in records}
    fix, original = by["20261026800524"], by["20260819800340"]
    assert fix.chain.correction_link == "linked"
    assert fix.chain.original_rcept_no == "20260819800340"
    assert fix.chain.first_filed_at == D(2026, 8, 19)
    assert (original.chain.is_latest, fix.chain.is_latest) == (False, True)


# -- body text of in-scope filings (M3 follow-up) -------------------------------------------------

UNREAD = "20260727800009"  # 주식소각결정: in scope, not a correction, no body needed to classify


def test_the_text_limit_is_the_one_the_sec_ingest_uses() -> None:
    assert events.TEXT_STORE_LIMIT is sec_8k.TEXT_STORE_LIMIT


def test_store_body_text_cuts_exactly_over_the_limit_and_says_so() -> None:
    assert store_body_text("abcde", 5) == ("abcde", False)
    assert store_body_text("abcdef", 5) == ("abcde", True)
    assert store_body_text("", 5) == ("", False)


def test_in_scope_filings_get_their_plain_text_and_excluded_ones_do_not() -> None:
    client = FakeDartClient("035420", documents={"20261103000311": CORRECTION_BODY})
    records, summary = collect(client)
    in_scope = [r for r in records if is_event_category(r.classification.category)]
    excluded = [r for r in records if not is_event_category(r.classification.category)]
    assert in_scope and excluded

    for record in in_scope:
        assert record.body_text, record.key
        row = record.to_row()
        assert row["body_text"] == record.body_text and row["body_truncated"] is False
    # The text is what the existing reader makes of the saved body, not a placeholder.
    chosen = next(r for r in in_scope if r.key == "20261103000311")
    assert chosen.body_text == read_event_document(CORRECTION_BODY.read_bytes()).text
    assert len(chosen.body_text) > 1000

    for record in excluded:
        assert record.body_text is None
        assert "body_text" not in record.to_row()  # a stored text is not overwritten
    assert summary.bodies_stored == len(in_scope)
    assert summary.bodies_truncated == 0


def test_notices_get_no_body_no_chain_and_no_structured_call() -> None:
    client = FakeDartClient("035420", documents={"20261103000311": CORRECTION_BODY})
    records, summary = collect(client)
    notices = [r for r in records if r.classification.kind == "notice"]
    assert {r.classification.category for r in notices} >= {"ir_event", "meeting_notice"}
    fetched = {c[1] for c in client.calls if c[0] == "document"}
    for record in notices:
        assert record.key not in fetched
        assert record.body_text is None and "body_text" not in record.to_row()
        assert record.chain.correction_link in ("none", "not_resolved_excluded")
        assert not record.facts
    assert sum(summary.notices.values()) == len(notices)
    assert "notices: " in format_summary(summary) and "ir_event=" in format_summary(summary)


def test_a_rerun_under_a_newer_contract_fetches_bodies_it_brought_into_scope(monkeypatch) -> None:
    """A filing excluded under the old contract stored no body. Every run classifies again, so
    the first run after D76 fetches and keeps the text of every filing it brought into scope."""
    from app.filings import categories as categories_module

    newly_in_scope = ("outlook", "clarification", "lending", "management", "shareholder_value")
    current = categories_module.load_contract()
    old = copy.deepcopy(current)
    old["dart"]["rules"] = [r for r in old["dart"]["rules"] if r["category"] not in newly_in_scope]
    old["dart"]["exclusions"].append(
        {"id": "dart.x.old", "reason": "no_rule", "prefixes": [
            p for r in current["dart"]["rules"] if r["category"] in newly_in_scope
            for p in r["prefixes"]
        ]}
    )  # fmt: skip
    monkeypatch.setattr(categories_module, "load_contract", lambda: old)
    first_client = FakeDartClient("035420", documents={"20261103000311": CORRECTION_BODY})
    first, _ = collect(first_client)
    before = {r.key: r for r in first}
    monkeypatch.undo()

    second_client = FakeDartClient("035420", documents={"20261103000311": CORRECTION_BODY})
    second, summary = collect(second_client)
    brought = [r for r in second if r.classification.category in newly_in_scope]
    assert {r.classification.category for r in brought} == set(newly_in_scope)
    first_fetched = {c[1] for c in first_client.calls if c[0] == "document"}
    second_fetched = {c[1] for c in second_client.calls if c[0] == "document"}
    for record in brought:
        assert before[record.key].classification.excluded_reason == "no_rule"
        assert before[record.key].body_text is None and record.key not in first_fetched
        assert record.key in second_fetched
        assert record.body_text and record.to_row()["body_text"] == record.body_text
    assert summary.ok, summary.problems


def test_a_long_body_is_cut_at_the_limit_and_flagged(monkeypatch) -> None:
    monkeypatch.setattr(events, "TEXT_STORE_LIMIT", 100)
    client = FakeDartClient("035420", documents={"20261103000311": CORRECTION_BODY})
    records, summary = collect(client)
    full = read_event_document(CORRECTION_BODY.read_bytes()).text
    chosen = next(r for r in records if r.key == "20261103000311")
    assert chosen.body_text == full[:100]
    assert chosen.body_truncated is True
    assert chosen.to_row()["body_truncated"] is True
    short = next(r for r in records if r.key == UNREAD)
    assert short.body_text == "본문 없음" and short.body_truncated is False
    assert all(len(r.body_text) <= 100 for r in records if r.body_text)
    cut = sum(1 for r in records if r.body_truncated)
    assert cut == summary.bodies_truncated and cut > 1  # the long bodies, not the 5-character ones
    assert f"cut at 100 characters={cut}" in format_summary(summary)


def test_the_summary_counts_every_document_request_once() -> None:
    client = FakeDartClient("035420", documents={"20261103000311": CORRECTION_BODY})
    records, summary = collect(client)
    requested = [c[1] for c in client.calls if c[0] == "document"]
    assert len(requested) == len(set(requested))  # never fetched twice
    in_scope = {r.key for r in records if is_event_category(r.classification.category)}
    needs_body = {
        r.key for r in records if classify_dart(r.item.report_nm).excluded_reason == "needs_body"
    }
    assert summary.documents_fetched == len(requested) == len(in_scope | needs_body)
    assert f"documents fetched={len(requested)} bodies stored={len(in_scope)}" in format_summary(
        summary
    )


def test_a_failed_fetch_sets_no_text_and_is_a_problem_without_freezing_the_chain() -> None:
    broken = {UNREAD: DartApiError("document.xml unavailable")}
    client = FakeDartClient("035420", documents={"20261103000311": CORRECTION_BODY}, broken=broken)
    records, summary = collect(client)
    record = next(r for r in records if r.key == UNREAD)
    assert record.body_text is None and "body_text" not in record.to_row()
    assert not record.degraded  # its category never depended on the body
    assert record.classification.category is not None
    assert any(p.startswith(f"document {UNREAD}") for p in summary.problems)
    assert any("unavailable" in e for e in record.errors)
    assert not summary.ok
    healthy = next(r for r in records if r.key == "20260727000001")
    assert healthy.body_text
    # The failed request still counts: it was made.
    assert summary.documents_fetched == len({c[1] for c in client.calls if c[0] == "document"})


def test_an_empty_extracted_body_leaves_the_text_unset_not_an_empty_string(tmp_path) -> None:
    empty = tmp_path / "empty.xml"
    empty.write_text("<html><body>  </body></html>", encoding="utf-8")
    client = FakeDartClient("035420", documents={"20261103000311": CORRECTION_BODY, UNREAD: empty})
    records, summary = collect(client)
    record = next(r for r in records if r.key == UNREAD)
    assert record.body_text is None and "body_text" not in record.to_row()
    assert summary.bodies_stored == len(
        [r for r in records if is_event_category(r.classification.category)]
    ) - 1
