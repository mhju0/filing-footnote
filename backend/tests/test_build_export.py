"""M8 export and verification, offline: the fixture-seeded build data, no database."""

from __future__ import annotations

import ast
import dataclasses
import datetime
import functools
import hashlib
import json
import os
import random
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from app.build import export, verify
from app.build.bundle import SCHEMA, TABLES, canonical_dump_lines, content_sha256
from app.build.export import BuildOptions, build_bundle, run, write_bundle
from app.build.model import (
    CANONICAL_DECIMAL_RE,
    AnnualFilingRow,
    BuildError,
    BuildInput,
    ChunkRow,
    EventFactRow,
    FinancialRow,
    SummaryRow,
    annual_source_text,
    canonical_decimal,
    event_source_text,
    latest_annual_ids,
    require_canonical,
    summary_input_sha256,
)
from app.build.source import event_rows
from app.build.templates import event_template, template_input_sha256
from app.build.verify import PinnedResponses, VerifyError, check_bundle, link_problems
from app.filings.categories import load_contract as load_categories_contract
from app.llm.neutrality_guard import load_lexicon
from tests.build_seed import AS_OF, PINNED_BUILD, PINNED_DIRS, event_input, fixture_build_input

BUILD_DIR = Path(__file__).resolve().parents[1] / "app" / "build"
SAMSUNG_2025 = "20260310000123"


@pytest.fixture(autouse=True)
def _no_event_cap(monkeypatch) -> None:
    """These tests exercise chains, windows and facts over the whole seed; the per-company cap
    (D72) has its own tests in test_build_event_scope.py."""
    monkeypatch.setattr(export, "EVENT_CAP", 1000)


@pytest.fixture(scope="module")
def data() -> BuildInput:
    return fixture_build_input()


def _args(out: Path, *extra: str) -> list[str]:
    pinned = [arg for d in PINNED_DIRS for arg in ("--pinned", str(d))]
    return ["--as-of", AS_OF.isoformat(), "--out", str(out), "--source-revision", "test", *pinned,
            *extra]  # fmt: skip


def _export(data: BuildInput, out: Path, *extra: str) -> int:
    return run(_args(out, *extra), load=lambda _args: data)


