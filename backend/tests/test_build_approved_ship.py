"""Approved summaries ship: approved.jsonl -> source.read_summaries -> bundle -> verify --release."""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from pathlib import Path

import pytest

from app.build import export, source, summaries, verify
from app.build.model import EVENT_PROMPT_VERSION, PROMPT_VERSION, BuildInput
from app.build.summaries import select_targets
from tests.build_seed import AS_OF, PINNED_DIRS
from tests.test_build_summaries import MODEL, _approve, _sourced


def _write_approved(path: Path, data: BuildInput, *, skip_state: bool = False) -> BuildInput:
    """Approve every target, write the rows as approved.jsonl, return ``data`` without them."""
    approved = _approve(data, select_targets(data, AS_OF))
    rows = []
    for row in approved.summaries:
        record = dataclasses.asdict(row)
        if skip_state:
            record["review_state"] = "staged"
        rows.append(json.dumps(record, ensure_ascii=False))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return dataclasses.replace(approved, summaries=())


def _run(data: BuildInput, path: Path, out: Path, *extra: str) -> int:
    pinned = [arg for d in PINNED_DIRS for arg in ("--pinned", str(d))]
    args = ["--as-of", AS_OF.isoformat(), "--out", str(out), "--source-revision", "test",
            "--llm-model", MODEL, *pinned, *extra]  # fmt: skip
    return export.run(
        args,
        load=lambda _args: dataclasses.replace(data, summaries=tuple(source.read_summaries(path))),
    )


def test_the_exporters_default_prompt_version_is_the_summary_builds() -> None:
    assert export.DEFAULT_PROMPT_VERSION == PROMPT_VERSION == summaries.PROMPT_VERSION
    assert PROMPT_VERSION != "none"
    assert export.DEFAULT_EVENT_PROMPT_VERSION == EVENT_PROMPT_VERSION
    assert EVENT_PROMPT_VERSION == summaries.EVENT_PROMPT_VERSION != "none"


def test_an_event_prompt_version_change_keeps_the_annual_summaries(tmp_path) -> None:
    # D78: the event prompt is versioned apart, so only event summaries go stale.
    data = _sourced()
    path = tmp_path / "approved.jsonl"
    bare = _write_approved(path, data)
    out = tmp_path / "footnote.sqlite"
    assert _run(bare, path, out, "--allow-unapproved", "--event-prompt-version", "other") == 0
    report = json.loads((tmp_path / "footnote.report.json").read_text(encoding="utf-8"))
    stale = report["summaries"]["stale_approved_rows_skipped"]
    assert {item.split("/")[-1] for item in stale} == {"summary"}
    # The annual reports' approved sections still match and ship.
    with sqlite3.connect(out) as db:
        shipped = {row[0] for row in db.execute("SELECT section FROM filing_summaries")}
    assert {"one_line", "business"} <= shipped


def test_a_release_refuses_event_prompt_version_none(tmp_path, capsys) -> None:
    data = _sourced()
    path = tmp_path / "approved.jsonl"
    bare = _write_approved(path, data)
    assert _run(bare, path, tmp_path / "f.sqlite", "--release", "--event-prompt-version",
                "none") == 1  # fmt: skip
    assert "release build refused: --event-prompt-version is 'none'" in capsys.readouterr().err


def test_a_missing_approved_file_means_no_approved_summaries(tmp_path) -> None:
    assert source.read_summaries(tmp_path / "absent.jsonl") == []


def test_only_approved_rows_are_read(tmp_path) -> None:
    data = _sourced()
    _write_approved(tmp_path / "approved.jsonl", data, skip_state=True)
    assert source.read_summaries(tmp_path / "approved.jsonl") == []


def test_the_default_path_is_the_summary_stores_approved_file(monkeypatch, tmp_path) -> None:
    data = _sourced()
    path = tmp_path / "approved.jsonl"
    _write_approved(path, data)
    monkeypatch.setattr(summaries, "APPROVED_PATH", path)
    assert len(source.read_summaries()) > 0


def test_a_bundle_from_an_approved_file_passes_release_verify(tmp_path) -> None:
    data = _sourced()
    path = tmp_path / "approved.jsonl"
    bare = _write_approved(path, data)
    out = tmp_path / "footnote.sqlite"
    assert _run(bare, path, out, "--release") == 0  # the default prompt version, no flag
    assert (
        verify.main(
            [str(out), "--release", *[a for d in PINNED_DIRS for a in ("--pinned", str(d))]]
        )
        == 0
    )
    report = json.loads((tmp_path / "footnote.report.json").read_text(encoding="utf-8"))
    assert report["mode"] == "release"
    assert report["summaries"]["approved_rows"] > 0
    assert report["build_meta"]["prompt_version"] == PROMPT_VERSION


def test_a_stale_approved_row_fails_the_release_and_is_named(tmp_path, capsys) -> None:
    data = _sourced()
    path = tmp_path / "approved.jsonl"
    bare = _write_approved(path, data)
    lines = path.read_text(encoding="utf-8").splitlines()
    stale = json.loads(lines[0])
    stale["input_sha256"] = "0" * 64
    lines[0] = json.dumps(stale, ensure_ascii=False)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = tmp_path / "footnote.sqlite"
    assert _run(bare, path, out, "--release") == 1
    assert not out.exists()
    err = capsys.readouterr().err
    assert f"{stale['filing_id']} {stale['lang']}/{stale['section']}" in err
    assert "do not match the current source text" in err


def test_a_release_names_every_stale_row_not_just_the_first_ten(tmp_path, capsys) -> None:
    data = _sourced()
    path = tmp_path / "approved.jsonl"
    bare = _write_approved(path, data)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    for row in rows:
        row["input_sha256"] = "0" * 64
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    assert len(rows) > 10
    assert _run(bare, path, tmp_path / "footnote.sqlite", "--release") == 1
    err = capsys.readouterr().err
    for row in rows:
        assert f"{row['filing_id']} {row['lang']}/{row['section']}" in err


def test_a_development_build_leaves_stale_rows_out_and_reports_them(tmp_path) -> None:
    data = _sourced()
    path = tmp_path / "approved.jsonl"
    bare = _write_approved(path, data)
    lines = path.read_text(encoding="utf-8").splitlines()
    stale = json.loads(lines[0])
    stale["input_sha256"] = "0" * 64
    lines[0] = json.dumps(stale, ensure_ascii=False)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = tmp_path / "footnote.sqlite"
    assert _run(bare, path, out, "--allow-unapproved") == 0
    report = json.loads((tmp_path / "footnote.report.json").read_text(encoding="utf-8"))
    assert report["mode"] == "development"
    assert (
        f"{stale['filing_id']} {stale['lang']}/{stale['section']}"
        in (report["summaries"]["stale_approved_rows_skipped"])
    )


@pytest.mark.parametrize("prompt_version", ["none"])
def test_a_release_still_refuses_prompt_version_none(tmp_path, prompt_version) -> None:
    data = _sourced()
    path = tmp_path / "approved.jsonl"
    bare = _write_approved(path, data)
    assert (
        _run(bare, path, tmp_path / "f.sqlite", "--release", "--prompt-version", prompt_version)
        == 1
    )
