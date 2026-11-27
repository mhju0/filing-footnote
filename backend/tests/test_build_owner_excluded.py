"""Event filings the owner excluded (D109): left out of every bundle, the reason in the output."""

from __future__ import annotations

import dataclasses
import datetime
import json
from pathlib import Path

import pytest

from app.build import export, source
from app.build.export import build_bundle
from app.build.model import BuildError, BuildInput, ExcludedFiling
from app.build.verify import check_bundle
from tests.build_seed import AS_OF, PINNED_DIRS, fixture_build_input
from tests.test_build_export import (
    RELEASE,
    _all_approved,
    _export,
    _faithfulness_dir,  # noqa: F401  (autouse fixture, see test_build_export.py)
    _no_event_cap,  # noqa: F401  (autouse fixture, see test_build_export.py)
    _options,
    _rows,
)
from tests.test_build_preview import PREVIEW

DECIDED = datetime.date(2026, 11, 26)
REASON = "Owner decision: no summary and no more regeneration tries."
TABLES_WITH_A_FILING_ID = {
    "filings": "id",
    "filing_facts": "filing_id",
    "filing_summaries": "filing_id",
    "summary_sources": "filing_id",
}


@pytest.fixture(scope="module")
def data() -> BuildInput:
    return fixture_build_input()


def _event_ids(data: BuildInput) -> list[str]:
    bundle = build_bundle(data, _options(), PINNED_DIRS)
    return [row[0] for row in bundle.rows["filings"] if row[2] == "event"]


def _excluding(data: BuildInput, *filing_ids: str) -> BuildInput:
    entries = tuple(ExcludedFiling(fid, DECIDED, REASON) for fid in filing_ids)
    return dataclasses.replace(data, excluded=entries)


def _report(out: Path) -> dict:
    return json.loads(out.with_suffix(".report.json").read_text(encoding="utf-8"))


def _shipped(out: Path, filing_id: str) -> dict[str, int]:
    return {
        table: _rows(out, f"SELECT count(*) FROM {table} WHERE {column} = '{filing_id}'")[0][0]
        for table, column in TABLES_WITH_A_FILING_ID.items()
    }


def test_an_excluded_filing_never_reaches_the_bundle_in_any_mode(data, tmp_path, capsys) -> None:
    everything = build_bundle(data, _options(), PINNED_DIRS)
    # The event with the most facts, so the facts table would show it if it slipped through.
    fid = max(
        _event_ids(data), key=lambda i: sum(r[0] == i for r in everything.rows["filing_facts"])
    )
    # Its approved summaries are in the input too; they must not bring it back.
    approved = _excluding(_all_approved(data, everything), fid)
    for name, extra in (("release", RELEASE), ("preview", PREVIEW),
                        ("development", ("--allow-unapproved",))):  # fmt: skip
        out = tmp_path / f"{name}.sqlite"
        assert _export(approved, out, *extra) == 0, name
        assert _shipped(out, fid) == dict.fromkeys(TABLES_WITH_A_FILING_ID, 0), name
        report = _report(out)
        assert report["owner_excluded_filings"] == {
            "count": 1,
            "filings": [{"id": fid, "decided_on": "2026-11-26", "reason": REASON,
                         "in_scope": True}],
        }, name  # fmt: skip
        assert fid not in report["summaries"]["filings_without_approved_summaries"], name
        printed = capsys.readouterr().out
        assert f"owner-excluded {fid} (left out; decided 2026-11-26): {REASON}" in printed, name
    release = tmp_path / "release.sqlite"
    assert check_bundle(release, release=True, pinned_dirs=PINNED_DIRS) == []


def test_an_excluded_filing_without_a_summary_lets_the_release_ship(data, tmp_path) -> None:
    fid = _event_ids(data)[0]
    sourced = _all_approved(data, build_bundle(data, _options(), PINNED_DIRS),
                            skip=frozenset({fid}))  # fmt: skip
    out = tmp_path / "footnote.sqlite"
    assert _export(_excluding(sourced, fid), out, *RELEASE) == 0
    assert _rows(out, "SELECT allow_unapproved, preview FROM build_meta") == [(0, 0)]
    assert _shipped(out, fid)["filings"] == 0


