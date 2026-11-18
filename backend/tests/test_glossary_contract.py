"""The glossary contract: wording guards, coverage of the other contracts, and export rules."""

from __future__ import annotations

import copy
import dataclasses
import json
import sqlite3
from pathlib import Path

import pytest

from app.build import export
from app.build.bundle import TABLES
from app.build.export import BuildOptions, build_bundle, write_bundle
from app.build.glossary import (
    LANGS,
    glossary_problems,
    glossary_rows,
    load_glossary,
    release_problems,
)
from app.build.model import BuildError, BuildInput
from app.filings.categories import load_contract as load_categories
from tests.build_seed import AS_OF, PINNED_DIRS, fixture_build_input

CONTRACTS = Path(__file__).parents[2] / "contracts"


def _contract(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def data() -> BuildInput:
    return fixture_build_input()


def test_every_entry_is_unapproved_until_the_owner_approves() -> None:
    # Only the owner flips this. When approval starts, replace this with a per-key list.
    assert [k for k, e in load_glossary().items() if e["approved"]] == []


def test_every_entry_has_both_languages_and_passes_the_neutrality_guard() -> None:
    entries = load_glossary()
    assert glossary_problems(entries) == []
    for entry in entries.values():
        for lang in LANGS:
            assert entry[lang]["term"] and entry[lang]["plain"]
            assert not any(c.isdigit() for text in entry[lang].values() if text for c in text)


def test_the_guard_catches_a_digit_a_judgement_word_and_a_missing_language() -> None:
    broken = copy.deepcopy(load_glossary())
    broken["metric_revenue"]["ko"]["plain"] = "회사가 번 돈이 100원이에요."
    broken["metric_eps"]["en"]["plain"] = "A strong measure of profit."
    del broken["restated"]["en"]
    problems = glossary_problems(broken)
    assert any("metric_revenue/ko/plain: N1" in p for p in problems)
    assert any("metric_eps/en/plain: N2" in p for p in problems)
    assert any("restated/en" in p for p in problems)


def test_term_keys_cover_every_metric_category_and_refusal_reason() -> None:
    keys = set(load_glossary())
    vocabulary = _contract("financial-vocabulary.json")
    categories = load_categories()
    refusals = _contract("comparison-cases.json")["refusal_reasons"]
    expected = {
        f"metric_{m}" for m in vocabulary["reported_metrics"] + vocabulary["derived_metrics"]
    }
    for group in ("categories", "notice_categories", "non_event_categories"):
        expected |= {f"category_{c['key']}" for c in categories[group]}
    expected |= {f"refusal_{r}" for r in refusals}
    expected |= {
        "notices", "basis_consolidated", "basis_separate", "restated", "k_ifrs", "us_gaap",
        "fiscal_year_end",
    }  # fmt: skip
    assert expected <= keys
    assert keys - expected == set()  # no entry without a source in the contracts


def test_category_terms_match_the_category_contract_labels() -> None:
    entries = load_glossary()
    categories = load_categories()
    for group in ("categories", "notice_categories", "non_event_categories"):
        for category in categories[group]:
            entry = entries[f"category_{category['key']}"]
            assert entry["ko"]["term"] == category["ko"], category["key"]
            assert entry["en"]["term"] == category["en"], category["key"]


def test_the_glossary_has_no_research_and_development_entry() -> None:
    """research_and_development is only in family-glossary.json, not in the vocabulary."""
    vocabulary = _contract("financial-vocabulary.json")
    assert "research_and_development" not in vocabulary["reported_metrics"]
    assert "metric_research_and_development" not in load_glossary()


def test_rows_are_approved_entries_only_unless_unapproved_are_allowed() -> None:
    entries = copy.deepcopy(load_glossary())
    assert glossary_rows(entries, allow_unapproved=False) == []
    assert len(glossary_rows(entries, allow_unapproved=True)) == 2 * len(entries)
    entries["restated"]["approved"] = True
    shipped = glossary_rows(entries, allow_unapproved=False)
    assert {(r[0], r[1]) for r in shipped} == {("restated", "en"), ("restated", "ko")}
    assert len(release_problems(entries)) == len(entries) - 1


def test_the_glossary_table_matches_the_bundle_schema() -> None:
    columns, key = TABLES["glossary"]
    assert columns == ("term_key", "lang", "term", "plain", "formal")
    assert key == ("term_key", "lang")


def test_development_export_writes_unapproved_entries(data, tmp_path) -> None:
    out = tmp_path / "footnote.sqlite"
    write_bundle(
        build_bundle(data, BuildOptions(AS_OF, "test", allow_unapproved=True), PINNED_DIRS), out
    )
    with sqlite3.connect(out) as connection:
        count = connection.execute("SELECT count(*) FROM glossary").fetchone()[0]
    assert count == 2 * len(load_glossary())


def test_release_refuses_while_any_glossary_entry_is_unapproved(data, monkeypatch) -> None:
    monkeypatch.setattr(export, "load_glossary", load_glossary)  # the contract as committed
    release = dataclasses.replace(
        BuildOptions(AS_OF, "test"), prompt_version="v1", event_prompt_version="v1"
    )
    with pytest.raises(BuildError) as raised:
        build_bundle(data, release, PINNED_DIRS)
    problems = [p for p in raised.value.problems if "glossary" in p]
    assert len(problems) == len(load_glossary())
    assert all("not approved" in p for p in problems)
