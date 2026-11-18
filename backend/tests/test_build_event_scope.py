"""D72 and D76: the latest ten events per company and the notices beside them, one rule for
the exporter and the summary build."""

from __future__ import annotations

import dataclasses
import datetime

from app.build import export
from app.build.export import BuildOptions, build_bundle, event_scope
from app.build.model import BuildInput, CompanyRow, EventRow
from app.build.summaries import select_targets
from tests.build_seed import AS_OF, PINNED_DIRS, fixture_build_input

SAMSUNG = CompanyRow("DART", "00126380", "삼성전자", "SAMSUNG ELECTRONICS CO,.LTD", "005930", "Y")
OTHER = CompanyRow("DART", "00164779", "에스케이하이닉스", "SK hynix", "000660", "Y")


def _event(key: str, filed_on: datetime.date, body: str | None = "본문", **changes) -> EventRow:
    values = dict(
        regulator="DART", filing_key=key, company_key="00126380", stock_code="005930",
        report_nm="주요사항보고서(자기주식취득결정)", filed_on=filed_on, rm="유",
        url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={key}", category="buyback",
        excluded_reason=None, is_correction=False, chain_key=key, target_key=None,
        sec_items=None, body_text=body, facts=(),
    )  # fmt: skip
    values.update(changes)
    return EventRow(**values)


def _data(*events: EventRow) -> BuildInput:
    return BuildInput((SAMSUNG, OTHER), (), (), tuple(events))


def _day(offset: int) -> datetime.date:
    return AS_OF - datetime.timedelta(days=offset)


def _keys(data: BuildInput) -> list[str]:
    return [e.filing_key for e in event_scope(data, AS_OF).exported]


def test_twelve_events_keep_the_newest_ten() -> None:
    data = _data(*(_event(f"2026{n:08d}", _day(n * 10)) for n in range(1, 13)))
    assert export.EVENT_CAP == 10
    assert _keys(data) == [f"2026{n:08d}" for n in range(1, 11)]
    scope = event_scope(data, AS_OF)
    assert scope.capped == {"dart:00126380": ["dart:202600000011", "dart:202600000012"]}


def test_a_filing_date_tie_is_broken_by_filing_key_descending() -> None:
    same = _day(100)
    newer = [_event(f"2026{n:08d}", _day(1 + n)) for n in range(7)]
    tied = [_event(key, same) for key in ("20260000000A", "20260000000B", "20260000000C")]
    assert len(_keys(_data(*newer, *tied))) == 10  # nothing tied is dropped yet
    newer.append(_event("202600000009", _day(2)))
    kept = _keys(_data(*newer, *tied))
    assert len(kept) == 10 and "20260000000A" not in kept
    assert {"20260000000B", "20260000000C"} <= set(kept)


def test_an_event_without_a_body_is_left_out_and_does_not_count() -> None:
    bodyless = [_event(f"2026{n:08d}", _day(n), body=None) for n in range(1, 4)]
    withbody = [_event(f"2027{n:08d}", _day(50 + n * 10)) for n in range(1, 6)]
    scope = event_scope(_data(*bodyless, *withbody), AS_OF)
    assert [e.filing_key for e in scope.exported] == sorted(e.filing_key for e in withbody)
    assert scope.without_body == [f"dart:2026{n:08d}" for n in range(1, 4)]
    assert scope.capped == {}


def test_a_corrected_chain_counts_once() -> None:
    original = _event("20260000000001", _day(40), rm="정")
    correction = _event(
        "20260000000002", _day(30), is_correction=True, chain_key=original.chain_key, rm="유"
    )
    others = [_event(f"2027{n:08d}", _day(n * 5)) for n in range(1, 5)]
    scope = event_scope(_data(original, correction, *others), AS_OF)
    # Five chains, six filings: the correction is the one shown and nothing is capped.
    assert len(scope.exported) == 5 and scope.capped == {}
    assert "20260000000002" in [e.filing_key for e in scope.exported]
    assert scope.superseded == ["dart:20260000000001"]


def test_the_cap_is_per_company() -> None:
    mine = [_event(f"2026{n:08d}", _day(n)) for n in range(1, 12)]
    theirs = [
        _event(f"2027{n:08d}", _day(n), company_key="00164779", stock_code="000660")
        for n in range(1, 4)
    ]
    scope = event_scope(_data(*mine, *theirs), AS_OF)
    assert len(scope.exported) == 13
    assert scope.capped == {"dart:00126380": ["dart:202600000011"]}


def _fourteen_events() -> BuildInput:
    events = (
        _event(f"2026{n:08d}", _day(n * 7), body=None if n == 2 else "본문") for n in range(1, 15)
    )
    return dataclasses.replace(fixture_build_input(), events=tuple(events))


