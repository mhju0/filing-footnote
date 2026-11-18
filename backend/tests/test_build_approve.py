"""M9 approve command: staged rows move to approved.jsonl only through the owner."""

from __future__ import annotations

import pytest

from app.build import approve, summaries
from app.build.summaries import read_approved, read_jsonl, write_staged

FID = "dart:20260821000616"
OTHER = "dart:20260821000999"
NAMES = ("삼성전자", "SAMSUNG ELECTRONICS CO,.LTD")
KO = ["회사는 자기주식을 취득하기로 결정했다고 공시했어요",
      "회사는 임직원 주식보상에 쓰려고 자기주식을 취득한다고 밝혔어요",
      "회사는 장내 매수로 자기주식을 취득할 예정이라고 밝혔어요"]  # fmt: skip
EN = ["The company decided to repurchase its own shares.",
      "The company said it will use the shares for employee stock compensation.",
      "The company said it plans to acquire the shares on the exchange."]  # fmt: skip


def _row(fid=FID, lang="ko", state="staged", flags=(), violations=(), section="summary"):
    lines = KO if lang == "ko" else EN
    return {
        "filing_id": fid, "lang": lang, "section": section, "line1": lines[0],
        "line2": lines[1], "line3": lines[2], "review_state": state,
        "input_sha256": f"hash-{fid}-{section}", "violations": list(violations),
        "warnings": [], "reviewer_flags": None if flags is None else list(flags),
        "model": "m", "prompt_version": "p", "lexicon_version": 1,
    }  # fmt: skip


def _setup(tmp_path, rows):
    staged, approved = tmp_path / "staged.jsonl", tmp_path / "approved.jsonl"
    write_staged(staged, rows)
    return staged, approved


def _names(_filing_id):
    return NAMES


def test_approve_moves_both_rows_and_keeps_provenance(tmp_path) -> None:
    staged, approved = _setup(tmp_path, [_row(lang="ko"), _row(lang="en"), _row(OTHER)])
    result = approve.approve_filing(staged, approved, FID)
    assert result.approved == [(FID, "en", "summary"), (FID, "ko", "summary")]
    assert [r["filing_id"] for r in read_jsonl(staged)] == [OTHER]
    rows = read_jsonl(approved)
    assert {r["lang"] for r in rows} == {"ko", "en"}
    assert all(r["review_state"] == "approved" for r in rows)
    assert all(r["input_sha256"] == f"hash-{FID}-summary" for r in rows)
    assert all(r["model"] == "m" and r["prompt_version"] == "p" for r in rows)
    # The exporter's reader accepts them.
    assert len(read_approved(approved)) == 2


def test_a_withheld_row_is_refused_and_nothing_changes(tmp_path) -> None:
    staged, approved = _setup(tmp_path, [_row(lang="ko"), _row(lang="en", state="withheld")])
    before = staged.read_bytes()
    with pytest.raises(approve.ApproveError, match="withheld"):
        approve.approve_filing(staged, approved, FID)
    assert staged.read_bytes() == before
    assert not approved.exists()


def test_an_unknown_filing_is_refused(tmp_path) -> None:
    staged, approved = _setup(tmp_path, [_row()])
    with pytest.raises(approve.ApproveError, match="no staged"):
        approve.approve_filing(staged, approved, "dart:nope")


def test_an_edit_replaces_the_line_and_is_approved(tmp_path) -> None:
    staged, approved = _setup(tmp_path, [_row(lang="ko"), _row(lang="en")])
    text = "회사는 자기주식을 장내에서 취득하기로 했다고 공시했어요"
    approve.approve_filing(staged, approved, FID, lang="ko", edit=(1, text), names=_names)
    ko = next(r for r in read_jsonl(approved) if r["lang"] == "ko")
    assert ko["line1"] == text and ko["line2"] == KO[1]
    assert ko["input_sha256"] == f"hash-{FID}-summary"
    assert [r["lang"] for r in read_jsonl(staged)] == ["en"]


