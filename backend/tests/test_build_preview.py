"""The preview bundle (D90): relaxes missing and stale summaries only, every other check stays."""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from pathlib import Path

import pytest

from app.build import export
from app.build.export import build_bundle
from app.build.glossary import load_glossary
from app.build.model import BuildError, BuildInput
from app.build.verify import check_bundle
from tests.build_seed import APPLE_PRIOR, PINNED_DIRS, SAMSUNG_PRIOR, fixture_build_input
from tests.test_build_export import (
    RELEASE,
    _all_approved,
    _export,
    _faithfulness_dir,  # noqa: F401  (autouse fixture, see test_build_export.py)
    _no_event_cap,  # noqa: F401  (autouse fixture, see test_build_export.py)
    _options,
    _rows,
    _without_filings,
)

PREVIEW = ("--preview", "--prompt-version", "v1")


@pytest.fixture(scope="module")
def data() -> BuildInput:
    return fixture_build_input()


def _preview_options(**changes):
    return _options(
        **{"allow_unapproved": False, "preview": True, "prompt_version": "v1", **changes}
    )


def _unapproved_glossary(monkeypatch) -> None:
    unapproved = {k: {**e, "approved": False} for k, e in load_glossary().items()}
    monkeypatch.setattr(export, "load_glossary", lambda: unapproved)


def _with_missing_summary(data: BuildInput):
    """Approved summaries for every filing but the first one, which has none."""
    everything = build_bundle(data, _options(), PINNED_DIRS)
    skipped = everything.rows["filings"][0][0]
    return _all_approved(data, everything, skip=frozenset({skipped})), skipped


def test_a_preview_builds_without_a_summary_and_without_unapproved_glossary(
    data, tmp_path, monkeypatch
) -> None:
    _unapproved_glossary(monkeypatch)
    sourced, skipped = _with_missing_summary(data)
    out = tmp_path / "footnote.sqlite"
    assert _export(sourced, out, *PREVIEW) == 0
    assert _rows(out, "SELECT allow_unapproved, preview FROM build_meta") == [(0, 1)]
    assert _rows(out, "SELECT count(*) FROM glossary") == [(0,)]
    assert _rows(out, f"SELECT count(*) FROM filing_summaries WHERE filing_id = '{skipped}'") == [
        (0,)
    ]
    assert _rows(out, "SELECT DISTINCT review_state FROM filing_summaries") == [("approved",)]
    report = json.loads(out.with_suffix(".report.json").read_text(encoding="utf-8"))
    assert report["mode"] == "preview"
    assert report["summaries"]["filings_without_approved_summaries"] == [skipped]


def test_a_release_still_refuses_the_same_data(data, tmp_path, monkeypatch) -> None:
    _unapproved_glossary(monkeypatch)
    sourced, _ = _with_missing_summary(data)
    assert _export(sourced, tmp_path / "footnote.sqlite", *RELEASE) == 1


def test_a_development_build_and_a_release_record_preview_zero(data, tmp_path) -> None:
    sourced, _ = _with_missing_summary(data)
    development = tmp_path / "development.sqlite"
    assert _export(sourced, development, "--allow-unapproved") == 0
    assert _rows(development, "SELECT allow_unapproved, preview FROM build_meta") == [(1, 0)]
    complete = _all_approved(data, build_bundle(data, _options(), PINNED_DIRS))
    release = tmp_path / "release.sqlite"
    assert _export(complete, release, *RELEASE) == 0
    assert _rows(release, "SELECT allow_unapproved, preview FROM build_meta") == [(0, 0)]


def test_the_modes_are_mutually_exclusive(data, tmp_path) -> None:
    with pytest.raises(SystemExit):
        _export(data, tmp_path / "footnote.sqlite", "--preview", "--allow-unapproved")


def test_a_preview_still_refuses_a_neutrality_failure(data) -> None:
    sourced, _ = _with_missing_summary(data)
    bad = dataclasses.replace(sourced.summaries[0], line1="The company reported 5 percent.")
    broken = dataclasses.replace(sourced, summaries=(bad, *sourced.summaries[1:]))
    with pytest.raises(BuildError) as raised:
        build_bundle(broken, _preview_options(), PINNED_DIRS)
    assert any(bad.filing_id in p for p in raised.value.problems)


def test_a_preview_still_refuses_prompt_version_none(data) -> None:
    sourced, _ = _with_missing_summary(data)
    with pytest.raises(BuildError, match="--prompt-version is 'none'"):
        build_bundle(sourced, _preview_options(prompt_version="none"), PINNED_DIRS)
    with pytest.raises(BuildError, match="--event-prompt-version is 'none'"):
        build_bundle(sourced, _preview_options(event_prompt_version="none"), PINNED_DIRS)


def test_a_preview_still_refuses_restatement_unchecked(data) -> None:
    bundle = build_bundle(data, _options(), PINNED_DIRS)
    no_prior = _without_filings(data, SAMSUNG_PRIOR, APPLE_PRIOR)
    with pytest.raises(BuildError, match="restatement_unchecked"):
        build_bundle(_all_approved(no_prior, bundle), _preview_options(), PINNED_DIRS)


def test_verify_release_refuses_a_preview_and_verify_preview_refuses_a_development_build(
    data, tmp_path
) -> None:
    sourced, _ = _with_missing_summary(data)
    preview = tmp_path / "preview.sqlite"
    development = tmp_path / "development.sqlite"
    assert _export(sourced, preview, *PREVIEW) == 0
    assert _export(sourced, development, "--allow-unapproved") == 0

    release_problems = check_bundle(preview, release=True, pinned_dirs=PINNED_DIRS)
    assert "a preview bundle; a release refuses it" in release_problems
    # Missing summaries are the preview's business, a release also reports them.
    assert check_bundle(preview, release=False, preview=True, pinned_dirs=PINNED_DIRS) == []

    refused = check_bundle(development, release=False, preview=True, pinned_dirs=PINNED_DIRS)
    assert "built with --allow-unapproved; a preview refuses it" in refused


def test_verify_preview_keeps_the_other_release_checks(data, tmp_path) -> None:
    sourced, _ = _with_missing_summary(data)
    preview = tmp_path / "preview.sqlite"
    assert _export(sourced, preview, *PREVIEW) == 0
    with sqlite3.connect(preview) as connection:
        connection.execute("UPDATE build_meta SET prompt_version = 'none'")
    problems = check_bundle(preview, release=False, preview=True, pinned_dirs=PINNED_DIRS)
    assert any("prompt_version is 'none'" in p for p in problems)


def test_the_makefile_has_a_preview_target() -> None:
    makefile = (Path(__file__).resolve().parents[2] / "Makefile").read_text(encoding="utf-8")
    assert "data-preview:" in makefile and "--preview" in makefile
