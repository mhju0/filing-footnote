"""The Python calculator against the shared comparison cases."""

import ast
import datetime
import json
import re
from dataclasses import fields, is_dataclass
from decimal import ROUND_UP, Decimal, localcontext
from enum import Enum
from pathlib import Path

import pytest

from app.compare import (
    CROSS_COMPANY_CAVEAT,
    Fact,
    Refusal,
    RefusalDetail,
    RefusalReason,
    cross_company,
    operating_margin,
    year_over_year,
)

ROOT = Path(__file__).parents[2]
CONTRACT = json.loads(
    (ROOT / "contracts" / "comparison-cases.json").read_text(encoding="utf-8")
)
ROUNDED_FIELDS = frozenset(CONTRACT["rounded_fields"])
EXACT_FIELDS = frozenset(CONTRACT["exact_fields"])
DECIMAL_STRING = re.compile(r"-?\d+(\.\d+)?")
ROUNDED_STRING = re.compile(r"-?(0|[1-9]\d*)\.\d\d")
EXACT_STRING = re.compile(r"-?(0|[1-9]\d*)(\.\d*[1-9])?")
FACT_KEYS = {
    "company_id",
    "metric",
    "value",
    "unit",
    "currency",
    "basis",
    "period_start",
    "period_end",
    "is_restated",
}


def _fact(raw: dict) -> Fact:
    return Fact(
        company_id=raw["company_id"],
        metric=raw["metric"],
        value=Decimal(raw["value"]),
        unit=raw["unit"],
        currency=raw["currency"],
        basis=raw["basis"],
        period_start=datetime.date.fromisoformat(raw["period_start"]),
        period_end=datetime.date.fromisoformat(raw["period_end"]),
        is_restated=raw["is_restated"],
    )


def _run(case_input: dict):
    facts = [_fact(raw) for raw in case_input["facts"]]
    kind = case_input["kind"]
    if kind == "yoy":
        return year_over_year(case_input["metric"], facts)
    if kind == "operating_margin":
        return operating_margin(case_input["metric"], facts)
    if kind == "cross_company":
        return cross_company(case_input["metric"], case_input["measure"], facts)
    raise AssertionError(f"unknown kind {kind}")


def _plain(value):
    """Turn a result into the contract's JSON shape, keeping Decimals."""
    if is_dataclass(value):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime.date):
        return value.isoformat()
    return value


def _canonical_exact(value: Decimal) -> str:
    """The contract's exact-field form: plain digits, no trailing zeros, no -0."""
    if value.is_zero():
        return "0"
    with localcontext() as context:
        context.prec = 60
        return format(value.normalize(), "f")


def _is_canonical_rounded(text: str) -> bool:
    return bool(ROUNDED_STRING.fullmatch(text)) and text != "-0.00"


def _is_canonical_exact(text: str) -> bool:
    return bool(EXACT_STRING.fullmatch(text)) and text != "-0"


def _assert_matches(actual, expected, path: str = "result") -> None:
    if isinstance(expected, dict):
        assert isinstance(actual, dict), path
        assert actual.keys() == expected.keys(), path
        for key, value in expected.items():
            _assert_matches(actual[key], value, f"{path}.{key}")
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), path
        for index, (item, wanted) in enumerate(zip(actual, expected, strict=True)):
            _assert_matches(item, wanted, f"{path}[{index}]")
    elif path.rsplit(".", 1)[-1] in ROUNDED_FIELDS:
        assert isinstance(actual, Decimal), path
        assert str(actual) == expected, f"{path}: {actual} != {expected}"
    elif path.rsplit(".", 1)[-1] in EXACT_FIELDS:
        assert isinstance(actual, Decimal), path
        assert _canonical_exact(actual) == expected, f"{path}: {actual} != {expected}"
    else:
        assert actual == expected, f"{path}: {actual!r} != {expected!r}"


@pytest.mark.parametrize(
    "case", CONTRACT["cases"], ids=[case["id"] for case in CONTRACT["cases"]]
)
def test_comparison_case(case: dict) -> None:
    outcome = _run(case["input"])
    expected = case["expected"]
    if "refusal" in expected:
        assert outcome == Refusal(
            reason=RefusalReason(expected["refusal"]),
            detail=RefusalDetail(expected["detail"]),
        )
    else:
        assert not isinstance(outcome, Refusal), outcome
        _assert_matches(_plain(outcome), expected["result"])


