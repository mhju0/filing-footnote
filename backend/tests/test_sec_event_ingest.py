"""SEC 8-K event ingest logic without a database: 8-K/A chains and the collect step."""

from __future__ import annotations

import asyncio
import datetime

from app.clients.sec import SecFilingItem
from app.clients.sec_8k import TEXT_STORE_LIMIT
from app.ingest.events import window_bounds
from app.ingest.sec_events import (
    SecChainInput,
    collect_sec_events,
    format_sec_summary,
    item_set,
    resolve_sec_chains,
    sec_facts,
)
from tests.sec_fakes import HTML, FakeSecClient

D = datetime.date
CIK = "0000320193"
TODAY = D(2026, 11, 17)

EARNINGS = "0000320193-26-000024"
LEADERSHIP = "0001140361-26-015711"
AMENDMENT = "0001140361-26-035325"
VOTE = "0001140361-26-006577"
BROKEN = "0000320193-26-000018"


def chain_entry(
    key: str,
    filed: datetime.date,
    report: datetime.date | None,
    items: str,
    *,
    correction: bool = False,
    in_scope: bool = True,
    cik: str = CIK,
) -> SecChainInput:
    return SecChainInput(key, cik, filed, report, item_set(items), correction, in_scope)


# -- chains --------------------------------------------------------------------------------------


def test_an_amendment_links_to_the_one_original_with_the_same_event_date_and_a_shared_item() -> None:
    chains = resolve_sec_chains(
        [
            chain_entry("sec:orig", D(2026, 4, 20), D(2026, 4, 17), "5.02,9.01"),
            chain_entry("sec:other-day", D(2026, 4, 21), D(2026, 4, 18), "5.02"),
            chain_entry("sec:other-item", D(2026, 4, 20), D(2026, 4, 17), "1.01"),
            chain_entry("sec:amend", D(2026, 9, 1), D(2026, 4, 17), "5.02", correction=True),
        ]
    )
    amend = chains["sec:amend"]
    assert (amend.correction_link, amend.original_rcept_no) == ("linked", "sec:orig")
    assert amend.first_filed_at == D(2026, 4, 20) and amend.is_latest and amend.note is None
    assert chains["sec:orig"].correction_link == "none" and not chains["sec:orig"].is_latest
    assert chains["sec:other-day"].is_latest and chains["sec:other-item"].is_latest


def test_two_candidate_originals_leave_the_amendment_unlinked() -> None:
    chains = resolve_sec_chains(
        [
            chain_entry("sec:a", D(2026, 4, 20), D(2026, 4, 17), "5.02"),
            chain_entry("sec:b", D(2026, 4, 20), D(2026, 4, 17), "5.02,9.01"),
            chain_entry("sec:amend", D(2026, 9, 1), D(2026, 4, 17), "5.02", correction=True),
        ]
    )
    amend = chains["sec:amend"]
    assert (amend.correction_link, amend.original_rcept_no) == ("unlinked", None)
    assert "2 original 8-Ks" in str(amend.note)
    assert chains["sec:a"].is_latest and chains["sec:b"].is_latest  # no chain was formed


def test_sharing_only_item_9_01_is_not_enough_to_link() -> None:
    chains = resolve_sec_chains(
        [
            chain_entry("sec:orig", D(2026, 4, 20), D(2026, 4, 17), "2.03,9.01"),
            chain_entry("sec:amend", D(2026, 9, 1), D(2026, 4, 17), "5.02,9.01", correction=True),
        ]
    )
    assert chains["sec:amend"].correction_link == "unlinked"
    assert "no original" in str(chains["sec:amend"].note)


def test_other_companies_later_filings_and_excluded_originals_are_never_linked() -> None:
    chains = resolve_sec_chains(
        [
            chain_entry("sec:other-co", D(2026, 4, 20), D(2026, 4, 17), "5.02", cik="0000000001"),
            chain_entry("sec:late", D(2026, 10, 1), D(2026, 4, 17), "5.02"),  # after the amendment
            chain_entry("sec:excluded", D(2026, 4, 20), D(2026, 4, 17), "5.02", in_scope=False),
            chain_entry("sec:amend", D(2026, 9, 1), D(2026, 4, 17), "5.02", correction=True),
        ]
    )
    assert chains["sec:amend"].correction_link == "unlinked"


