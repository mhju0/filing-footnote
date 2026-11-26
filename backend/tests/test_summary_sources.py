"""Source sentences in the bundle (D101): the export copies them, verify holds them to the report."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.build import faithfulness, verify
from app.build.bundle import content_sha256
from app.build.export import build_bundle
from app.build.model import BuildError, BuildInput
from app.build.verify import check_bundle
from tests.build_seed import PINNED_DIRS, fixture_build_input, supported_records
from tests.test_build_export import (
    RELEASE,
    _all_approved,
    _export,
    _faithfulness_dir,  # noqa: F401  (autouse fixture, see test_build_export.py)
    _no_event_cap,  # noqa: F401  (autouse fixture, see test_build_export.py)
    _options,
    _pinned_args,
    _rehash,
    _rows,
)

PREVIEW = ("--preview", "--prompt-version", "v1")


@pytest.fixture(scope="module")
def data() -> BuildInput:
    return fixture_build_input()


@pytest.fixture
def approved(data) -> BuildInput:
    """After the autouse fixtures, so the event cap is the one the export runs with."""
    return _all_approved(data, build_bundle(data, _options(), PINNED_DIRS))


def _event(approved: BuildInput) -> str:
    return next(s.filing_id for s in approved.summaries
                if s.section == "summary" and s.filing_id.startswith("dart:"))  # fmt: skip


def _sec_event(approved: BuildInput) -> str:
    return next(s.filing_id for s in approved.summaries
                if s.section == "summary" and s.filing_id.startswith("sec:"))  # fmt: skip


def _edit(records: list[dict], filing_id: str, lang: str, section: str, line_no: int, **changes):
    """Replace the fields of one line's record."""
    for number, record in enumerate(records):
        if (record["filing_id"], record["lang"], record["section"], record["line_no"]) == (
            filing_id, lang, section, line_no
        ):  # fmt: skip
            records[number] = {**record, **changes}
            return records[number]
    raise AssertionError((filing_id, lang, section, line_no))


def _report(tmp_path: Path, records: list[dict]) -> Path:
    path = tmp_path / "report" / "faithfulness.jsonl"
    faithfulness.write_records(path, records)
    return path


def _release(approved: BuildInput, records: list[dict], accepted=()) -> object:
    options = _options(allow_unapproved=False, prompt_version="v1")
    return build_bundle(approved, options, PINNED_DIRS,
                        faithfulness.RecordIndex(records, accepted))  # fmt: skip


def _sources(path: Path, where: str = "1 = 1") -> list[tuple]:
    return _rows(path, "SELECT filing_id, lang, section, line_no, position, verdict, excerpt, "
                       f"excerpt_lang FROM summary_sources WHERE {where} "
                       "ORDER BY filing_id, lang, section, line_no, position")  # fmt: skip


def _accepted(record: dict) -> dict:
    return {key: record[key] for key in
            ("filing_id", "lang", "section", "line_no", "line_sha256", "input_sha256")}  # fmt: skip


# -- export ---------------------------------------------------------------------------------------


def test_a_release_copies_each_lines_span_in_source_order(approved, tmp_path) -> None:
    records = supported_records(approved.summaries)
    event = _event(approved)
    two = [{"start": 300, "end": 304, "text": "둘째 문장"}, {"start": 10, "end": 14, "text": "첫째 문장"}]
    _edit(records, event, "ko", "summary", 2, verdict=faithfulness.PARTLY, spans=two)
    _edit(records, event, "en", "summary", 3, verdict=faithfulness.TEMPLATE, spans=[])
    out = tmp_path / "footnote.sqlite"
    assert _export(approved, out, *RELEASE, "--faithfulness", str(_report(tmp_path, records))) == 0
    assert _sources(out, f"filing_id = '{event}' AND line_no > 1") == [
        (event, "en", "summary", 2, 0, "supported", "공시 원문 문장", "ko"),
        (event, "en", "summary", 3, 0, "template", None, "ko"),
        (event, "ko", "summary", 2, 0, "partly", "첫째 문장", "ko"),
        (event, "ko", "summary", 2, 1, "partly", "둘째 문장", "ko"),
        (event, "ko", "summary", 3, 0, "supported", "공시 원문 문장", "ko"),
    ]
    # Every line of the bundle has its rows, and an SEC filing's excerpt is English for a
    # Korean line too.
    lines = sum(1 for row in _rows(out, "SELECT line1, line2, line3 FROM filing_summaries")
                for line in row if line is not None)  # fmt: skip
    assert _rows(out, "SELECT count(DISTINCT filing_id || lang || section || line_no) "
                      "FROM summary_sources")[0][0] == lines  # fmt: skip
    sec = _sec_event(approved)
    assert {r[-1] for r in _sources(out, f"filing_id = '{sec}'")} == {"en"}
    assert _rows(out, "SELECT aligner_version FROM build_meta") == [(faithfulness.ALIGNER_VERSION,)]
    report = json.loads(out.with_name("footnote.report.json").read_text(encoding="utf-8"))
    assert report["summary_sources"]["lines_without_record"] == []
    assert report["summary_sources"]["sections_withheld"] == []