def _fingerprint(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        return connection.execute("SELECT content_sha256 FROM build_meta").fetchone()[0]


def _rows(path: Path, query: str) -> list[tuple]:
    with sqlite3.connect(path) as connection:
        return connection.execute(query).fetchall()


def _event_id(event) -> str:
    return f"{event.regulator.lower()}:{event.filing_key}"


def _options(**changes) -> BuildOptions:
    return dataclasses.replace(BuildOptions(AS_OF, "test", allow_unapproved=True), **changes)


# Lines that pass the neutrality guard for either company.
NEUTRAL = {
    "ko": ("회사는 이 공시를 제출했다고 밝혔어요", "회사는 공시에 세부 내용을 적었어요",
           "회사는 공시 원문에 근거를 남겼다고 밝혔어요"),
    "en": ("The company said it filed this report.",
           "The company said the filing lists the details.",
           "The company said the source filing has the full text."),
}  # fmt: skip
RELEASE = ("--release", "--prompt-version", "v1")


# Text under every summary heading, so each event and annual section has source text.
SOURCE_CHUNKS = {
    "DART": (ChunkRow(10, "1. 사업의 개요", "사업 본문"),
             ChunkRow(11, "IV. 이사의 경영진단 및 분석의견", "경영 본문"),
             ChunkRow(12, "7. 투자위험요소", "위험 본문")),
    "SEC": (ChunkRow(10, "Item 1. Business", "Business text"),
            ChunkRow(11, "Item 7. Management's Discussion and Analysis", "MD&A text"),
            ChunkRow(12, "Item 1A. Risk Factors", "Risk text")),
}  # fmt: skip


def _with_sources(data: BuildInput) -> BuildInput:
    events = tuple(dataclasses.replace(e, body_text=e.body_text or f"본문 {e.filing_key}")
                   for e in data.events)  # fmt: skip
    annual = tuple(dataclasses.replace(f, chunks=f.chunks + SOURCE_CHUNKS[f.regulator])
                   for f in data.annual_filings)  # fmt: skip
    return dataclasses.replace(data, events=events, annual_filings=annual)


def _key(data: BuildInput, fid: str, section: str, prompt_version: str) -> str:
    """The current key, from the shared functions the summary build uses."""
    events = {_event_id(e): e for e in data.events}
    if fid in events:
        template = event_template(events[fid])
        if template is not None:  # a templated event's key is the template's (D77)
            return template_input_sha256(template, load_lexicon().version)
        source = event_source_text(events[fid])
    else:
        annual = next(f for f in data.annual_filings
                      if f"{f.regulator.lower()}:{f.filing_key}" == fid)  # fmt: skip
        source = annual_source_text(annual, section)
    assert source is not None
    return summary_input_sha256(source, export.DEFAULT_LLM_MODEL, section, prompt_version,
                                load_lexicon().version)  # fmt: skip


def _summary(data: BuildInput, fid: str, lang: str, section: str, prompt_version: str
             ) -> SummaryRow:  # fmt: skip
    lines = NEUTRAL[lang] if section == "summary" else (NEUTRAL[lang][0], None, None)
    return SummaryRow(fid, lang, section, *lines, "approved",
                      _key(data, fid, section, prompt_version))  # fmt: skip


def _all_approved(data: BuildInput, bundle, skip: frozenset[str] = frozenset(),
                  prompt_version: str = "v1") -> BuildInput:  # fmt: skip
    """Source text for every filing, and approved summaries keyed for ``prompt_version``."""
    sourced = _with_sources(data)
    summaries = [
        _summary(sourced, row[0], lang, section, prompt_version)
        for row in bundle.rows["filings"]
        if row[0] not in skip
        for lang in ("ko", "en")
        for section in export.SUMMARY_SECTIONS[row[2]]
    ]
    return dataclasses.replace(sourced, summaries=tuple(summaries))


def _exported_ids(data: BuildInput) -> set[str]:
    return {row[0] for row in build_bundle(data, _options(), PINNED_DIRS).rows["filings"]}


def _rehash(path: Path, *statements: str) -> None:
    """Edit a finished file and store a fingerprint that matches the edit."""
    with sqlite3.connect(path) as connection:
        for statement in statements:
            connection.execute(statement)
        connection.execute("UPDATE build_meta SET content_sha256 = ?",
                           (content_sha256(connection),))  # fmt: skip


# -- the file ------------------------------------------------------------------------------------


def test_export_writes_section_four_file_and_report(data, tmp_path, capsys) -> None:
    out = tmp_path / "dist" / "footnote.sqlite"
    assert _export(data, out, "--allow-unapproved") == 0
    printed = capsys.readouterr().out
    report = json.loads((tmp_path / "dist" / "footnote.report.json").read_text())

    assert f"content_sha256={_fingerprint(out)}" in printed
    assert report["file"]["size_bytes"] == out.stat().st_size
    assert f"size_bytes={out.stat().st_size}" in printed
    assert report["build_meta"]["allow_unapproved"] == 1 and report["mode"] == "development"
    assert _rows(out, "SELECT schema_version, data_as_of, source_revision, allow_unapproved "
                      "FROM build_meta") == [(2, "2026-11-17", "test", 1)]  # fmt: skip
    for table, count in report["row_counts"].items():
        assert _rows(out, f"SELECT count(*) FROM {table}") == [(count,)]
    assert report["row_counts"]["figures"] == len(report["figure_checks"]) > 0
    assert all(check["result"] == "match" for check in report["figure_checks"])

    figure = _rows(
        out,
        "SELECT value, unit, basis, regulator_tag, period_start, period_end, filing_id "
        "FROM figures WHERE id = 'dart:00126380|revenue|2024-12-31|consolidated'",
    )
    assert figure == [("258935494000000", "KRW", "consolidated", "ifrs-full_Revenue",
                       "2024-01-01", "2024-12-31", f"dart:{SAMSUNG_2025}")]  # fmt: skip
    assert _rows(out, "SELECT value FROM figures WHERE id LIKE 'sec:%|eps_diluted|%'") == [
        ("7.46",)
    ]
    assert _rows(
        out, "SELECT id, fiscal_year_end, currency, sort_order FROM companies ORDER BY sort_order"
    ) == [  # fmt: skip
        ("dart:00126380", "12-31", "KRW", 1),
        ("sec:0000320193", "09-27", "USD", 2),
    ]
    # check_bundle accepts the development file but a release check refuses it.
    assert check_bundle(out, release=False, pinned_dirs=PINNED_DIRS) == []
    assert "built with --allow-unapproved; a release refuses it" in check_bundle(
        out, release=True, pinned_dirs=PINNED_DIRS
    )


def test_two_exports_print_the_same_fingerprint(data, tmp_path, capsys) -> None:
    a, b = tmp_path / "a.sqlite", tmp_path / "b.sqlite"
    assert _export(data, a, "--allow-unapproved") == 0
    first = capsys.readouterr().out
    assert _export(data, b, "--allow-unapproved") == 0
    second = capsys.readouterr().out

    def sha(text: str) -> str:
        return next(line for line in text.splitlines() if line.startswith("content_sha256="))

    assert sha(first) == sha(second)
    assert a.read_bytes() == b.read_bytes()


def test_reordered_input_rows_give_the_same_fingerprint(data, tmp_path) -> None:
    rng = random.Random(8)

    def shuffled(rows: tuple) -> tuple:
        items = list(rows)
        rng.shuffle(items)
        return tuple(items)

    reordered = BuildInput(
        companies=shuffled(data.companies),
        annual_filings=shuffled(data.annual_filings),
        financials=shuffled(data.financials),
        events=shuffled(
            tuple(dataclasses.replace(e, facts=shuffled(e.facts)) for e in data.events)
        ),
    )
    assert [e.filing_key for e in reordered.events] != [e.filing_key for e in data.events]
    a, b = tmp_path / "a.sqlite", tmp_path / "b.sqlite"
    write_bundle(build_bundle(data, _options(), PINNED_DIRS), a)
    write_bundle(build_bundle(reordered, _options(), PINNED_DIRS), b)
    assert _fingerprint(a) == _fingerprint(b)
    assert a.read_bytes() == b.read_bytes()


def test_one_figure_changed_by_a_hundredth_changes_the_fingerprint(data, tmp_path) -> None:
    bundle = build_bundle(data, _options(), PINNED_DIRS)
    original = tmp_path / "a.sqlite"
    write_bundle(bundle, original)

    value = TABLES["figures"][0].index("value")
    figures = bundle.rows["figures"]
    row = figures[0]
    changed = canonical_decimal(Decimal(row[value]) + Decimal("0.01"))
    figures[0] = (*row[:value], changed, *row[value + 1 :])
    edited = tmp_path / "b.sqlite"
    write_bundle(bundle, edited)

    assert _fingerprint(original) != _fingerprint(edited)


# -- refusals ------------------------------------------------------------------------------------


def _no_outputs(directory: Path) -> bool:
    return not any(directory.iterdir())


def test_tampered_figure_exits_one_and_leaves_no_file(data, tmp_path, capsys) -> None:
    tampered = tuple(
        dataclasses.replace(row, value=row.value + 1)
        if row.regulator == "SEC" and row.metric == "revenue"
        else row
        for row in data.financials
    )
    assert tampered != data.financials
    out_dir = tmp_path / "dist"
    out_dir.mkdir()
    out = out_dir / "footnote.sqlite"

    code = _export(dataclasses.replace(data, financials=tampered), out, "--allow-unapproved")

    assert code == 1
    assert not out.exists() and _no_outputs(out_dir)
    error = capsys.readouterr().err
    assert "sec:0000320193|revenue|2025-09-27|consolidated" in error
    assert "416161000000" in error and "416161000001" in error


def test_tampered_event_fact_exits_one(data, tmp_path, capsys) -> None:
    def tamper(fact: EventFactRow) -> EventFactRow:
        if fact.key == "acquire_amount_common":
            return dataclasses.replace(fact, value_decimal=fact.value_decimal + Decimal("0.01"))
        return fact

    events = tuple(dataclasses.replace(e, facts=tuple(map(tamper, e.facts))) for e in data.events)
    out = tmp_path / "footnote.sqlite"
    assert _export(dataclasses.replace(data, events=events), out, "--allow-unapproved") == 1
    assert _no_outputs(tmp_path)
    assert "acquire_amount_common" in capsys.readouterr().err


def test_missing_pinned_response_fails_the_build(data, tmp_path) -> None:
    with pytest.raises(BuildError, match="no pinned response sec/companyfacts/CIK0000320193"):
        build_bundle(data, _options(), [PINNED_DIRS[1]])


@pytest.mark.parametrize("text", ["1.50", "01", "1e3", "1E+3", "-0", "1.", ".5", "+1", "1,000",
                                  " 1", "NaN", ""])  # fmt: skip
def test_non_canonical_decimal_is_rejected(text) -> None:
    with pytest.raises(ValueError, match="non-canonical"):
        require_canonical(text)


def test_canonical_decimal_form() -> None:
    assert canonical_decimal(Decimal("1000000.0000")) == "1000000"
    assert canonical_decimal(Decimal("1.50")) == "1.5"
    assert canonical_decimal(Decimal("1E+3")) == "1000"
    assert canonical_decimal(Decimal("-0.000")) == "0"
    assert canonical_decimal(Decimal("-0.010")) == "-0.01"
    with pytest.raises(ValueError):
        canonical_decimal(Decimal("NaN"))
    with pytest.raises(TypeError):
        canonical_decimal("1.5")


def test_non_canonical_figure_value_stops_the_write(data, tmp_path) -> None:
    bundle = build_bundle(data, _options(), PINNED_DIRS)
    value = TABLES["figures"][0].index("value")
    row = bundle.rows["figures"][0]
    bundle.rows["figures"][0] = (*row[:value], row[value] + ".0", *row[value + 1 :])
    with pytest.raises(BuildError, match="non-canonical"):
        write_bundle(bundle, tmp_path / "footnote.sqlite")
    assert _no_outputs(tmp_path)


@pytest.mark.parametrize(
    "url",
    [
        "https://dart.fss.or.kr.example.com/dsaf001/main.do",
        "http://dart.fss.or.kr/dsaf001/main.do?rcpNo=1",
        "https://example.com/?next=https://www.sec.gov/",
        "https://sec.gov/Archives/x.htm",
        "https://www.sec.gov:8443/Archives/x.htm",
        "https://user@www.sec.gov/Archives/x.htm",
        "",
    ],
)
def test_bad_link_host_is_rejected(url) -> None:
    assert link_problems(url)


def test_good_links_pass() -> None:
    assert link_problems("https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260310000123") == []
    assert link_problems("https://www.sec.gov/Archives/edgar/data/320193/x.htm") == []


def test_bad_link_host_fails_the_build(data, tmp_path, capsys) -> None:
    filings = tuple(
        dataclasses.replace(f, url="https://www.sec.gov.example.com/Archives/x.htm")
        if f.regulator == "SEC"
        else f
        for f in data.annual_filings
    )
    out = tmp_path / "footnote.sqlite"
    assert (
        _export(dataclasses.replace(data, annual_filings=filings), out, "--allow-unapproved") == 1
    )
    assert _no_outputs(tmp_path)
    assert "N5" in capsys.readouterr().err


def test_release_is_refused_without_approved_summaries(data, tmp_path, capsys) -> None:
    for extra in ((), ("--release",)):
        out = tmp_path / "footnote.sqlite"
        assert _export(data, out, *extra) == 1
        assert _no_outputs(tmp_path)
        assert "release build refused" in capsys.readouterr().err


def test_release_passes_when_every_filing_has_approved_summaries(data, tmp_path) -> None:
    approved = _all_approved(data, build_bundle(data, _options(), PINNED_DIRS))
    staged = SummaryRow(approved.summaries[0].filing_id, "ko", "summary", "x", None, None,
                        "staged", "0" * 64)  # fmt: skip
    with_staged = dataclasses.replace(
        approved, summaries=tuple(s for s in approved.summaries if s.section != "summary"
                                  or s.lang != "ko" or s.filing_id != staged.filing_id)
        + (staged,),
    )  # fmt: skip
    out = tmp_path / "footnote.sqlite"
    # One summary only staged: release refuses that filing.
    assert _export(with_staged, out) == 1 and _no_outputs(tmp_path)

    assert _export(approved, out, *RELEASE) == 0
    assert _rows(out, "SELECT allow_unapproved FROM build_meta") == [(0,)]
    assert _rows(out, "SELECT DISTINCT review_state FROM filing_summaries") == [("approved",)]
    assert check_bundle(out, release=True, pinned_dirs=PINNED_DIRS) == []


def test_development_build_never_writes_unapproved_summaries(data, tmp_path) -> None:
    fid = min(
        i for i in _exported_ids(data) if i.startswith("dart:2026") and i != f"dart:{SAMSUNG_2025}"
    )
    staged = SummaryRow(fid, "ko", "summary", "x", None, None, "staged", "0" * 64)
    bundle = build_bundle(dataclasses.replace(data, summaries=(staged,)), _options(), PINNED_DIRS)
    assert bundle.rows["filing_summaries"] == []
    assert bundle.report["summaries"]["not_approved_rows_skipped"] == 1


# -- selection rules -----------------------------------------------------------------------------


def test_excluded_and_superseded_filings_are_counted_not_exported(data, tmp_path) -> None:
    out = tmp_path / "footnote.sqlite"
    assert _export(data, out, "--allow-unapproved") == 0
    report = json.loads((tmp_path / "footnote.report.json").read_text())
    ids = {row[0] for row in _rows(out, "SELECT id FROM filings")}

    excluded = [e for e in data.events if e.excluded_reason]
    assert report["excluded_filings"]["count"] == len(excluded) > 0
    assert not ids & {_event_id(e) for e in excluded}
    # The originals of the two linked chains: Samsung's 2026-10-08 earnings filing (its saved
    # correction body names it) and Apple's 2026-04-20 8-K (8-K/A of 2026-09-01).
    assert report["superseded_filings"]["ids"] == [
        "dart:20261008800004", "sec:0001140361-26-015711",
    ]  # fmt: skip
    assert not ids & set(report["superseded_filings"]["ids"])
    corrected = _rows(out, "SELECT id FROM filings WHERE is_corrected = 1")
    assert {"dart:20261029800099", "sec:0001140361-26-035325"} <= {fid for (fid,) in corrected}
    assert all(
        next(e for e in data.events if _event_id(e) == fid).is_correction for (fid,) in corrected
    )


def test_event_outside_the_window_is_not_exported(data) -> None:
    exported = _exported_ids(data)
    old = dataclasses.replace(
        next(e for e in data.events if f"dart:{e.filing_key}" in exported and not e.facts),
        filing_key="20241231000001",
        chain_key="20241231000001",
        filed_on=datetime.date(2024, 12, 31),
    )
    bundle = build_bundle(dataclasses.replace(data, events=data.events + (old,)), _options(),
                          PINNED_DIRS)  # fmt: skip
    assert "dart:20241231000001" not in {row[0] for row in bundle.rows["filings"]}
    assert bundle.report["event_filings_outside_window"]["count"] == 1


def test_error_facts_are_counted_not_exported(data) -> None:
    exported = _exported_ids(data)
    target = next(e for e in data.events if f"dart:{e.filing_key}" in exported and e.facts)
    broken = EventFactRow("acquire_shares_other", "count", "shares", "aqpln_stk_estk", "1,2,3",
                          None, None, None, "unparseable count")  # fmt: skip
    events = tuple(
        dataclasses.replace(e, facts=e.facts + (broken,)) if e is target else e for e in data.events
    )
    bundle = build_bundle(dataclasses.replace(data, events=events), _options(), PINNED_DIRS)
    fid = f"dart:{target.filing_key}"
    keys = {row[2] for row in bundle.rows["filing_facts"] if row[0] == fid}
    assert "acquire_shares_other" not in keys
    assert bundle.report["fact_errors"] == {
        "count": 1,
        "facts": [
            {"filing_id": fid, "fact_key": "acquire_shares_other", "error": "unparseable count"}
        ],  # fmt: skip
    }


def test_fact_kinds_map_to_section_four_value_kinds(data) -> None:
    bundle = build_bundle(data, _options(), PINNED_DIRS)
    kinds = {row[3] for row in bundle.rows["filing_facts"]}
    assert kinds == {"shares", "amount", "ratio", "date", "text"}
    shares = next(r for r in bundle.rows["filing_facts"] if r[2] == "acquire_shares_common")
    assert shares[3:] == ("shares", "18000000", "shares", "opendart:tsstkAqDecsn.aqpln_stk_ostk")


def test_newer_filing_wins_and_an_earlier_different_value_is_restated(data) -> None:
    older = AnnualFilingRow("DART", "20250311000001", "00126380", "business_report",
                            "사업보고서 (2024.12)", "2024-annual", datetime.date(2025, 3, 11),
                            "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250311000001",
                            "0" * 64)  # fmt: skip
    own = FinancialRow("DART", older.filing_key, "00126380", "revenue", "2024-annual",
                       "duration", 2024, None, None, Decimal("258935000000000"), "KRW", "KRW")  # fmt: skip
    changed = dataclasses.replace(
        data, annual_filings=data.annual_filings + (older,), financials=data.financials + (own,)
    )
    bundle = build_bundle(changed, _options(), PINNED_DIRS)
    figure = next(
        r for r in bundle.rows["figures"] if r[0].startswith("dart:00126380|revenue|2024")
    )
    assert figure[2] == f"dart:{SAMSUNG_2025}"
    assert figure[7] == "258935494000000" and figure[11] == 1


# -- exact decimals and schema -------------------------------------------------------------------


def test_build_package_has_no_float_and_no_real_column() -> None:
    offenders = []
    for path in sorted(BUILD_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, float):
                offenders.append(f"{path.name}:{node.lineno} float literal")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "float"
            ):
                offenders.append(f"{path.name}:{node.lineno} float() call")
            if isinstance(node, ast.Name) and node.id == "float":
                offenders.append(f"{path.name}:{node.lineno} float name")
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and any(word in node.value.upper().split() for word in ("REAL", "REAL,", "FLOAT",
                                                                        "DOUBLE"))
            ):  # fmt: skip
                offenders.append(f"{path.name}:{node.lineno} REAL/FLOAT/DOUBLE in a string")
    assert len(list(BUILD_DIR.glob("*.py"))) >= 5
    assert offenders == []