def test_an_amendment_without_an_event_date_is_unlinked() -> None:
    chains = resolve_sec_chains(
        [
            chain_entry("sec:orig", D(2026, 4, 20), None, "5.02"),
            chain_entry("sec:amend", D(2026, 9, 1), None, "5.02", correction=True),
        ]
    )
    assert chains["sec:amend"].correction_link == "unlinked"
    assert "no event date" in str(chains["sec:amend"].note)


def test_an_excluded_sibling_with_the_same_event_date_blocks_linking_to_the_in_scope_one() -> None:
    chains = resolve_sec_chains(
        [
            chain_entry("sec:excluded", D(2026, 4, 20), D(2026, 4, 17), "5.02,9.01", in_scope=False),
            chain_entry("sec:sibling", D(2026, 4, 21), D(2026, 4, 17), "5.02"),
            chain_entry("sec:amend", D(2026, 9, 1), D(2026, 4, 17), "5.02", correction=True),
        ]
    )
    amend = chains["sec:amend"]
    assert (amend.correction_link, amend.original_rcept_no) == ("unlinked", None)
    assert "2 original 8-Ks" in str(amend.note)
    assert chains["sec:sibling"].is_latest


def test_when_the_one_true_original_is_excluded_the_amendment_is_never_linked() -> None:
    chains = resolve_sec_chains(
        [
            chain_entry("sec:excluded", D(2026, 4, 20), D(2026, 4, 17), "5.02", in_scope=False),
            chain_entry("sec:other-day", D(2026, 4, 21), D(2026, 4, 18), "5.02"),
            chain_entry("sec:amend", D(2026, 9, 1), D(2026, 4, 17), "5.02", correction=True),
        ]
    )
    amend = chains["sec:amend"]
    assert (amend.correction_link, amend.original_rcept_no) == ("unlinked", None)
    assert "not in scope" in str(amend.note)


def test_an_excluded_amendment_is_not_resolved() -> None:
    chains = resolve_sec_chains(
        [
            chain_entry("sec:orig", D(2026, 4, 20), D(2026, 4, 17), "5.02"),
            chain_entry("sec:amend", D(2026, 9, 1), D(2026, 4, 17), "9.01", correction=True, in_scope=False),
        ]
    )
    assert chains["sec:amend"].correction_link == "not_resolved_excluded"
    assert chains["sec:amend"].original_rcept_no is None
    assert chains["sec:orig"].is_latest  # the excluded amendment does not join the chain


def test_only_the_newest_member_of_a_chain_is_latest() -> None:
    chains = resolve_sec_chains(
        [
            chain_entry("sec:orig", D(2026, 4, 20), D(2026, 4, 17), "5.02"),
            chain_entry("sec:am1", D(2026, 5, 1), D(2026, 4, 17), "5.02", correction=True),
            chain_entry("sec:am2", D(2026, 6, 1), D(2026, 4, 17), "5.02", correction=True),
        ]
    )
    # Both amendments find the one original; the newest of the three is shown.
    assert {k: v.is_latest for k, v in chains.items()} == {
        "sec:orig": False,
        "sec:am1": False,
        "sec:am2": True,
    }
    assert chains["sec:am1"].original_rcept_no == chains["sec:am2"].original_rcept_no == "sec:orig"


# -- facts ---------------------------------------------------------------------------------------


def test_facts_are_items_and_event_date_only_with_exact_values() -> None:
    facts = {
        f.key: f
        for f in sec_facts(
            SecFilingItem("a", "8-K", D(2026, 11, 2), D(2026, 11, 1), "p.htm", items="2.02,9.01")
        )
    }
    assert set(facts) == {"items", "report_date"}
    assert (facts["items"].kind, facts["items"].value_text) == ("text", "2.02,9.01")
    assert facts["items"].source_field == "sec:submissions.items"
    assert (facts["report_date"].kind, facts["report_date"].value_date) == ("date", D(2026, 11, 1))
    assert all(f.value_decimal is None and f.error is None for f in facts.values())
    assert sec_facts(SecFilingItem("a", "8-K", None, None, "p.htm")) == []


# -- collect over the saved M1 fixtures -----------------------------------------------------------


