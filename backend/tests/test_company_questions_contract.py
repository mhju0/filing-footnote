"""The "Ask about this company" contract (D99): fixed questions and answer sentences.

The app's answers are fixed sentences chosen by code, so the neutrality guard checks them
here once, as it checks every generated summary line. FootnoteKit's contract tests hold
the Swift copies of these strings to the same file.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from app.llm.neutrality_guard import check_line, line_warnings

CONTRACT = Path(__file__).parents[2] / "contracts" / "company-questions.json"

# The guard's word rules: no digits, judgement words, predictions or advice, and the right
# language. N4 (every line attributed to the company, ending in 밝혔어요 or "said") and N6's
# summary shape are not applied: these sentences describe what the app does, in its own
# voice, and some are two sentences long.
SENTENCE_RULES = {"N1", "N2", "N3", "N7", "N8"}
# Questions are the reader's words ("Should I buy this?"), not statements the app makes.
QUESTION_RULES = {"N1", "N8"}


def _contract() -> dict[str, Any]:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _texts(kind: str) -> list[tuple[str, str, str]]:
    return [(entry["key"], lang, entry[lang]) for entry in _contract()[kind] for lang in ("ko", "en")]


def test_contract_shape() -> None:
    contract = _contract()
    assert contract["version"] == 1
    intents = [entry["key"] for entry in contract["intents"]]
    sentences = [entry["key"] for entry in contract["sentences"]]
    assert intents == [
        "should_buy",
        "fundamentals",
        "recent_trend",
        "profit_or_loss",
        "revenue",
        "next_quarter_revenue",
    ]
    assert len(set(sentences)) == len(sentences)
    assert all(re.fullmatch(r"[a-z]+(?:_[a-z]+)*", key) for key in intents + sentences)
    kinds = {entry["key"]: entry["kind"] for entry in contract["intents"]}
    assert {key for key, kind in kinds.items() if kind == "deflected"} == {
        "should_buy",
        "next_quarter_revenue",
    }
    assert set(kinds.values()) == {"answered", "deflected"}


@pytest.mark.parametrize(("key", "lang", "text"), _texts("sentences"))
def test_sentences_pass_the_neutrality_guard(key: str, lang: str, text: str) -> None:
    failures = [v for v in check_line(text, lang) if v.rule_id in SENTENCE_RULES]
    assert failures == [], (key, lang, failures)
    assert line_warnings(text, lang) == [], (key, lang)


@pytest.mark.parametrize(("key", "lang", "text"), _texts("intents"))
def test_questions_hold_no_digits(key: str, lang: str, text: str) -> None:
    failures = [v for v in check_line(text, lang) if v.rule_id in QUESTION_RULES]
    assert failures == [], (key, lang, failures)


@pytest.mark.parametrize(("kind",), [("sentences",), ("intents",)])
def test_no_em_dashes(kind: str) -> None:
    assert [key for key, _, text in _texts(kind) if "—" in text] == []


def test_the_guard_catches_a_bad_sentence() -> None:
    # The filter above must not hide the rules it keeps.
    rules = {v.rule_id for v in check_line("Revenue will likely surge by 5% next quarter.", "en")}
    assert {"N1", "N2", "N3"} <= rules
    rules = {v.rule_id for v in check_line("지금이 매수 기회라고 보여요.", "ko")}
    assert {"N3", "N7"} <= rules