def test_a_filing_without_a_summary_that_is_not_excluded_still_blocks_the_release(
    data, tmp_path, capsys
) -> None:
    fid, other = _event_ids(data)[:2]
    sourced = _all_approved(data, build_bundle(data, _options(), PINNED_DIRS),
                            skip=frozenset({fid}))  # fmt: skip
    # Excluding a different filing does not excuse this one.
    assert _export(_excluding(sourced, other), tmp_path / "footnote.sqlite", *RELEASE) == 1
    err = capsys.readouterr().err
    assert "exported filings lack approved summaries" in err and fid in err
    assert not any(tmp_path.iterdir())


def test_leaving_one_out_brings_no_other_filing_in(data, monkeypatch) -> None:
    monkeypatch.setattr(export, "EVENT_CAP", 1)
    kept = set(_event_ids(data))
    fid = sorted(kept)[0]
    bundle = build_bundle(_excluding(data, fid), _options(), PINNED_DIRS)
    events = {row[0] for row in bundle.rows["filings"] if row[2] == "event"}
    assert events == kept - {fid}


@pytest.mark.parametrize(
    "filing_id",
    ["dart:20991231000001", "dart:20261030800867", "dart:20260310000123", "20261030800867"],
    ids=["unknown", "not-in-this-input", "an-annual-filing", "no-regulator-prefix"],
)
def test_an_id_that_is_not_an_event_filing_fails_loudly(data, tmp_path, capsys, filing_id) -> None:
    assert filing_id not in _event_ids(data)
    for extra in (RELEASE, PREVIEW, ("--allow-unapproved",)):
        out = tmp_path / "footnote.sqlite"
        assert _export(_excluding(data, filing_id), out, *extra) == 1
        err = capsys.readouterr().err
        assert (f"FAIL {filing_id}: listed as owner-excluded but not an event filing in the "
                "build input") in err  # fmt: skip
        assert not any(tmp_path.iterdir())


def test_the_tracked_list_holds_the_owner_decision_of_2026_11_26() -> None:
    entries = source.read_excluded()
    assert source.EXCLUDED_PATH.name == "excluded_filings.jsonl"
    assert [(e.filing_id, e.decided_on) for e in entries] == [("dart:20261030800867", DECIDED)]
    assert all(e.reason.strip() for e in entries)


def test_a_missing_list_excludes_nothing(tmp_path) -> None:
    assert source.read_excluded(tmp_path / "absent.jsonl") == []


@pytest.mark.parametrize(
    ("lines", "message"),
    [
        (['{"filing_id":"dart:1","decided_on":"2026-11-26"}'], "needs exactly"),
        (
            ['{"filing_id":"dart:1","decided_on":"2026-11-26","reason":"x","note":"y"}'],
            "needs exactly",
        ),
        (['{"filing_id":"dart:1","decided_on":"26 Nov","reason":"x"}'], "is not an ISO date"),
        (['{"filing_id":"dart:1","decided_on":"2026-11-26","reason":" "}'], "non-empty reason"),
        (['{"filing_id":"dart:1","decided_on":"2026-11-26","reason":"x"}'] * 2, "listed twice"),
    ],
    ids=["no-reason", "extra-field", "bad-date", "blank-reason", "duplicate"],
)
def test_a_malformed_list_fails_loudly(tmp_path, lines, message) -> None:
    path = tmp_path / "excluded_filings.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(BuildError, match=message):
        source.read_excluded(path)


def test_the_cli_reads_the_list_it_is_given(data, tmp_path, capsys) -> None:
    path = tmp_path / "excluded_filings.jsonl"
    path.write_text('{"filing_id":"dart:1","decided_on":"2026-11-26","reason":""}\n',
                    encoding="utf-8")  # fmt: skip

    def load(args):
        return dataclasses.replace(data, excluded=tuple(source.read_excluded(args.excluded)))

    out = tmp_path / "out" / "footnote.sqlite"
    pinned = [arg for d in PINNED_DIRS for arg in ("--pinned", str(d))]
    argv = ["--as-of", AS_OF.isoformat(), "--out", str(out), "--source-revision", "test", *pinned,
            "--allow-unapproved", "--excluded", str(path)]  # fmt: skip
    assert export.run(argv, load=load) == 1
    assert "non-empty reason" in capsys.readouterr().err