@pytest.mark.parametrize("verdict", [faithfulness.UNSUPPORTED, faithfulness.NO_SOURCE])
def test_a_release_refuses_a_line_whose_span_cannot_ship(approved, verdict) -> None:
    records = supported_records(approved.summaries)
    event = _event(approved)
    _edit(records, event, "en", "summary", 1, verdict=verdict, spans=[])
    with pytest.raises(BuildError) as raised:
        _release(approved, records)
    assert any(f"{event} en/summary line 1 is {verdict}" in p and "never ship" in p
               for p in raised.value.problems)  # fmt: skip


def test_a_supported_line_without_a_span_cannot_ship_either(approved) -> None:
    records = supported_records(approved.summaries)
    event = _event(approved)
    _edit(records, event, "ko", "summary", 1, verdict=faithfulness.PARTLY, spans=[])
    with pytest.raises(BuildError, match=f"{event} ko/summary line 1 is partly"):
        _release(approved, records)


def test_an_owner_accepted_line_ships_without_a_source_sentence(approved, tmp_path) -> None:
    records = supported_records(approved.summaries)
    event = _event(approved)
    flagged = _edit(records, event, "en", "summary", 1, verdict=faithfulness.UNSUPPORTED, spans=[])
    bundle = _release(approved, records, accepted=[_accepted(flagged)])
    keys = {row[:4] for row in bundle.rows["summary_sources"]}
    assert (event, "en", "summary", 1) not in keys and (event, "ko", "summary", 1) in keys
    assert bundle.report["summary_sources"]["lines_accepted_without_source"] == 1


def test_a_release_refuses_a_missing_report_once(approved, tmp_path, capsys) -> None:
    out = tmp_path / "out" / "footnote.sqlite"
    missing = tmp_path / "absent.jsonl"
    assert _export(approved, out, *RELEASE, "--faithfulness", str(missing)) == 1
    err = capsys.readouterr().err
    assert err.count(f"no faithfulness report at {missing}") == 1
    assert "have no faithfulness record" not in err and not out.exists()


def test_a_release_names_lines_without_a_current_record(approved, tmp_path, capsys) -> None:
    records = supported_records(approved.summaries)
    event = _event(approved)
    _edit(records, event, "ko", "summary", 3, line_sha256="0" * 64)  # the line was edited
    _edit(records, event, "en", "summary", 2, aligner_version="f0-older")
    out = tmp_path / "out" / "footnote.sqlite"
    assert _export(approved, out, *RELEASE, "--faithfulness", str(_report(tmp_path, records))) == 1
    err = capsys.readouterr().err
    assert "2 summary lines have no faithfulness record" in err
    assert f"{event} en/summary line 2" in err and f"{event} ko/summary line 3" in err


@pytest.mark.parametrize("mode", [PREVIEW, ("--allow-unapproved",)])
def test_a_preview_withholds_an_unsupported_section_in_both_languages(
    approved, tmp_path, mode
) -> None:
    records = supported_records(approved.summaries)
    event, sec = _event(approved), _sec_event(approved)
    _edit(records, event, "en", "summary", 2, verdict=faithfulness.UNSUPPORTED, spans=[])
    records = [r for r in records if not (r["filing_id"] == sec and r["lang"] == "ko"
                                          and r["line_no"] == 1)]  # fmt: skip
    out = tmp_path / "footnote.sqlite"
    assert _export(approved, out, *mode, "--faithfulness", str(_report(tmp_path, records))) == 0
    assert _rows(out, f"SELECT count(*) FROM filing_summaries WHERE filing_id = '{event}'") == [
        (0,)
    ]
    assert _sources(out, f"filing_id = '{event}'") == []
    # A line without a record ships without a source sentence; its twin keeps its own.
    assert _sources(out, f"filing_id = '{sec}' AND line_no = 1") == [
        (sec, "en", "summary", 1, 0, "supported", "A sentence of the filing.", "en")
    ]
    report = json.loads(out.with_name("footnote.report.json").read_text(encoding="utf-8"))
    assert report["summary_sources"]["sections_withheld"] == [f"{event} summary"]
    assert report["summary_sources"]["lines_without_record"] == [f"{sec} ko/summary line 1"]
    assert check_bundle(out, release=False, pinned_dirs=PINNED_DIRS) == []


