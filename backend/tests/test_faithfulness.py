"""The build-time faithfulness check (D95): alignment, verdicts, the release gate and the eval."""

from __future__ import annotations

import json

import pytest

from app.build import faithfulness as f

SKHYNIX = (
    "Report: 사업보고서 (2025.12)\n\n[1. 사업의 개요]\n"
    "당사는 경기도 이천시에 위치한 본사를 거점으로 4개의 생산기지와 3개의 연구개발법인 및 "
    "미국, 중국, 싱가포르, 대만, 홍콩 등 판매법인과 사무소를 운영하고 있는 글로벌 반도체 "
    "기업입니다.\n당사 및 당사의 종속기업의 주력 제품은 DRAM 및 NAND를 중심으로 하는 메모리 "
    "반도체이며, Foundry 사업도 병행하고 있습니다."
)
SKHYNIX_LINES = {
    "ko": [
        "회사는 경기도 이천시에 본사를 둔 글로벌 반도체 기업이라고 밝혔어요.",
        "회사는 주력 제품이 DRAM과 NAND 중심의 메모리 반도체이며 파운드리 사업도 한다고 보고했어요.",
        "회사는 미국, 중국, 싱가포르, 대만, 홍콩에 판매법인과 사무소를 운영한다고 적었어요.",
    ],
    "en": [
        "The company said it is a global semiconductor company with its headquarters in Icheon, "
        "Gyeonggi Province.",
        "The company reported that its main products are memory semiconductors centered on DRAM "
        "and NAND, and it also runs a Foundry business.",
        "The company stated that it operates sales subsidiaries and offices in the United States, "
        "China, Singapore, Taiwan, and Hong Kong.",
    ],
}
DISPOSAL = (
    "Filing title: 주요사항보고서(자기주식처분결정)\n\nFiling text:\n자기주식 처분 결정 "
    "1. 처분예정주식(주) 보통주식 917,385 5. 처분목적 2026년 임금협상 결과에 따른 주식지급 "
    "6. 처분방법 기 타(주) 917,385 7. 처분상대방 직원 61,159명 13. 기타 투자판단에 참고할 사항 "
    "- 본 자기주식 처분 결정은 2026년 임금협상 결과에 따라 주식을 지급하기 위한 건으로, "
    "정기 주주총회에서 승인받은 자기주식 보유ㆍ처분 계획에 따른 처분임."
)
DISPOSAL_LINES = {
    "ko": ["회사는 임금협상 결과에 따라 직원에게 자기주식을 처분하기로 결정했어요"],
    "en": ["The company decided to dispose of treasury shares to employees based on the wage "
           "negotiation results."],
}  # fmt: skip
DIVIDEND = (
    "Filing title: 8-K\n\nFiling text:\nItem 8.01. Other Events\nThe Board of Directors declared "
    "a quarterly cash dividend on the Company's common stock and approved a quarterly increase "
    "from $1.30 to $1.47 per share. The dividend is payable May 15, 2026, to shareholders of "
    "record at the close of business on May 1, 2026."
)
CLARIFICATION = (
    "Filing title: 풍문또는보도에대한해명(미확정)\n\nFiling text:\n1. 풍문 또는 보도의 내용 "
    "[단독] LG전자 美자회사 베어로보틱스, 나스닥 상장 도전 2. 풍문 또는 보도의 매체 한국경제 "
    "4. 풍문 또는 보도의 내용에 대한 해명내용 - 당사의 해외 종속회사인 베어로보틱스는 해외 "
    "상장과 관련하여 결정된 바가 없습니다. - 추후 구체적인 내용이 확정되는 시점 또는 1개월 "
    "이내 재공시 하겠습니다."
)


def verdicts(lines: dict[str, list[str]], source: str) -> dict[str, list[str]]:
    return {lang: [r.verdict for r in rs] for lang, rs in f.check_section(lines, source).items()}


# -- words and terms -----------------------------------------------------------------------------


def test_korean_stems_drop_particles_and_endings() -> None:
    assert "이천시" in f.ko_stems("이천시에")
    assert "결정" in f.ko_stems("결정되거나")
    assert "승용" in f.ko_stems("승용차와")  # a compound the filing writes short


def test_terms_resolve_to_one_id_in_both_languages() -> None:
    lexicon = f.load_lexicon()

    def ids(text: str) -> list[str]:
        return [term for term, _, _ in f.scan_terms(text, lexicon)]

    assert ids("파운드리") == ids("Foundry") == ["product.foundry"]
    assert ids("중화권") == ids("Greater China") == ["place.greater_china"]
    assert ids("Greater China and China") == ["place.greater_china", "place.china"]
    assert ids("아시아 태평양") == ids("Asia-Pacific") == ["place.asia_pacific"]
    assert ids("美자회사") == ["place.us", "term.subsidiary"]
    assert ids("U.S. and US") == ["place.us", "place.us"]
    assert ids("let us") == []  # an acronym keeps its case