def test_an_edit_with_a_digit_is_refused_and_files_are_unchanged(tmp_path) -> None:
    staged, approved = _setup(tmp_path, [_row(lang="ko"), _row(lang="en")])
    before = staged.read_bytes()
    with pytest.raises(approve.ApproveError, match="N1"):
        approve.approve_filing(staged, approved, FID, lang="ko",
                               edit=(1, "회사는 3주를 취득하기로 결정했어요"), names=_names)  # fmt: skip
    assert staged.read_bytes() == before
    assert not approved.exists()


def test_an_edit_needs_a_language_and_a_valid_line(tmp_path) -> None:
    staged, approved = _setup(tmp_path, [_row(lang="ko"), _row(lang="en")])
    with pytest.raises(approve.ApproveError, match="--lang"):
        approve.approve_filing(staged, approved, FID, edit=(1, "x"), names=_names)
    with pytest.raises(approve.ApproveError, match="line"):
        approve.approve_filing(staged, approved, FID, lang="ko", edit=(4, "x"), names=_names)


def test_a_section_is_required_when_the_filing_has_several(tmp_path) -> None:
    rows = [_row(lang=lang, section=s) for lang in ("ko", "en") for s in ("one_line", "business")]
    staged, approved = _setup(tmp_path, rows)
    with pytest.raises(approve.ApproveError, match="--section"):
        approve.approve_filing(staged, approved, FID)
    approve.approve_filing(staged, approved, FID, section="business")
    assert {r["section"] for r in read_jsonl(approved)} == {"business"}
    assert {r["section"] for r in read_jsonl(staged)} == {"one_line"}


def test_approving_again_replaces_the_approved_row(tmp_path) -> None:
    staged, approved = _setup(tmp_path, [_row(lang="ko"), _row(lang="en")])
    old = {**_row(lang="ko", state="approved"), "input_sha256": "old"}
    write_staged(approved, [old])
    approve.approve_filing(staged, approved, FID)
    rows = read_jsonl(approved)
    assert len(rows) == 2
    assert next(r for r in rows if r["lang"] == "ko")["input_sha256"] != "old"


def test_all_reviewed_approves_only_pairs_that_are_clean_and_reviewed(tmp_path) -> None:
    flag = {"lang": "ko", "type": "exaggeration", "line": 1, "quote_from_summary": "x"}
    rows = [
        _row(FID, "ko"), _row(FID, "en"),  # clean and reviewed: approved
        _row(OTHER, "ko", flags=[flag]), _row(OTHER, "en"),  # one language flagged
        _row("dart:2", "ko"), _row("dart:2", "en", flags=None),  # reviewer did not run
        _row("dart:3", "ko", state="withheld"), _row("dart:3", "en"),
        _row("dart:4", "ko"), _row("dart:4", "en", violations=[{"rule_id": "N1"}]),
        _row("dart:5", "ko"),  # only one language staged
    ]  # fmt: skip
    staged, approved = _setup(tmp_path, rows)
    result = approve.approve_all_reviewed(staged, approved)
    assert result.approved == [(FID, "en", "summary"), (FID, "ko", "summary")]
    left = {r["filing_id"] for r in read_jsonl(staged)}
    assert left == {OTHER, "dart:2", "dart:3", "dart:4", "dart:5"}
    assert len(read_jsonl(staged)) == len(rows) - 2


def test_the_command_line_lists_what_it_approved(tmp_path, capsys) -> None:
    staged, approved = _setup(tmp_path, [_row(lang="ko"), _row(lang="en")])
    code = approve.run(["--all-reviewed", "--staged", str(staged), "--approved", str(approved)])
    assert code == 0
    assert f"approved {FID} ko summary" in capsys.readouterr().out
    code = approve.run(["--filing", "dart:nope", "--staged", str(staged),
                        "--approved", str(approved)])  # fmt: skip
    assert code == 1


def test_the_default_paths_are_the_real_files() -> None:
    assert approve.STAGED_PATH == summaries.STAGED_PATH
    assert approve.APPROVED_PATH == summaries.APPROVED_PATH