def test_results_ignore_the_callers_decimal_context() -> None:
    ids = {
        "yoy-samsung-fy2023-revenue",
        "margin-samsung-fy2023",
        "cross-company-growth-samsung-microsoft",
        # 12.34499 would round up to 12.35 if any step used six digits.
        "round-below-half",
    }
    chosen = [case for case in CONTRACT["cases"] if case["id"] in ids]
    assert len(chosen) == len(ids)
    for case in chosen:
        with localcontext() as context:
            context.prec = 6
            context.rounding = ROUND_UP
            outcome = _run(case["input"])
        _assert_matches(_plain(outcome), case["expected"]["result"])


def test_contract_schema() -> None:
    assert CONTRACT["version"] == 1
    assert CONTRACT["refusal_reasons"] == [reason.value for reason in RefusalReason]
    assert set(CONTRACT["refusal_details"]) == set(CONTRACT["refusal_reasons"])
    listed_details = [
        detail for details in CONTRACT["refusal_details"].values() for detail in details
    ]
    assert sorted(listed_details) == sorted(detail.value for detail in RefusalDetail)
    assert CONTRACT["caveats"] == [CROSS_COMPANY_CAVEAT]

    cases = CONTRACT["cases"]
    assert len(cases) >= 40
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids))

    reason_counts = dict.fromkeys(CONTRACT["refusal_reasons"], 0)
    for case in cases:
        assert set(case) == {"id", "description", "input", "expected"}, case["id"]
        assert case["description"].strip(), case["id"]
        case_input = case["input"]
        assert case_input["kind"] in CONTRACT["kinds"], case["id"]
        expected_input_keys = {"kind", "metric", "facts"}
        if case_input["kind"] == "cross_company":
            expected_input_keys.add("measure")
        assert set(case_input) == expected_input_keys, case["id"]
        for raw in case_input["facts"]:
            assert set(raw) == FACT_KEYS, case["id"]
            assert isinstance(raw["value"], str), case["id"]
            assert DECIMAL_STRING.fullmatch(raw["value"]), case["id"]
            assert isinstance(raw["is_restated"], bool), case["id"]
            datetime.date.fromisoformat(raw["period_start"])
            datetime.date.fromisoformat(raw["period_end"])

        expected = case["expected"]
        if "refusal" in expected:
            assert set(expected) == {"refusal", "detail"}, case["id"]
            assert expected["detail"] in CONTRACT["refusal_details"][expected["refusal"]]
            reason_counts[expected["refusal"]] += 1
        else:
            assert set(expected) == {"result"}, case["id"]
            stack = [expected["result"]]
            while stack:
                node = stack.pop()
                if isinstance(node, list):
                    stack.extend(node)
                elif isinstance(node, dict):
                    for key, value in node.items():
                        if key in ROUNDED_FIELDS:
                            assert isinstance(value, str), (case["id"], key)
                            assert _is_canonical_rounded(value), (case["id"], key)
                        elif key in EXACT_FIELDS:
                            assert isinstance(value, str), (case["id"], key)
                            assert _is_canonical_exact(value), (case["id"], key)
                        else:
                            assert not isinstance(value, float), (case["id"], key)
                            stack.append(value)

    assert all(count >= 2 for count in reason_counts.values()), reason_counts


def test_samsung_fy2023_revenue_reproduces_the_pilot_snapshot() -> None:
    case = next(c for c in CONTRACT["cases"] if c["id"] == "yoy-samsung-fy2023-revenue")
    values = [raw["value"] for raw in case["input"]["facts"]]
    assert values == ["302231360000000", "258935494000000"]
    assert case["expected"]["result"]["percent_change"] == "-14.33"


def test_compare_package_contains_no_float() -> None:
    package = ROOT / "backend" / "app" / "compare"
    sources = sorted(package.glob("*.py"))
    assert sources
    for source in sources:
        text = source.read_text(encoding="utf-8")
        assert "float" not in text.lower(), source.name
        for node in ast.walk(ast.parse(text, filename=source.name)):
            if isinstance(node, ast.Constant):
                assert not isinstance(node.value, (float, complex)), (
                    source.name,
                    node.lineno,
                )
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != "float", (source.name, node.lineno)
            if isinstance(node, ast.Name):
                assert node.id != "float", (source.name, node.lineno)
            if isinstance(node, ast.Attribute):
                assert node.attr != "float", (source.name, node.lineno)