def test_the_summary_targets_and_the_exporter_return_the_same_events() -> None:
    data = _fourteen_events()
    targets = [t for t in select_targets(data, AS_OF) if t.kind == "event"]
    bundle = build_bundle(data, BuildOptions(AS_OF, "test", allow_unapproved=True), PINNED_DIRS)
    exported = [row[0] for row in bundle.rows["filings"] if row[2] == "event"]
    assert sorted(t.filing_id for t in targets) == sorted(exported)
    assert len(exported) == 10 and all(t.skip_reason is None for t in targets)


def test_the_report_lists_body_less_events_and_counts_the_cap_per_company() -> None:
    options = BuildOptions(AS_OF, "test", allow_unapproved=True)
    report = build_bundle(_fourteen_events(), options, PINNED_DIRS).report
    assert report["event_filings_without_body"] == {"count": 1, "ids": ["dart:202600000002"]}
    over = report["event_filings_over_cap"]
    assert over["cap"] == export.EVENT_CAP == 10
    assert over["count"] == 3 and over["by_company"] == {"dart:00126380": 3}


def test_excluded_and_outside_window_events_do_not_take_a_slot() -> None:
    excluded = [
        _event(f"2026{n:08d}", _day(n), category=None, excluded_reason="out_of_scope")
        for n in range(1, 4)
    ]
    old = _event("20240000000001", datetime.date(2024, 1, 1))
    real = [_event(f"2027{n:08d}", _day(50 + n)) for n in range(1, 6)]
    scope = event_scope(_data(*excluded, old, *real), AS_OF)
    assert len(scope.exported) == 5 and scope.capped == {}


def _notice(key: str, filed_on: datetime.date, **changes) -> EventRow:
    values = dict(
        report_nm="기업설명회(IR)개최(안내공시)", category="ir_event", body=None, rm="",
    )  # fmt: skip
    values.update(changes)
    body = values.pop("body")
    return _event(key, filed_on, body=body, **values)


def test_notices_are_listed_apart_never_capped_and_need_no_body() -> None:
    notices = [_notice(f"2028{n:08d}", _day(n)) for n in range(1, 15)]
    events = [_event(f"2027{n:08d}", _day(n * 3)) for n in range(1, 11)]
    scope = event_scope(_data(*notices, *events), AS_OF)
    assert [e.filing_key for e in scope.exported] == sorted(e.filing_key for e in events)
    assert [e.filing_key for e in scope.notices] == sorted(n.filing_key for n in notices)
    assert scope.capped == {} and scope.without_body == []


def test_notices_follow_the_window_and_the_shown_version_rule() -> None:
    old = _notice("20240000000001", datetime.date(2024, 1, 1))
    replaced = _notice("20280000000001", _day(40), rm="정", report_nm="주주총회소집결의",
                       category="meeting_notice")  # fmt: skip
    correction = _notice("20280000000002", _day(30), is_correction=True, chain_key=replaced.chain_key,
                         report_nm="[기재정정]주주총회소집결의", category="meeting_notice")  # fmt: skip
    scope = event_scope(_data(old, replaced, correction), AS_OF)
    assert [e.filing_key for e in scope.notices] == ["20280000000002"]
    assert scope.outside_window == 1 and scope.superseded == ["dart:20280000000001"]


def test_the_bundle_writes_notices_to_their_own_table_and_never_summarises_them() -> None:
    notices = [_notice(f"2028{n:08d}", _day(n)) for n in range(1, 4)]
    events = [_event(f"2027{n:08d}", _day(n * 3)) for n in range(1, 3)]
    data = dataclasses.replace(fixture_build_input(), events=tuple(notices + events))
    bundle = build_bundle(data, BuildOptions(AS_OF, "test", allow_unapproved=True), PINNED_DIRS)
    rows = bundle.rows["notices"]
    assert [r[0] for r in rows] == [f"dart:2028{n:08d}" for n in range(1, 4)]
    assert rows[0][1:] == (
        "dart:00126380", "ir_event", "기업설명회(IR)개최(안내공시)", _day(1).isoformat(),
        "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=202800000001", 0,
    )  # fmt: skip
    filing_ids = {r[0] for r in bundle.rows["filings"]}
    assert not filing_ids & {r[0] for r in rows}
    targets = {t.filing_id for t in select_targets(data, AS_OF)}
    assert not targets & {r[0] for r in rows}
    assert bundle.report["notices"] == {
        "count": 3, "by_company": {"dart:00126380": 3}, "by_category": {"ir_event": 3},
    }  # fmt: skip