def test_every_table_is_strict_with_text_or_integer_columns(data, tmp_path) -> None:
    out = tmp_path / "footnote.sqlite"
    write_bundle(build_bundle(data, _options(), PINNED_DIRS), out)
    tables = _rows(out, "SELECT name, sql FROM sqlite_master WHERE type = 'table'")
    assert {name for name, _ in tables} == set(TABLES) | {"build_meta"}
    assert all(sql.rstrip().endswith("STRICT") for _, sql in tables)
    for name, _ in tables:
        for column in _rows(out, f"PRAGMA table_info({name})"):
            assert column[2] in ("TEXT", "INTEGER"), (name, column)


def test_verify_detects_a_file_edited_after_the_build(data, tmp_path) -> None:
    out = tmp_path / "footnote.sqlite"
    write_bundle(build_bundle(data, _options(), PINNED_DIRS), out)
    with sqlite3.connect(out) as connection:
        connection.execute("UPDATE figures SET value = '1' WHERE id LIKE 'sec:%|revenue|%'")
    assert "content_sha256 does not match the file's contents" in check_bundle(
        out, release=False, pinned_dirs=PINNED_DIRS
    )


# -- review fixes --------------------------------------------------------------------------------

SEC_REVENUE = "sec:0000320193|revenue|2025-09-27|consolidated"