def test_a_development_build_without_a_report_ships_no_source_sentences(approved, tmp_path) -> None:
    out = tmp_path / "footnote.sqlite"
    absent = tmp_path / "absent.jsonl"
    assert _export(approved, out, "--allow-unapproved", "--faithfulness", str(absent)) == 0
    assert _rows(out, "SELECT count(*) FROM summary_sources") == [(0,)]
    assert _rows(out, "SELECT count(*) FROM filing_summaries")[0][0] > 0


# -- the fingerprint ------------------------------------------------------------------------------


def test_the_fingerprint_covers_the_excerpts_and_the_aligner_version(approved, tmp_path) -> None:
    out = tmp_path / "footnote.sqlite"
    assert _export(approved, out, *RELEASE) == 0
    with sqlite3.connect(out) as connection:
        stored = connection.execute("SELECT content_sha256 FROM build_meta").fetchone()[0]
        assert content_sha256(connection) == stored
        assert content_sha256(connection, "f0-other") != stored
        connection.execute("UPDATE summary_sources SET excerpt = excerpt || ' ' "
                           "WHERE rowid = (SELECT min(rowid) FROM summary_sources)")  # fmt: skip
        assert content_sha256(connection) != stored
    assert "content_sha256 does not match the file's contents" in check_bundle(
        out, release=False, pinned_dirs=PINNED_DIRS
    )


def test_a_changed_aligner_version_fails_verify(approved, tmp_path) -> None:
    out = tmp_path / "footnote.sqlite"
    assert _export(approved, out, *RELEASE) == 0
    _rehash(out, "UPDATE build_meta SET aligner_version = 'f0-older'")
    assert "aligner_version 'f0-older' is not " + repr(faithfulness.ALIGNER_VERSION) in (
        check_bundle(out, release=False, pinned_dirs=PINNED_DIRS)
    )


def test_the_schema_keeps_template_rows_without_an_excerpt(approved, tmp_path) -> None:
    out = tmp_path / "footnote.sqlite"
    assert _export(approved, out, *RELEASE) == 0
    with sqlite3.connect(out) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute("UPDATE summary_sources SET verdict = 'template' "
                           "WHERE rowid = (SELECT min(rowid) FROM summary_sources)")  # fmt: skip
    with sqlite3.connect(out) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute("UPDATE summary_sources SET verdict = 'unsupported' "
                           "WHERE rowid = (SELECT min(rowid) FROM summary_sources)")  # fmt: skip


# -- verify ---------------------------------------------------------------------------------------


def _verify(out: Path, report: Path, *extra: str) -> int:
    return verify.main([str(out), "--release", *_pinned_args(), "--faithfulness", str(report),
                        *extra])  # fmt: skip


def test_release_verify_requires_a_source_sentence_for_every_line(approved, tmp_path, capsys):
    records = supported_records(approved.summaries)
    report = _report(tmp_path, records)
    out = tmp_path / "footnote.sqlite"
    assert _export(approved, out, *RELEASE, "--faithfulness", str(report)) == 0
    assert _verify(out, report) == 0
    event = _event(approved)
    _rehash(out, f"DELETE FROM summary_sources WHERE filing_id = '{event}' AND lang = 'ko' "
                 "AND section = 'summary' AND line_no = 2")  # fmt: skip
    capsys.readouterr()
    for policy in ("unsupported", "warn", "off"):
        assert _verify(out, report, "--faithfulness-policy", policy) == 1
        err = capsys.readouterr().err
        assert f"{event} ko/summary line 2: no supported, partly or template source" in err
    # A development check only looks at the rows that are there.
    assert check_bundle(out, release=False, pinned_dirs=PINNED_DIRS) == []