def test_look_alike_words_are_not_terms() -> None:
    lexicon = f.load_lexicon()
    assert f.scan_terms("부산물", lexicon) == []  # a by-product, not Busan
    assert f.scan_terms("사유로", lexicon) == []  # a reason, not the euro
    assert f.scan_terms("이 중 동일", lexicon) == []  # not 중동 across a space
    assert [t for t, _, _ in f.scan_terms("대중국 수출", lexicon)] == ["place.china"]


def test_a_term_inside_a_compound_and_a_hanja_country() -> None:
    lexicon = f.load_lexicon()
    ids = [t for t, _, _ in f.scan_terms("日 키옥시아 지분 차익 특별배당 추진", lexicon)]
    assert ids == ["place.japan", "term.special", "term.dividend"]


def test_an_acronym_the_source_spells_out_is_supported() -> None:
    source = ("Filing text:\nEach Global Note will be payable to Cede & Co., as nominee of The "
              "Depository Trust Company.")  # fmt: skip
    lines = {"en": ["The company said the global notes are payable to Cede & Co. as nominee of "
                    "DTC."]}  # fmt: skip
    assert verdicts(lines, source)["en"] == [f.SUPPORTED]
    lines = {"en": ["The company said the global notes are payable to Cede & Co. as nominee of "
                    "NYSE."]}  # fmt: skip
    assert verdicts(lines, source)["en"] == [f.UNSUPPORTED]


def test_sentences_keep_offsets_and_decimals() -> None:
    text = "주요사항보고서 6.4 현대자동차 5. 처분목적 임금협상 결과. 6. 처분방법 기타"
    sentences = f.split_sentences(text)
    assert all(text[s.start : s.end] == s.text for s in sentences)
    assert any("6.4 현대자동차" in s.text for s in sentences)
    assert [s.text for s in sentences if s.text.startswith("5.")] == ["5. 처분목적 임금협상 결과."]


# -- verdicts ------------------------------------------------------------------------------------


def test_korean_and_cross_language_lines_are_supported() -> None:
    results = f.check_section(SKHYNIX_LINES, SKHYNIX)
    assert [r.verdict for r in results["ko"]] == [f.SUPPORTED] * 3
    assert [r.verdict for r in results["en"]] == [f.SUPPORTED] * 3
    assert {r.method for r in results["en"]} == {"pivot"}
    # The span is the source sentence, by offset.
    span = results["ko"][0].spans[0]
    assert SKHYNIX[span.start : span.end] == span.text and "이천시" in span.text


def test_english_lines_against_english_source() -> None:
    lines = {
        "en": ["The company said its Board of Directors declared a quarterly cash dividend on "
               "common stock."],
        "ko": ["회사는 이사회가 보통주에 대해 분기 현금 배당을 결정했다고 밝혔어요"],
    }  # fmt: skip
    assert verdicts(lines, DIVIDEND) == {"en": [f.SUPPORTED], "ko": [f.SUPPORTED]}


def test_a_place_the_source_never_names_is_unsupported() -> None:
    swapped = {
        "ko": [SKHYNIX_LINES["ko"][2].replace("싱가포르", "일본")],
        "en": [SKHYNIX_LINES["en"][2].replace("Singapore", "Japan")],
    }
    results = f.check_section(swapped, SKHYNIX)
    assert [r.verdict for r in results["ko"]] == [f.UNSUPPORTED]
    assert [r.verdict for r in results["en"]] == [f.UNSUPPORTED]
    assert "place.japan" in results["ko"][0].reasons[0]


def test_an_english_place_is_checked_against_a_korean_source() -> None:
    lines = {"ko": SKHYNIX_LINES["ko"][:1], "en": ["The company said it is a global semiconductor "
             "company with its headquarters in Icheon and offices in Germany."]}  # fmt: skip
    assert verdicts(lines, SKHYNIX)["en"] == [f.UNSUPPORTED]


def test_a_number_the_source_does_not_state_is_unsupported() -> None:
    lines = {"en": ["The company approved a quarterly increase from $1.30 to $1.62 per share."]}
    assert verdicts(lines, DIVIDEND)["en"] == [f.UNSUPPORTED]
    lines = {"en": ["The company approved a quarterly increase from $1.30 to $1.47 per share."]}
    assert verdicts(lines, DIVIDEND)["en"] == [f.SUPPORTED]