def _pinned_args(*dirs: Path) -> list[str]:
    return [arg for d in (*dirs, *PINNED_DIRS) for arg in ("--pinned", str(d))]


def _dart_pinned(directory: Path, year: int, rcept_no: str,
                 rows: list[tuple[str, str, str]]) -> Path:  # fmt: skip
    """A synthetic fnlttSinglAcntAll response: (account_id, thstrm_amount, frmtrm_amount)."""
    path = directory / "dart" / "fnlttSinglAcntAll" / f"00126380_{year}_11011_CFS.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    items = [
        {"rcept_no": rcept_no, "reprt_code": "11011", "bsns_year": str(year),
         "corp_code": "00126380", "sj_div": "IS", "sj_nm": "손익계산서", "account_id": account,
         "account_nm": "영업수익", "thstrm_amount": this, "frmtrm_amount": prior,
         "ord": str(order), "currency": "KRW"}
        for order, (account, this, prior) in enumerate(rows, start=1)
    ]  # fmt: skip
    path.write_text(json.dumps({"status": "000", "message": "정상", "list": items}),
                    encoding="utf-8")  # fmt: skip
    return directory


def _dart_annual(key: str, filed_on: datetime.date, year: int, title: str | None = None):
    return AnnualFilingRow("DART", key, "00126380", "business_report",
                           title or f"사업보고서 ({year}.12)", f"{year}-annual", filed_on,
                           f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={key}", "0" * 64)  # fmt: skip


def _dart_revenue(key: str, year: int, value: str) -> FinancialRow:
    return FinancialRow("DART", key, "00126380", "revenue", f"{year}-annual", "duration", year,
                        None, None, Decimal(value), "KRW", "KRW")  # fmt: skip


def _with_annual(data: BuildInput, filings, financials) -> BuildInput:
    return dataclasses.replace(data, annual_filings=data.annual_filings + tuple(filings),
                               financials=data.financials + tuple(financials))  # fmt: skip


def _figure(bundle, prefix: str) -> tuple:
    return next(r for r in bundle.rows["figures"] if r[0].startswith(prefix))


# item 1: release verify trusts nothing in build_meta but the fingerprint


def test_release_verify_rejects_the_edited_development_file(data, tmp_path) -> None:
    out = tmp_path / "footnote.sqlite"
    assert _export(data, out, "--allow-unapproved", "--prompt-version", "none") == 0
    _rehash(out, "UPDATE build_meta SET allow_unapproved = 0",
            f"UPDATE figures SET value = '999' WHERE id = '{SEC_REVENUE}'")  # fmt: skip

    problems = check_bundle(out, release=True, pinned_dirs=PINNED_DIRS)
    assert "content_sha256 does not match the file's contents" not in problems
    assert "built with --allow-unapproved; a release refuses it" not in problems
    assert (f"{SEC_REVENUE}: sec/companyfacts/CIK0000320193.json: revenue is 416161000000, "
            "stored 999") in problems  # fmt: skip
    assert (f"dart:{SAMSUNG_2025}: no approved summary ko/one_line, ko/business, ko/changes, "
            "en/one_line, en/business, en/changes") in problems  # fmt: skip
    assert "prompt_version is 'none'; a release refuses it" in problems
    assert verify.main([str(out), "--release", *_pinned_args()]) == 1


def test_release_verify_runs_the_neutrality_guard_and_coverage(data, tmp_path) -> None:
    approved = _all_approved(data, build_bundle(data, _options(), PINNED_DIRS))
    out = tmp_path / "footnote.sqlite"
    assert _export(approved, out, *RELEASE) == 0
    assert verify.main([str(out), "--release", *_pinned_args()]) == 0
    event = _rows(out, "SELECT filing_id FROM filing_summaries WHERE section = 'summary' "
                       "ORDER BY filing_id LIMIT 1")[0][0]  # fmt: skip
    _rehash(out, "UPDATE filing_summaries SET line1 = 'The company said revenue soared.' "
                 f"WHERE filing_id = '{event}' AND lang = 'en'",
            f"DELETE FROM filing_summaries WHERE filing_id = 'dart:{SAMSUNG_2025}' "
            "AND lang = 'ko' AND section = 'business'")  # fmt: skip
    problems = check_bundle(out, release=True, pinned_dirs=PINNED_DIRS)
    assert f"{event} summary en/summary: N2 on line 1 'soared'" in problems
    assert f"dart:{SAMSUNG_2025}: no approved summary ko/business" in problems


def test_release_export_runs_the_neutrality_guard(data, tmp_path, capsys) -> None:
    approved = _all_approved(data, build_bundle(data, _options(), PINNED_DIRS))
    target = next(s for s in approved.summaries if s.lang == "en" and s.section == "summary")
    summaries = tuple(
        dataclasses.replace(s, line1="The company said revenue soared.") if s is target else s
        for s in approved.summaries
    )
    out = tmp_path / "footnote.sqlite"
    assert _export(dataclasses.replace(approved, summaries=summaries), out, *RELEASE) == 1
    assert "N2 on line 1 'soared'" in capsys.readouterr().err and _no_outputs(tmp_path)


# item 2: a finished file is re-read against the pinned responses


def test_verify_rereads_figures_and_facts_from_the_pinned_responses(data, tmp_path) -> None:
    out = tmp_path / "footnote.sqlite"
    write_bundle(build_bundle(data, _options(), PINNED_DIRS), out)
    _rehash(out, f"UPDATE figures SET value = '999' WHERE id = '{SEC_REVENUE}'",
            "UPDATE figures SET regulator_tag = 'x' WHERE id LIKE 'dart:%|revenue|2025%'",
            "UPDATE filing_facts SET value_text = '18000001' "
            "WHERE fact_key = 'acquire_shares_common' AND filing_id = 'dart:20260821000616'")  # fmt: skip
    problems = check_bundle(out, release=False, pinned_dirs=PINNED_DIRS)
    assert any(p.startswith(f"{SEC_REVENUE}: ") and "stored 999" in p for p in problems)
    assert any("|revenue|2025-12-31|" in p and "regulator_tag 'x'" in p for p in problems)
    assert any(p.startswith("dart:20260821000616#") and "18000001" in p for p in problems)
    assert len(problems) == 3


# item 3: a failed build never leaves a stale or half-finished result


def test_report_rename_failure_leaves_no_outputs(data, tmp_path, monkeypatch) -> None:
    out = tmp_path / "footnote.sqlite"
    assert _export(data, out, "--allow-unapproved") == 0  # an earlier good build
    real_replace = os.replace

    def replace(src, dst):
        if Path(dst).name == "footnote.report.json":
            raise OSError("disk full")
        return real_replace(src, dst)

    monkeypatch.setattr(export.os, "replace", replace)
    with pytest.raises(OSError, match="disk full"):
        _export(data, out, "--allow-unapproved")
    assert _no_outputs(tmp_path)


def test_write_bundle_rename_failure_leaves_no_outputs(data, tmp_path, monkeypatch) -> None:
    bundle = build_bundle(data, _options(), PINNED_DIRS)
    out = tmp_path / "footnote.sqlite"
    write_bundle(bundle, out)  # an earlier good build
    real_replace = os.replace

    def replace(src, dst):
        if Path(dst).name == "footnote.report.json":
            raise OSError("disk full")
        return real_replace(src, dst)

    monkeypatch.setattr(export.os, "replace", replace)
    with pytest.raises(OSError, match="disk full"):
        write_bundle(bundle, out)
    assert _no_outputs(tmp_path)


def test_failed_build_removes_an_earlier_good_build(data, tmp_path, capsys) -> None:
    out = tmp_path / "footnote.sqlite"
    assert _export(data, out, "--allow-unapproved") == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["footnote.report.json",
                                                          "footnote.sqlite"]  # fmt: skip
    tampered = tuple(dataclasses.replace(r, value=r.value + 1) if r.regulator == "SEC" else r
                     for r in data.financials)  # fmt: skip
    assert _export(dataclasses.replace(data, financials=tampered), out, "--allow-unapproved") == 1
    assert _no_outputs(tmp_path)
    assert "no bundle or report left" in capsys.readouterr().err


# item 4: the shown version is computed as of --as-of


@functools.cache
def _seed_events() -> tuple[list[dict], dict[str, list[EventFactRow]]]:
    return event_input()


def _with_rows(data: BuildInput, **changes: dict) -> BuildInput:
    """``data`` with its events rebuilt through the adapter after changing stored columns of
    the rows named by key (``rcept_no``)."""
    rows, facts = _seed_events()
    changed = [{**row, **changes.get(row["rcept_no"], {})} for row in rows]
    return dataclasses.replace(data, events=tuple(event_rows(changed, facts)))


def _unlinked_stating(first: datetime.date) -> dict:
    return {"correction_link": "unlinked", "correction_first_filed_at": first}


def _filing_ids(data: BuildInput, as_of: datetime.date = AS_OF) -> set[str]:
    return {
        row[0] for row in build_bundle(data, _options(as_of=as_of), PINNED_DIRS).rows["filings"]
    }


def test_as_of_between_a_filing_and_its_replacing_correction_shows_the_filing(data) -> None:
    replaced = "dart:20260407800002"  # rm 유정; its correction was filed 2026-04-30
    # The correction could not be linked but its body names the 2026-04-07 filing: an orphan.
    orphan = _with_rows(data, **{"20260430800097": _unlinked_stating(datetime.date(2026, 4, 7))})
    assert replaced in _filing_ids(orphan, datetime.date(2026, 4, 20))
    after = build_bundle(orphan, _options(as_of=datetime.date(2026, 5, 1)), PINNED_DIRS)
    assert replaced not in {row[0] for row in after.rows["filings"]}
    assert replaced in after.report["superseded_filings"]["ids"]
    assert "dart:20260430800097" in {row[0] for row in after.rows["filings"]}


def test_a_later_correction_of_a_different_same_name_filing_does_not_hide_a_filing(data) -> None:
    # 2026-01-08 and 2026-04-07 are two different filings of the same report name, both rm 정.
    # As of 2026-05-01 the correction of 2026-04-30 (naming 2026-01-08) is filed; the one of
    # 2026-07-30 that names 2026-04-07 is not yet, so 2026-04-07 is still the shown version.
    unrelated = _with_rows(
        data,
        **{"20260430800097": _unlinked_stating(datetime.date(2026, 1, 8)),
           "20260730800103": _unlinked_stating(datetime.date(2026, 4, 7))},
    )  # fmt: skip
    ids = _filing_ids(unrelated, datetime.date(2026, 5, 1))
    assert "dart:20260407800002" in ids
    assert "dart:20260108800001" not in ids


def test_an_orphan_correction_of_another_subsidiary_flag_does_not_hide_a_filing(data) -> None:
    other = {**_unlinked_stating(datetime.date(2026, 4, 7)), "subsidiary": True}
    changed = _with_rows(
        data,
        **{"20260430800097": other, "20260730800103": _unlinked_stating(datetime.date(2026, 4, 7))},
    )
    assert "dart:20260407800002" in _filing_ids(changed, datetime.date(2026, 5, 1))


UNRESOLVED = ["dart:20260108800001", "dart:20260407800002", "dart:20260707800004"]
# Since D76: an outlook filing and two notices marked 정, whose corrections are stored
# unchained (the outlook correction's body names no first filing date; notices are never
# chained). Each correction is the version shown.
UNRESOLVED_D76 = ["dart:20260212801353", "dart:20260213800423", "dart:20260629801143"]


def test_a_filing_marked_jeong_without_a_resolvable_correction_is_hidden_as_unresolved(
    data,
) -> None:
    # Samsung's earnings filings marked 정 whose corrections' bodies name no first filing date.
    for as_of in (AS_OF, datetime.date(2026, 7, 10)):
        bundle = build_bundle(data, _options(as_of=as_of), PINNED_DIRS)
        ids = {row[0] for row in bundle.rows["filings"]}
        assert not ids & set(UNRESOLVED + UNRESOLVED_D76)
        assert not {row[0] for row in bundle.rows["notices"]} & set(UNRESOLVED_D76)
        assert bundle.report["superseded_unresolved"] == {
            "count": 6, "ids": sorted(UNRESOLVED + UNRESOLVED_D76),
        }  # fmt: skip
        assert not set(UNRESOLVED) & set(bundle.report["superseded_filings"]["ids"])
    # Their DART-filed corrections are the one version shown.
    assert {"dart:20260129800008", "dart:20260430800097", "dart:20260730800103"} <= _filing_ids(
        data
    )


@pytest.mark.parametrize(
    "as_of",
    [datetime.date(2026, 4, 20), datetime.date(2026, 5, 1), datetime.date(2026, 8, 31), AS_OF],
)
def test_at_most_one_version_per_chain_is_exported(data, as_of) -> None:
    variants = (
        data,
        _with_rows(data, **{"20260430800097": _unlinked_stating(datetime.date(2026, 4, 7))}),
    )
    for variant in variants:
        bundle = build_bundle(variant, _options(as_of=as_of), PINNED_DIRS)
        events = [
            {_event_id(e): e for e in variant.events}[row[0]]
            for row in bundle.rows["filings"]
            if row[2] == "event"
        ]
        chains = [e.chain_key for e in events]
        assert len(chains) == len(set(chains))
        for jeong in (e for e in events if "정" in e.rm):
            # An exported 정 filing has a resolved correction, filed after as-of, so not exported.
            assert jeong.target_key is not None
            assert any(
                other.is_correction
                and other.target_key == jeong.target_key
                and other.filed_on > as_of
                for other in variant.events
            )
            assert not any(
                other.is_correction
                and other.target_key == jeong.target_key
                and (other.filed_on, other.filing_key) > (jeong.filed_on, jeong.filing_key)
                for other in events
            )


def test_dart_orphans_with_the_same_target_share_a_chain(data) -> None:
    first = _unlinked_stating(datetime.date(2026, 1, 8))
    events = _with_rows(data, **{"20260129800008": first, "20260430800097": first}).events
    by = {e.filing_key: e for e in events}
    assert by["20260129800008"].chain_key == by["20260430800097"].chain_key
    assert by["20260129800008"].target_key == by["20260108800001"].target_key
    ids = _filing_ids(dataclasses.replace(data, events=events))
    assert "dart:20260430800097" in ids and "dart:20260129800008" not in ids


def test_linked_chain_shows_the_newest_member_filed_by_as_of(data) -> None:
    template = next(e for e in data.events if e.category == "leadership")
    original = dataclasses.replace(
        template, filing_key="20260501000001", chain_key="20260501000001", rm="유정",
        filed_on=datetime.date(2026, 5, 1), is_correction=False, facts=(),
        url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260501000001",
    )  # fmt: skip
    correction = dataclasses.replace(
        original, filing_key="20260510000001", rm="유", is_correction=True,
        filed_on=datetime.date(2026, 5, 10), report_nm=f"[기재정정]{original.report_nm}",
        url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260510000001",
    )  # fmt: skip
    chained = dataclasses.replace(data, events=data.events + (original, correction))

    def filings(as_of: datetime.date) -> dict[str, tuple]:
        bundle = build_bundle(chained, _options(as_of=as_of), PINNED_DIRS)
        return {row[0]: row for row in bundle.rows["filings"]}

    # Between the two: the original shows although its rm already carries 정.
    early = filings(datetime.date(2026, 5, 5))
    assert early["dart:20260501000001"][10] == 0 and "dart:20260510000001" not in early
    late = filings(AS_OF)
    assert "dart:20260501000001" not in late
    assert late["dart:20260510000001"][10] == 1
    assert late["dart:20260510000001"][4] == original.report_nm


# M4: SEC 8-K rows through the adapter

AMENDMENT = "sec:0001140361-26-035325"  # 8-K/A of 2026-09-01, linked to the 8-K below
AMENDED = "sec:0001140361-26-015711"  # 8-K of 2026-04-20, event date 2026-04-17, item 5.02
APPLE = "sec:0000320193"


def test_sec_event_rows_map_to_section_four_columns(data) -> None:
    bundle = build_bundle(data, _options(), PINNED_DIRS)
    filings = {row[0]: row for row in bundle.rows["filings"]}
    row = filings[AMENDMENT]
    assert row[1:7] == (APPLE, "event", "leadership", "8-K/A", "5.02", "8-K/A")
    assert row[9] == ("https://www.sec.gov/Archives/edgar/data/320193/000114036126035325/"
                      "0001140361-26-035325-index.html") and row[10] == 1  # fmt: skip
    assert filings["sec:0000320193-26-000024"][4:6] == ("8-K", "2.02,9.01")
    assert not any(fid.startswith("sec:sec:") for fid in filings)
    assert APPLE in {row[0] for row in bundle.rows["companies"]}
    facts = [r[2:] for r in bundle.rows["filing_facts"] if r[0] == AMENDMENT]
    assert facts == [
        ("items", "text", "5.02", None, "sec:submissions.items"),
        ("report_date", "date", "2026-04-17", None, "sec:submissions.reportDate"),
    ]
    checked = {c["pinned"] for c in bundle.report["fact_checks"] if c["filing_id"] == AMENDMENT}
    assert checked == {"sec/submissions/CIK0000320193.json"}


def test_sec_row_key_without_its_prefix_is_refused() -> None:
    rows, facts = _seed_events()
    row = next(r for r in rows if r["rcept_no"] == AMENDMENT)
    with pytest.raises(ValueError, match="lacks the 'sec:' prefix"):
        event_rows([{**row, "rcept_no": AMENDMENT.removeprefix("sec:")}], facts)


def test_an_8k_amendment_replaces_its_original_from_its_filing_date(data) -> None:
    before = _filing_ids(data, datetime.date(2026, 8, 31))
    assert AMENDED in before and AMENDMENT not in before
    after = _filing_ids(data, datetime.date(2026, 9, 1))
    assert AMENDMENT in after and AMENDED not in after


def test_unlinked_8k_amendments_group_by_cik_event_date_and_a_shared_item(data) -> None:
    rows, facts = _seed_events()
    amendment = next(r for r in rows if r["rcept_no"] == AMENDMENT)
    later = "sec:0001140361-26-099999"

    def copy(key: str, items: str, cik: str = "0000320193") -> tuple[dict, list[EventFactRow]]:
        fact_rows = [dataclasses.replace(f, value_text=items) if f.key == "items" else f
                     for f in facts[AMENDMENT]]  # fmt: skip
        return {**amendment, "rcept_no": key, "corp_code": cik, "filed_at":
                datetime.date(2026, 10, 1), "correction_link": "unlinked",
                "original_rcept_no": None}, fact_rows  # fmt: skip

    unlinked = {**amendment, "correction_link": "unlinked", "original_rcept_no": None}
    shared, shared_facts = copy(later, "5.02,9.01")
    other_item, other_item_facts = copy("sec:0001140361-26-099998", "1.01,9.01")
    other_cik, other_cik_facts = copy("sec:0001140361-26-099997", "5.02", "0000000001")
    events = event_rows(
        [unlinked, shared, other_item, other_cik],
        {AMENDMENT: facts[AMENDMENT], later: shared_facts, other_item["rcept_no"]: other_item_facts,
         other_cik["rcept_no"]: other_cik_facts},
    )  # fmt: skip
    chain = {e.filing_key: e.chain_key for e in events}
    assert chain["0001140361-26-035325"] == chain["0001140361-26-099999"]
    assert len(set(chain.values())) == 3
    # The original 8-K is not in that chain, so it is shown again.
    unlinked_data = _with_rows(data, **{AMENDMENT: {"correction_link": "unlinked",
                                                    "original_rcept_no": None}})  # fmt: skip
    assert {AMENDED, AMENDMENT} <= _filing_ids(unlinked_data)


def test_tampered_sec_fact_fails_the_build(data) -> None:
    def tamper(fact: EventFactRow) -> EventFactRow:
        return dataclasses.replace(fact, value_text="5.03") if fact.key == "items" else fact

    events = tuple(
        dataclasses.replace(e, facts=tuple(map(tamper, e.facts)))
        if _event_id(e) == AMENDMENT else e
        for e in data.events
    )  # fmt: skip
    with pytest.raises(BuildError, match="0001140361-26-035325 items is 5.02, not 5.03"):
        build_bundle(dataclasses.replace(data, events=events), _options(), PINNED_DIRS)


def test_verify_rereads_sec_facts_from_the_pinned_submissions(data, tmp_path) -> None:
    out = tmp_path / "footnote.sqlite"
    write_bundle(build_bundle(data, _options(), PINNED_DIRS), out)
    assert check_bundle(out, release=False, pinned_dirs=PINNED_DIRS) == []
    _rehash(out, "UPDATE filing_facts SET value_text = '2026-04-18' "
                 f"WHERE fact_key = 'report_date' AND filing_id = '{AMENDMENT}'")  # fmt: skip
    problems = check_bundle(out, release=False, pinned_dirs=PINNED_DIRS)
    assert len(problems) == 1 and problems[0].startswith(f"{AMENDMENT}#")
    assert "report_date is 2026-04-17, not 2026-04-18" in problems[0]


def test_event_source_hash_covers_the_stored_body_when_there_is_one(data) -> None:
    as_of = datetime.date(2026, 5, 1)  # the 8-K with a stored body is shown

    def source_hash(changed: BuildInput, fid: str) -> str:
        rows = build_bundle(changed, _options(as_of=as_of), PINNED_DIRS).rows["filings"]
        return next(row[11] for row in rows if row[0] == fid)

    base = source_hash(data, AMENDED)
    body = next(e for e in data.events if _event_id(e) == AMENDED).body_text
    assert body
    expected = hashlib.sha256(json.dumps(
        {"body_text": body, "facts": sorted([f.key, f.source_field, f.raw]
                                            for f in _seed_events()[1][AMENDED])},
        sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()  # fmt: skip
    assert base == expected
    assert source_hash(_with_rows(data, **{AMENDED: {"body_text": body + " "}}), AMENDED) != base
    # The list row is not hashed when a body is stored.
    assert source_hash(_with_rows(data, **{AMENDED: {"rm": "x"}}), AMENDED) == base
    # A DART row the ingest stored a body for hashes the body, not the list row.
    dart = "dart:20260430800097"
    dart_body = next(e for e in data.events if _event_id(e) == dart).body_text
    assert dart_body
    with_body = source_hash(data, dart)
    assert source_hash(_with_rows(data, **{"20260430800097": {"rm": ""}}), dart) == with_body
    assert source_hash(
        _with_rows(data, **{"20260430800097": {"body_text": dart_body + " "}}), dart
    ) != with_body
    # A DART row without a stored body is not exported at all (D72).
    no_body = _with_rows(data, **{"20260430800097": {"body_text": None}})
    assert dart not in _filing_ids(no_body)


# item 5: annual scope


def test_older_annual_filing_is_exported_as_a_figure_source_without_summaries(
    data, tmp_path
) -> None:
    older = "20250311000001"
    pinned = _dart_pinned(tmp_path / "pinned", 2024, older,
                          [("ifrs-full_Revenue", "258935000000000", "250000000000000")])  # fmt: skip
    changed = _with_annual(data, [_dart_annual(older, datetime.date(2025, 3, 11), 2024)],
                           [_dart_revenue(older, 2024, "258935000000000"),
                            _dart_revenue(older, 2023, "250000000000000")])  # fmt: skip
    dirs = (pinned, *PINNED_DIRS)
    bundle = build_bundle(changed, _options(), dirs)
    filings = {row[0]: row for row in bundle.rows["filings"]}
    assert filings[f"dart:{older}"][2] == "annual" and filings[f"dart:{older}"][8] == "FY2024"
    assert _figure(bundle, "dart:00126380|revenue|2023")[2] == f"dart:{older}"
    assert _figure(bundle, "dart:00126380|revenue|2024")[2] == f"dart:{SAMSUNG_2025}"
    assert f"dart:{older}" not in bundle.report["summaries"]["filings_without_approved_summaries"]

    out = tmp_path / "out" / "footnote.sqlite"
    no_older = _all_approved(changed, bundle, skip=frozenset({f"dart:{older}"}))
    argv = ["--as-of", AS_OF.isoformat(), "--out", str(out), "--source-revision", "test",
            *_pinned_args(pinned), *RELEASE]  # fmt: skip
    assert run(argv, load=lambda _args: no_older) == 0
    assert check_bundle(out, release=True, pinned_dirs=dirs) == []
    no_latest = _all_approved(changed, bundle, skip=frozenset({f"dart:{SAMSUNG_2025}"}))
    with pytest.raises(BuildError, match=f"dart:{SAMSUNG_2025}"):
        build_bundle(no_latest, _options(allow_unapproved=False, prompt_version="v1"), dirs)


def test_annual_filing_that_is_no_figure_source_is_not_exported(data) -> None:
    older = "20250311000001"
    changed = _with_annual(data, [_dart_annual(older, datetime.date(2025, 3, 11), 2024)],
                           [_dart_revenue(older, 2024, "258935000000000")])  # fmt: skip
    bundle = build_bundle(changed, _options(), PINNED_DIRS)
    assert f"dart:{older}" not in {row[0] for row in bundle.rows["filings"]}
    assert bundle.report["annual_filings_without_figures"]["ids"] == [f"dart:{older}"]


def test_annual_correction_replaces_its_original(data, tmp_path) -> None:
    corrected = "20260320000001"
    source = PINNED_BUILD / "dart" / "fnlttSinglAcntAll" / "00126380_2025_11011_CFS.json"
    target = tmp_path / "dart" / "fnlttSinglAcntAll" / source.name
    target.parent.mkdir(parents=True)
    target.write_text(source.read_text(encoding="utf-8").replace(SAMSUNG_2025, corrected)
                      .replace("300870903000000", "300870903000001"), encoding="utf-8")  # fmt: skip

    def copy(row: FinancialRow) -> FinancialRow:
        current_revenue = row.metric == "revenue" and row.fiscal_year == 2025
        return dataclasses.replace(
            row, filing_key=corrected,
            value=Decimal("300870903000001") if current_revenue else row.value,
        )  # fmt: skip

    copies = [copy(r) for r in data.financials if r.filing_key == SAMSUNG_2025]
    title = "[기재정정]사업보고서 (2025.12)"
    changed = _with_annual(
        data, [_dart_annual(corrected, datetime.date(2026, 3, 20), 2025, title)], copies
    )
    bundle = build_bundle(changed, _options(), (tmp_path, *PINNED_DIRS))
    filings = {row[0]: row for row in bundle.rows["filings"]}
    assert f"dart:{SAMSUNG_2025}" not in filings
    assert filings[f"dart:{corrected}"][10] == 1 and filings[f"dart:{corrected}"][4] == "사업보고서"
    assert bundle.report["annual_versions_replaced"]["ids"] == [f"dart:{SAMSUNG_2025}"]
    revenue = _figure(bundle, "dart:00126380|revenue|2025")
    assert revenue[2] == f"dart:{corrected}" and revenue[7] == "300870903000001"
    assert revenue[11] == 0  # the replaced version's value is not a restatement
    dart_sources = {r[2] for r in bundle.rows["figures"] if r[0].startswith("dart:")}
    assert dart_sources == {f"dart:{corrected}"}


def test_latest_annual_is_by_period_then_filing_date_then_id() -> None:
    rows = [("a", "c1", "FY2024", "2025-03-01"), ("b", "c1", "FY2025", "2026-03-01"),
            ("c", "c2", "FY2025", "2026-03-01"), ("d", "c2", "FY2025", "2026-03-01"),
            ("e", "c3", "FY2023", "2026-05-01"), ("f", "c3", "FY2024", "2025-03-01")]  # fmt: skip
    assert latest_annual_ids(rows) == {"b", "d", "f"}


# item 6: the annual category is in the contract and never assigned by the classifier


def test_annual_is_a_non_event_category_of_the_contract() -> None:
    contract = load_categories_contract()
    annual = [c for c in contract["non_event_categories"] if c["key"] == export.ANNUAL_CATEGORY]
    assert annual and annual[0]["ko"] == "사업보고서" and annual[0]["en"] == "Annual report"
    assert annual[0]["assigned_by_classifier"] is False
    assert export.ANNUAL_CATEGORY not in {c["key"] for c in contract["categories"]}


# item 7: rows are inserted in primary-key order


def test_rows_are_inserted_in_primary_key_order(data, tmp_path) -> None:
    approved = _all_approved(data, build_bundle(data, _options(), PINNED_DIRS),
                             prompt_version="none")
    out = tmp_path / "footnote.sqlite"
    write_bundle(build_bundle(approved, _options(prompt_version="none"), PINNED_DIRS), out)
    for table, (_, key) in TABLES.items():
        columns = ", ".join(key)
        by_rowid = _rows(out, f"SELECT {columns} FROM {table} ORDER BY rowid")
        assert by_rowid == sorted(by_rowid), table
        assert table == "glossary" or by_rowid, table


# item 8: is_restated


def test_equal_values_from_two_filings_are_not_restated(data) -> None:
    older = "20250311000001"
    changed = _with_annual(data, [_dart_annual(older, datetime.date(2025, 3, 11), 2024)],
                           [_dart_revenue(older, 2024, "258935494000000.00")])  # fmt: skip
    figure = _figure(build_bundle(changed, _options(), PINNED_DIRS), "dart:00126380|revenue|2024")
    assert figure[2] == f"dart:{SAMSUNG_2025}" and figure[11] == 0


@pytest.mark.parametrize("key, wins", [("20260310000999", True), ("20260310000001", False)])
def test_same_date_tie_is_broken_by_filing_id(data, tmp_path, key, wins) -> None:
    pinned = _dart_pinned(tmp_path, 2024, key, [("ifrs-full_Revenue", "258935000000000", "")])
    changed = _with_annual(data, [_dart_annual(key, datetime.date(2026, 3, 10), 2024)],
                           [_dart_revenue(key, 2024, "258935000000000")])  # fmt: skip
    bundle = build_bundle(changed, _options(), (pinned, *PINNED_DIRS))
    figure = _figure(bundle, "dart:00126380|revenue|2024")
    assert figure[2] == (f"dart:{key}" if wins else f"dart:{SAMSUNG_2025}")
    assert figure[7] == ("258935000000000" if wins else "258935494000000")
    assert figure[11] == 1


# items 9 and 10: canonical decimals are exact and ASCII


def test_canonical_decimal_never_rounds() -> None:
    long = "1" + "0" * 70 + "1"
    assert canonical_decimal(Decimal(long)) == long
    assert canonical_decimal(Decimal(f"-{long}.500")) == f"-{long}.5"
    tiny = "0." + "0" * 70 + "1"
    assert canonical_decimal(Decimal(tiny + "000")) == tiny


@pytest.mark.parametrize("text", ["1٢", "1１", "1.٥1", "-1٠", "١٢"])
def test_non_ascii_digits_are_not_canonical(data, tmp_path, text) -> None:
    assert CANONICAL_DECIMAL_RE.fullmatch(text) is None
    with pytest.raises(ValueError, match="non-canonical"):
        require_canonical(text)
    out = tmp_path / "footnote.sqlite"
    write_bundle(build_bundle(data, _options(), PINNED_DIRS), out)
    _rehash(out, f"UPDATE figures SET value = '{text}' WHERE id = '{SEC_REVENUE}'")
    problems = check_bundle(out, release=False, pinned_dirs=PINNED_DIRS)
    assert any(p.startswith(SEC_REVENUE) and "non-canonical" in p for p in problems)


# item 11: verify selects the DART row the way ingest does


def test_dart_comparative_skips_rows_without_a_current_amount(tmp_path) -> None:
    _dart_pinned(tmp_path, 2025, "1", [("ifrs-full_Revenue", "", "111"),
                                       ("ifrs-full_Revenue", "222", "333")])  # fmt: skip
    pinned = PinnedResponses([tmp_path])
    check = pinned.dart_annual(corp_code="00126380", rcept_no="1", bsns_year=2025,
                               metric="revenue", fiscal_year=2024, expected=Decimal("333"))  # fmt: skip
    assert check.regulator_tag == "ifrs-full_Revenue"
    with pytest.raises(VerifyError, match="revenue is 333, stored 111"):
        pinned.dart_annual(corp_code="00126380", rcept_no="1", bsns_year=2025,
                           metric="revenue", fiscal_year=2024, expected=Decimal("111"))  # fmt: skip


# item 12: the schema is defined once


def test_every_schema_column_is_in_the_fingerprint(data, tmp_path) -> None:
    with sqlite3.connect(":memory:") as connection:
        connection.executescript(SCHEMA)
        names = [n for (n,) in connection.execute("SELECT name FROM sqlite_master "
                                                  "WHERE type = 'table'")]  # fmt: skip
        schema = {n: {c[1] for c in connection.execute(f"PRAGMA table_info({n})")} for n in names}
    fingerprinted = {n: cols for n, cols in schema.items() if n != "build_meta"}
    assert {n: set(spec[0]) for n, spec in TABLES.items()} == fingerprinted

    approved = _all_approved(data, build_bundle(data, _options(), PINNED_DIRS),
                             prompt_version="none")
    out = tmp_path / "footnote.sqlite"
    write_bundle(build_bundle(approved, _options(prompt_version="none"), PINNED_DIRS), out)
    with sqlite3.connect(out) as connection:
        lines = [json.loads(line) for line in canonical_dump_lines(connection)]
    seen: dict[str, set[str]] = {}
    for table, row in lines:
        assert set(row) == fingerprinted[table], table
        seen[table] = set(row)
    assert set(seen) == set(fingerprinted) - {"glossary"}


# item 13: a release refuses prompt version none


def test_release_export_refuses_prompt_version_none(data, tmp_path, capsys) -> None:
    approved = _all_approved(data, build_bundle(data, _options(), PINNED_DIRS),
                             prompt_version="none")
    out = tmp_path / "footnote.sqlite"
    assert _export(approved, out, "--release", "--prompt-version", "none") == 1
    assert _no_outputs(tmp_path)
    err = capsys.readouterr().err
    assert "release build refused: --prompt-version is 'none'" in err
    assert "lack approved summaries" not in err


# D76: notices


def test_the_seed_exports_its_notices_and_verify_checks_them(data, tmp_path) -> None:
    out = tmp_path / "footnote.sqlite"
    assert _export(data, out, "--allow-unapproved") == 0
    notices = _rows(out, "SELECT id, category FROM notices ORDER BY id")
    assert notices and {c for _, c in notices} >= {"ir_event", "meeting_notice"}
    assert not {i for i, _ in notices} & {i for (i,) in _rows(out, "SELECT id FROM filings")}
    assert check_bundle(out, release=False, pinned_dirs=PINNED_DIRS) == []

    first = notices[0][0]
    event = _rows(out, "SELECT id FROM filings WHERE kind = 'event' ORDER BY id")[0][0]
    _rehash(out, f"UPDATE notices SET category = 'buyback' WHERE id = '{first}'",
            f"UPDATE filings SET category = 'ir_event' WHERE id = '{event}'")  # fmt: skip
    problems = check_bundle(out, release=False, pinned_dirs=PINNED_DIRS)
    assert f"{first}: 'buyback' is not a notice category" in problems
    assert f"{event}: notice category 'ir_event' as an event" in problems