def test_release_verify_lets_an_accepted_line_through_without_one(approved, tmp_path, monkeypatch):
    records = supported_records(approved.summaries)
    event = _event(approved)
    flagged = _edit(records, event, "en", "summary", 1, verdict=faithfulness.UNSUPPORTED, spans=[])
    accepted = tmp_path / "accepted.jsonl"
    faithfulness.write_records(accepted, [_accepted(flagged)])
    monkeypatch.setattr(faithfulness, "ACCEPTED_PATH", accepted)
    report = _report(tmp_path, records)
    out = tmp_path / "footnote.sqlite"
    assert _export(approved, out, *RELEASE, "--faithfulness", str(report)) == 0
    gate = faithfulness.load_gate("unsupported", report, accepted)
    assert check_bundle(out, release=True, pinned_dirs=PINNED_DIRS, faithfulness_gate=gate) == []
    # Without the acceptance, the same file fails twice: the verdict and the missing sentence.
    gate = faithfulness.load_gate("unsupported", report, tmp_path / "none.jsonl")
    problems = check_bundle(out, release=True, pinned_dirs=PINNED_DIRS, faithfulness_gate=gate)
    assert f"{event} en/summary line 1: faithfulness unsupported" in problems
    assert f"{event} en/summary line 1: no supported, partly or template source sentence" in problems


def test_release_verify_compares_the_rows_with_the_report(approved, tmp_path, capsys) -> None:
    records = supported_records(approved.summaries)
    report = _report(tmp_path, records)
    out = tmp_path / "footnote.sqlite"
    assert _export(approved, out, *RELEASE, "--faithfulness", str(report)) == 0
    event = _event(approved)
    _rehash(out, "UPDATE summary_sources SET excerpt = '다른 문장이다.', source_end = "
                 f"source_start + 8 WHERE filing_id = '{event}' AND lang = 'en' "
                 "AND section = 'summary' AND line_no = 1")  # fmt: skip
    capsys.readouterr()
    assert _verify(out, report) == 1
    assert (f"{event} en/summary line 1: summary_sources rows differ from the faithfulness report"
            in capsys.readouterr().err)  # fmt: skip
    # Only a blocking policy compares; warn and off still need a sentence per line.
    assert _verify(out, report, "--faithfulness-policy", "warn") == 0


@pytest.mark.parametrize(
    ("statement", "problem"),
    [
        ("UPDATE summary_sources SET line_no = 3 WHERE section = 'one_line'",
         "summary_sources row for a line the bundle does not hold"),
        ("UPDATE summary_sources SET excerpt_lang = 'en' WHERE filing_id LIKE 'dart:%' "
         "AND section = 'one_line'", "excerpt_lang 'en', the filing's language is 'ko'"),
        ("UPDATE summary_sources SET source_end = source_end + 1 WHERE section = 'one_line'",
         "excerpt does not match its offsets"),
        ("UPDATE summary_sources SET position = 1 WHERE section = 'one_line'",
         "summary_sources positions are not 0..0"),
    ],
)  # fmt: skip
def test_every_check_reads_the_rows_that_are_there(approved, tmp_path, statement, problem) -> None:
    out = tmp_path / "footnote.sqlite"
    assert _export(approved, out, *RELEASE) == 0
    _rehash(out, statement)
    problems = check_bundle(out, release=False, pinned_dirs=PINNED_DIRS)
    assert any(problem in p for p in problems), problems


def test_bundle_source_problems_reads_mappings() -> None:
    summary = {"filing_id": "dart:1", "lang": "en", "section": "summary", "line1": "One.",
               "line2": "Two.", "line3": None, "input_sha256": "k"}  # fmt: skip
    row = dict(zip(faithfulness.SOURCE_COLUMNS,
                   ("dart:1", "en", "summary", 1, 0, "template", None, "ko", None, None),
                   strict=True))  # fmt: skip
    twin = {**row, "position": 1}
    assert faithfulness.bundle_source_problems([summary], [row], {"dart:1": "DART"}) == []
    problems = faithfulness.bundle_source_problems(
        [summary], [row, twin], {"dart:1": "DART"}, release=True
    )
    assert "dart:1 en/summary line 1: a template line has 2 summary_sources rows" in problems
    assert "dart:1 en/summary line 2: no supported, partly or template source sentence" in problems