def scenario_client() -> FakeSecClient:
    docs = {
        (AMENDMENT, "ef20081427_8ka.htm"): HTML.format("Amendment to the leadership report.").encode(),
        (BROKEN, "aapl-20260730.htm"): HTML.format("Results.").encode(),
    }
    return FakeSecClient(
        accessions={EARNINGS, LEADERSHIP, AMENDMENT, VOTE, BROKEN},
        indexes={
            EARNINGS: [
                ("aapl-20261102.htm", "8-K"),
                ("a8-kex991q4202609262026.htm", "EX-99.1"),
                ("slides.pdf", "EX-99.2"),
            ],
            AMENDMENT: [("ef20081427_8ka.htm", "8-K/A")],
            BROKEN: [("aapl-20260730.htm", "8-K"), ("ex991.htm", "EX-99.1")],
        },
        documents=docs,
        broken={(BROKEN, "ex991.htm")},
    )


def collect(client: FakeSecClient):
    records, summary = asyncio.run(
        collect_sec_events(client, CIK, "AAPL", "Apple Inc.", window_bounds(TODAY))
    )
    return {r.key: r for r in records}, summary


def test_collect_classifies_links_and_reports_over_the_saved_fixtures() -> None:
    client = scenario_client()
    records, summary = collect(client)
    assert len(records) == summary.listed == 5

    earnings = records[f"sec:{EARNINGS}"]
    assert (earnings.classification.category, earnings.classification.matched_rule) == (
        "earnings",
        "sec.2.02.results",
    )
    assert earnings.degraded is False and earnings.errors == []
    assert earnings.body_text is not None and earnings.body_text.startswith("[8-K]\n")
    # Fixed input: the saved primary (2218 chars) and EX-99.1 (6114 chars) with their headers.
    assert len(earnings.body_text) == 2218 + 6114 + len("[8-K]\n") + len("\n\n[EX-99.1]\n")
    assert len(earnings.body_text) < TEXT_STORE_LIMIT and earnings.body_truncated is False
    assert {f.key for f in earnings.facts or []} == {"items", "report_date"}
    assert earnings.to_row()["source"] == "sec"
    assert earnings.to_row()["url"].endswith(f"/320193/000032019326000024/{EARNINGS}-index.html")

    original = records[f"sec:{LEADERSHIP}"]
    amendment = records[f"sec:{AMENDMENT}"]
    assert original.classification.category == amendment.classification.category == "leadership"
    assert amendment.classification.is_correction and not original.classification.is_correction
    assert amendment.chain.correction_link == "linked"
    assert amendment.chain.original_rcept_no == original.key
    assert amendment.chain.is_latest and not original.chain.is_latest

    vote = records[f"sec:{VOTE}"]
    assert vote.classification.category is None
    assert vote.classification.excluded_reason == "shareholder_vote"
    assert {f.key for f in vote.facts or []} == {"items", "report_date"}  # excluded ones too
    assert vote.body_text is None
    # An excluded filing is not fetched at all.
    assert not any(VOTE in call for call in client.calls)

    assert summary.skipped_exhibits == [f"{EARNINGS} EX-99.2 slides.pdf"]
    assert summary.by_category == {"earnings": 1, "leadership": 2}
    assert summary.excluded == {"shareholder_vote": 1, "needs_body": 1}
    assert (summary.linked, summary.unlinked) == (1, 0)
    assert summary.truncated == 0
    # The failed exhibit is the one problem, and its line names the accession (item 6).
    assert summary.problems == [f"document {BROKEN} EX-99.1 ex991.htm: ex991.htm unavailable"]
    assert not summary.ok


def test_a_failed_exhibit_leaves_a_body_item_filing_needs_body_not_a_guessed_category() -> None:
    records, _ = collect(scenario_client())
    broken = records[f"sec:{BROKEN}"]
    assert broken.degraded is True
    # Its primary document alone would classify as earnings; with an exhibit missing, no category.
    assert broken.classification.category is None
    assert broken.classification.excluded_reason == "needs_body"
    assert broken.body_text is None and broken.body_truncated is False
    assert broken.errors == [f"{BROKEN} EX-99.1 ex991.htm: ex991.htm unavailable"]
    assert {f.key for f in broken.facts or []} == {"items", "report_date"}  # from the listing