def test_a_rival_action_is_unsupported() -> None:
    assert verdicts(DISPOSAL_LINES, DISPOSAL) == {"ko": [f.SUPPORTED], "en": [f.SUPPORTED]}
    cancel = {
        "ko": ["회사는 임금협상 결과에 따라 직원에게 자기주식을 소각하기로 결정했어요"],
        "en": ["The company decided to cancel treasury shares based on the wage negotiation "
               "results."],
    }  # fmt: skip
    assert verdicts(cancel, DISPOSAL) == {"ko": [f.UNSUPPORTED], "en": [f.UNSUPPORTED]}
    special = {"en": ["The company said its Board declared a special cash dividend."]}
    assert verdicts(special, DIVIDEND)["en"] == [f.UNSUPPORTED]


def test_a_flipped_negation_is_flagged() -> None:
    faithful = {"ko": ["회사는 베어로보틱스의 해외 상장에 관해 결정된 사항이 없다고 밝혔어요."]}
    assert verdicts(faithful, CLARIFICATION)["ko"] == [f.SUPPORTED]
    flipped = {"ko": ["회사는 베어로보틱스의 나스닥 상장을 결정했다고 밝혔어요."]}
    result = f.check_section(flipped, CLARIFICATION)["ko"][0]
    assert result.verdict == f.PARTLY and "negation differs" in result.reasons


def test_hanja_and_refiling_wording_are_supported() -> None:
    lines = {
        "ko": ["회사는 한국경제가 미국 자회사 베어로보틱스의 나스닥 상장 추진을 보도했다고 밝혔어요.",
               "회사는 내용이 확정되거나 공시에서 정한 기한이 되면 다시 공시할 계획이라고 밝혔어요."],
        "en": ["The company said the Korea Economic Daily reported that its US subsidiary Bear "
               "Robotics was pursuing a Nasdaq listing.",
               "The company said it plans to file again when details are finalized or by the "
               "deadline it disclosed."],
    }  # fmt: skip
    assert verdicts(lines, CLARIFICATION) == {"ko": [f.SUPPORTED] * 2, "en": [f.SUPPORTED] * 2}


def test_an_ambiguous_korean_word_does_not_block() -> None:
    source = "Filing text:\nIn the fourth quarter, we produced over 434,000 vehicles and delivered "
    source += "over 418,000 vehicles."
    lines = {
        "en": ["The company reported quarterly production and deliveries of vehicles."],
        "ko": ["회사는 분기 차량 생산과 인도를 보고했어요"],  # 인도: delivery here, not India
    }
    assert verdicts(lines, source)["ko"] != [f.UNSUPPORTED]


def test_template_and_missing_source_rows() -> None:
    row = {"filing_id": "dart:1", "section": "summary", "input_sha256": "a" * 64,
           "review_state": "staged", "line1": "회사는 자기주식을 처분하기로 결정했어요",
           "line2": None, "line3": None}  # fmt: skip
    rows = [{**row, "lang": "ko", "model": "template"}]
    assert [r["verdict"] for r in f.check_pair(rows, f.Source("x"))] == [f.TEMPLATE]
    rows = [{**row, "lang": "ko", "model": "qwen/qwen3.8-27b"}]
    assert [r["verdict"] for r in f.check_pair(rows, None)] == [f.NO_SOURCE]


def test_records_carry_hashes_spans_and_version() -> None:
    rows = [
        {"filing_id": "dart:20260317000635", "section": "business", "lang": lang,
         "model": "qwen/qwen3.8-27b", "review_state": "approved", "input_sha256": "b" * 64,
         **{f"line{n}": line for n, line in enumerate(SKHYNIX_LINES[lang], start=1)}}
        for lang in ("ko", "en")
    ]  # fmt: skip
    records = f.check_rows(rows, {("dart:20260317000635", "business"): f.Source(SKHYNIX)})
    assert len(records) == 6
    first = next(r for r in records if r["lang"] == "ko" and r["line_no"] == 1)
    assert first["line_sha256"] == f.line_sha256(SKHYNIX_LINES["ko"][0])
    assert first["aligner_version"] == f.ALIGNER_VERSION
    assert first["coverage"] == "1.00"
    span = first["spans"][0]
    assert SKHYNIX[span["start"] : span["end"]] == span["text"]


# -- release gate --------------------------------------------------------------------------------


def _summary(line1: str, lang: str = "ko") -> dict[str, object]:
    return {"filing_id": "dart:1", "lang": lang, "section": "summary", "line1": line1,
            "line2": None, "line3": None, "input_sha256": "c" * 64}  # fmt: skip


def _record(line: str, verdict: str, **extra: object) -> dict[str, object]:
    return {"filing_id": "dart:1", "lang": "ko", "section": "summary", "line_no": 1,
            "line_sha256": f.line_sha256(line), "input_sha256": "c" * 64, "verdict": verdict,
            "aligner_version": f.ALIGNER_VERSION, "reasons": ["not in source: place.japan"],
            **extra}  # fmt: skip


