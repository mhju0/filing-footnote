"""M9 proofreading sheet: one static page of staged summaries for the owner."""

from __future__ import annotations

from app.build import review
from app.build.review import FilingInfo
from app.build.summaries import write_staged
from tests.build_seed import AS_OF, fixture_build_input

FID = "dart:20260821000616"
FLAGGED = "dart:20260821000001"
WITHHELD = "dart:20260821000002"
KO = ["회사는 자기주식을 취득하기로 결정했다고 공시했어요", "둘째 줄이에요", "셋째 줄이에요"]
EN = ["The company decided to repurchase shares.", "Second line.", "Third line."]


def _row(fid, lang, state="staged", flags=(), violations=(), warnings=(), lines=None):
    lines = lines or (KO if lang == "ko" else EN)
    return {
        "filing_id": fid, "lang": lang, "section": "summary", "line1": lines[0],
        "line2": lines[1], "line3": lines[2], "review_state": state, "input_sha256": "h",
        "violations": list(violations), "warnings": list(warnings),
        "reviewer_flags": list(flags), "model": "m", "prompt_version": "p",
        "lexicon_version": 1,
    }  # fmt: skip


INFO = {
    FID: FilingInfo("삼성전자", "자기주식취득결정", "event",
                    "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260821000616",
                    (("취득예정주식", "3000000"),)),
}  # fmt: skip


def _rows():
    flag = {"lang": "en", "type": "exaggeration", "line": 1, "quote_from_summary": "strong word"}
    violation = {"rule_id": "N1", "line_no": 1, "token": "3", "span": [0, 1]}
    return [
        _row(FID, "ko"), _row(FID, "en"),
        _row(WITHHELD, "ko", "withheld", violations=[violation]),
        _row(FLAGGED, "ko"), _row(FLAGGED, "en", flags=[flag]),
    ]  # fmt: skip


def test_the_page_shows_both_languages_the_command_and_the_source_link() -> None:
    page = review.render(_rows(), INFO, AS_OF)
    assert KO[0] in page and EN[0] in page
    assert f"python -m app.build.approve --filing {FID} --section summary" in page
    assert 'href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260821000616"' in page
    assert "삼성전자" in page and "취득예정주식" in page
    assert "word-break: keep-all" in page and "overflow-wrap: anywhere" in page
    assert "<script" not in page and "http://" not in page


def test_flagged_filings_come_first_then_withheld_then_the_rest() -> None:
    page = review.render(_rows(), INFO, AS_OF)
    order = [page.index(f'id="{f}-summary"') for f in (FLAGGED, WITHHELD, FID)]
    assert order == sorted(order)


def test_withheld_rows_show_violations_and_no_approve_command() -> None:
    page = review.render(_rows(), INFO, AS_OF)
    assert "N1" in page
    assert f"--filing {WITHHELD}" not in page


def test_text_is_escaped() -> None:
    evil = ["<script>alert(1)</script>", "a & b", "c"]
    rows = [_row(FID, "ko", lines=evil), _row(FID, "en", lines=evil)]
    info = {FID: FilingInfo("<b>Co</b>", "t", "event", "javascript:alert(1)", ())}
    page = review.render(rows, info, AS_OF)
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "<b>Co</b>" not in page
    assert "javascript:" not in page


def test_the_page_is_byte_identical_across_runs_and_row_order() -> None:
    first = review.render(_rows(), INFO, AS_OF)
    assert review.render(list(reversed(_rows())), INFO, AS_OF) == first
    assert review.render(_rows(), INFO, AS_OF) == first


def test_the_command_line_writes_the_page_from_a_staged_file(tmp_path) -> None:
    staged = tmp_path / "staged.jsonl"
    write_staged(staged, _rows())
    out = tmp_path / "out" / "review.html"
    assert review.run(["--out", str(out), "--staged", str(staged)]) == 0
    assert FID in out.read_text(encoding="utf-8")


def test_filing_info_comes_from_the_build_input() -> None:
    data = fixture_build_input()
    info = review.build_info(data)
    event = next(e for e in data.events if e.url and e.facts)
    got = info[f"{event.regulator.lower()}:{event.filing_key}"]
    assert got.title == event.report_nm and got.url == event.url and got.facts
    assert all(isinstance(value, str) for _, value in got.facts)


def test_the_source_text_is_shown_escaped_under_each_summary() -> None:
    sources = {(FID, "summary"): "취득예정주식 3,000,000주 <b>원문</b>"}
    page = review.render(_rows(), INFO, AS_OF, sources)
    assert "Source text the summary was written from" in page
    assert "취득예정주식 3,000,000주 &lt;b&gt;원문&lt;/b&gt;" in page
    assert page.count("Source text the summary was written from") == 1


def test_sources_come_from_the_summary_targets() -> None:
    data = fixture_build_input()
    sources = review.build_sources(data, AS_OF)
    assert sources and all(text for text in sources.values())
    assert all(section in ("summary", "one_line", "business", "changes", "risks")
               for _, section in sources)  # fmt: skip


def test_korean_is_shown_before_english() -> None:
    page = review.render(_rows(), INFO, AS_OF)
    card = page[page.index(f'id="{FID}-summary"') :]
    assert card.index(KO[0]) < card.index(EN[0])