def test_a_failed_document_on_a_filing_without_body_items_keeps_its_item_category() -> None:
    client = scenario_client()
    client.broken.add((LEADERSHIP, "ef20071035_8k.htm"))
    records, summary = collect(client)
    original = records[f"sec:{LEADERSHIP}"]
    assert original.degraded and original.classification.category == "leadership"
    assert original.body_text is None  # no partial text is kept
    assert any(p.startswith(f"document {LEADERSHIP} 8-K ef20071035_8k.htm") for p in summary.problems)


def test_a_failed_listing_page_is_a_problem_and_the_run_is_not_ok() -> None:
    client = scenario_client()
    client.list_problems = ["0000320193 CIK0000320193-submissions-001.json: boom"]
    _, summary = collect(client)
    assert "list: 0000320193 CIK0000320193-submissions-001.json: boom" in summary.problems
    assert not summary.ok


def test_stored_filings_from_before_the_window_are_candidates_for_an_amendments_original() -> None:
    # A stored sibling with the same event date and item makes the original ambiguous.
    sibling = chain_entry("sec:0000000000-25-000001", D(2025, 11, 1), D(2026, 4, 17), "5.02")
    records, _ = asyncio.run(
        collect_sec_events(
            scenario_client(), CIK, "AAPL", "Apple Inc.", window_bounds(TODAY), [sibling]
        )
    )
    amendment = {r.key: r for r in records}[f"sec:{AMENDMENT}"]
    assert amendment.chain.correction_link == "unlinked"
    assert "2 original 8-Ks" in str(amendment.chain.note)


def test_sec_fact_keys_and_sources_come_from_the_contract(monkeypatch) -> None:
    from app.ingest import sec_events

    contract = {
        "sec": {
            "fields": [
                {"key": "k_items", "kind": "text", "unit": None, "source_field": "sec:submissions.items"},
                {"key": "k_date", "kind": "date", "unit": None, "source_field": "sec:submissions.reportDate"},
            ]
        }
    }
    monkeypatch.setattr(sec_events, "load_facts_contract", lambda: contract)
    facts = {f.key: f for f in sec_facts(SecFilingItem("a", "8-K", D(2026, 1, 2), D(2026, 1, 1), "p", items="5.02"))}
    assert set(facts) == {"k_items", "k_date"}
    assert facts["k_items"].source_field == "sec:submissions.items"
    assert facts["k_date"].value_date == D(2026, 1, 1)


def test_summary_lists_skipped_exhibits_and_cuts_before_problems() -> None:
    _, summary = collect(scenario_client())
    out = format_sec_summary(summary)
    lines = out.splitlines()
    assert any(line.startswith("skipped exhibits (not text): 1") for line in lines)
    assert any(f"skipped {EARNINGS} EX-99.2 slides.pdf" in line for line in lines)
    assert any(f"text cut at {TEXT_STORE_LIMIT} characters" in line for line in lines)
    assert lines[-1].startswith("PROBLEM ")


def test_filings_outside_the_window_are_dropped() -> None:
    client = FakeSecClient(accessions={VOTE, "0001140361-25-044561"})
    records, summary = asyncio.run(
        collect_sec_events(client, CIK, "AAPL", "Apple Inc.", (D(2026, 1, 1), D(2026, 12, 31)))
    )
    assert [r.filing.accession_number for r in records] == [VOTE]
    assert summary.listed == 1


def test_amendments_of_a_missing_original_form_one_orphan_chain_with_one_latest() -> None:
    chains = resolve_sec_chains(
        [
            chain_entry("sec:am1", D(2026, 9, 1), D(2026, 4, 17), "5.02", correction=True),
            chain_entry("sec:am2", D(2026, 9, 9), D(2026, 4, 17), "5.02,9.01", correction=True),
            chain_entry("sec:other-day", D(2026, 9, 20), D(2026, 4, 18), "5.02", correction=True),
        ]
    )
    assert chains["sec:am1"].correction_link == chains["sec:am2"].correction_link == "unlinked"
    assert (chains["sec:am1"].is_latest, chains["sec:am2"].is_latest) == (False, True)
    assert chains["sec:other-day"].is_latest  # a different event date is its own chain