@pytest.mark.parametrize(
    ("verdict", "policy", "blocked"),
    [
        (f.UNSUPPORTED, "unsupported", True),
        (f.PARTLY, "unsupported", False),
        (f.PARTLY, "partly", True),
        (f.SUPPORTED, "partly", False),
        (f.TEMPLATE, "partly", False),
        (f.NO_SOURCE, "unsupported", True),
        (f.UNSUPPORTED, "warn", False),
        (f.UNSUPPORTED, "off", False),
    ],
)
def test_the_policy_decides_what_blocks(verdict: str, policy: str, blocked: bool) -> None:
    line = "회사는 일본에 판매법인을 둔다고 밝혔어요"
    gate = f.ReleaseGate([_record(line, verdict)], policy)
    problems = gate.problems([_summary(line)])
    assert bool(problems) is blocked
    if blocked:
        assert problems[0].startswith(f"dart:1 ko/summary line 1: faithfulness {verdict}")


def test_a_line_needs_a_record_for_its_exact_text_and_aligner() -> None:
    line = "회사는 자기주식을 처분하기로 결정했어요"
    gate = f.ReleaseGate([_record("다른 문장", f.SUPPORTED)])
    assert "no faithfulness record" in gate.problems([_summary(line)])[0]
    old = f.ReleaseGate([_record(line, f.SUPPORTED, aligner_version="f0")])
    assert "no faithfulness record" in old.problems([_summary(line)])[0]
    assert f.ReleaseGate([_record(line, f.SUPPORTED)]).problems([_summary(line)]) == []


def test_an_owner_accepted_line_passes_and_is_counted() -> None:
    line = "회사는 일본에 판매법인을 둔다고 밝혔어요"
    accepted = [{"filing_id": "dart:1", "lang": "ko", "section": "summary", "line_no": 1,
                 "line_sha256": f.line_sha256(line), "input_sha256": "c" * 64,
                 "note": "the filing's table names Japan"}]  # fmt: skip
    gate = f.ReleaseGate([_record(line, f.UNSUPPORTED)], "unsupported", accepted)
    assert gate.problems([_summary(line)]) == []
    assert "accepted 1" in gate.notes[0]


def test_an_unknown_policy_is_refused() -> None:
    assert "is not one of" in f.ReleaseGate([], "strict").problems([])[0]


def test_records_round_trip_through_the_report_file(tmp_path) -> None:
    path = tmp_path / "faithfulness.jsonl"
    f.write_records(path, [_record("b", f.SUPPORTED), _record("a", f.PARTLY, line_no=0)])
    assert [r["line_no"] for r in f.read_records(path)] == [0, 1]
    assert f.read_records(tmp_path / "missing.jsonl") == []


def test_accept_writes_one_entry_per_line(tmp_path) -> None:
    rows = tmp_path / "approved.jsonl"
    rows.write_text(json.dumps({**_summary("회사는 일본에 판매법인을 둔다고 밝혔어요"),
                                "review_state": "approved"}, ensure_ascii=False) + "\n",
                    encoding="utf-8")  # fmt: skip
    accepted = tmp_path / "accepted.jsonl"
    args = ["accept", "--filing", "dart:1", "--section", "summary", "--lang", "ko", "--line",
            "1", "--note", "checked", "--rows", str(rows), "--accepted", str(accepted)]  # fmt: skip
    assert f.run(args) == 0 and f.run(args) == 0
    assert len(f.read_records(accepted)) == 1
    assert f.run([*args[:8], "2", *args[9:]]) == 1  # no line two


# -- eval ----------------------------------------------------------------------------------------


def test_the_eval_reproduces_the_recorded_numbers() -> None:
    """The numbers in D95 and the case study. Change them only with a new aligner version."""
    result = f.run_eval()
    assert len(result.pairs) == 73
    assert result.confusion() == {
        "supported": {"supported": 39, "partly": 6, "unsupported": 0},
        "partly": {"supported": 3, "partly": 1, "unsupported": 0},
        "unsupported": {"supported": 5, "partly": 5, "unsupported": 14},
    }
    unsupported = frozenset({f.UNSUPPORTED})
    assert result.precision_recall(unsupported) == (14, 14, 24)
    assert result.subset(split="dev").precision_recall(unsupported) == (10, 10, 15)
    assert result.subset(split="test").precision_recall(unsupported) == (4, 4, 9)
    flagged = frozenset({f.PARTLY, f.UNSUPPORTED})
    assert result.precision_recall(flagged) == (20, 26, 28)
    assert result.subset(split="test").precision_recall(flagged) == (6, 12, 11)
