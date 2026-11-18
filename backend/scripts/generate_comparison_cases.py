"""Generate contracts/comparison-cases.json.

Usage: python backend/scripts/generate_comparison_cases.py contracts/comparison-cases.json

Expected results are computed here with fractions.Fraction and a hand-written
half-up rule, independently of backend/app/compare, so the cases check the
calculator rather than echo it.
"""

import datetime
import json
import sys
from fractions import Fraction


def _output_path() -> str:
    args = sys.argv[1:]
    if len(args) != 1 or args[0].startswith("-"):
        print(
            "usage: python backend/scripts/generate_comparison_cases.py OUTPUT_JSON",
            file=sys.stderr,
        )
        sys.exit(2)
    return args[0]


OUTPUT = _output_path()

SAMSUNG = "dart:00126380"
NAVER = "dart:00266961"
MSFT = "sec:0000789019"
A = "synthetic:a"
B = "synthetic:b"


def half_up(q: Fraction) -> str:
    """Round to two places, ties away from zero, as a string with two places."""
    sign = -1 if q < 0 else 1
    scaled = abs(q) * 100
    whole = scaled.numerator // scaled.denominator
    rest = scaled - whole
    if rest >= Fraction(1, 2):
        whole += 1
    if whole == 0:
        sign = 1
    s = f"{whole // 100}.{whole % 100:02d}"
    return ("-" if sign < 0 else "") + s


def pct(num: str, base: str) -> str:
    return half_up(Fraction(num) * 100 / Fraction(base))


def exact(q: Fraction) -> str:
    """Canonical string of a terminating decimal: plain digits, no exponent,
    no trailing fractional zeros, no "-0"."""
    places = 0
    while (q * 10**places).denominator != 1:
        places += 1
        assert places < 60, "not a terminating decimal"
    scaled = q * 10**places
    digits = str(abs(scaled.numerator)).rjust(places + 1, "0")
    whole, fraction = (digits[:-places], digits[-places:]) if places else (digits, "")
    fraction = fraction.rstrip("0")
    text = whole + ("." + fraction if fraction else "")
    return ("-" if q < 0 else "") + text


def canon(value: str) -> str:
    return exact(Fraction(value))


def sub(a: str, b: str) -> str:
    return exact(Fraction(a) - Fraction(b))


def fact(company, metric, value, start, end, currency="KRW", unit=None,
         basis="consolidated", restated=False):
    return {
        "company_id": company,
        "metric": metric,
        "value": value,
        "unit": unit if unit is not None else currency,
        "currency": currency,
        "basis": basis,
        "period_start": start,
        "period_end": end,
        "is_restated": restated,
    }


def fy(year, company=A, metric="revenue", value="100", **kw):
    return fact(company, metric, value, f"{year}-01-01", f"{year}-12-31", **kw)


def msft_fy(year, metric, value, **kw):
    return fact(MSFT, metric, value, f"{year - 1}-07-01", f"{year}-06-30",
                currency="USD", basis="consolidated_entity_total", **kw)


cases = []


def add(case_id, description, input_, expected):
    cases.append({"id": case_id, "description": description,
                  "input": input_, "expected": expected})


def length(f):
    """Days in the period, counting both end days."""
    start = datetime.date.fromisoformat(f["period_start"])
    end = datetime.date.fromisoformat(f["period_end"])
    return (end - start).days + 1


def ends_differ(prior, current):
    """Month-days differ, unless both are the last day of February."""
    def last_of_february(text):
        day = datetime.date.fromisoformat(text)
        return day.month == 2 and (day + datetime.timedelta(days=1)).month == 3
    a, b = prior["period_end"], current["period_end"]
    if last_of_february(a) and last_of_february(b):
        return False
    return a[5:] != b[5:]


def yoy_case(case_id, description, metric, prior, current, *, order=None):
    facts = [prior, current] if order is None else order
    add(case_id, description, {"kind": "yoy", "metric": metric, "facts": facts}, {
        "result": {
            "company_id": current["company_id"],
            "metric": metric,
            "prior_value": canon(prior["value"]),
            "current_value": canon(current["value"]),
            "delta": sub(current["value"], prior["value"]),
            "percent_change": pct(sub(current["value"], prior["value"]), prior["value"]),
            "currency": current["currency"],
            "unit": current["unit"],
            "prior_period_start": prior["period_start"],
            "prior_period_end": prior["period_end"],
            "current_period_start": current["period_start"],
            "current_period_end": current["period_end"],
            "prior_is_restated": prior["is_restated"],
            "current_is_restated": current["is_restated"],
            "period_ends_differ": ends_differ(prior, current),
            "period_lengths_differ": abs(length(prior) - length(current)) >= 7,
        }
    })


def margin_result(revenue, income):
    return {
        "company_id": revenue["company_id"],
        "revenue": canon(revenue["value"]),
        "operating_income": canon(income["value"]),
        "operating_margin": pct(income["value"], revenue["value"]),
        "currency": revenue["currency"],
        "period_start": revenue["period_start"],
        "period_end": revenue["period_end"],
        "is_restated": revenue["is_restated"] or income["is_restated"],
    }


def margin_case(case_id, description, revenue, income):
    add(case_id, description,
        {"kind": "operating_margin", "metric": "operating_margin",
         "facts": [revenue, income]},
        {"result": margin_result(revenue, income)})


def refuse(case_id, description, input_, reason, detail):
    add(case_id, description, input_, {"refusal": reason, "detail": detail})


def yoy_in(metric, facts):
    return {"kind": "yoy", "metric": metric, "facts": facts}


def margin_in(facts, metric="operating_margin"):
    return {"kind": "operating_margin", "metric": metric, "facts": facts}


def cross_in(metric, measure, facts):
    return {"kind": "cross_company", "metric": metric, "measure": measure,
            "facts": facts}


# --- Verified figures (filing-agent pilot snapshot, 2026-09-07) -------------
s22_rev = fy(2022, SAMSUNG, "revenue", "302231360000000")
s23_rev = fy(2023, SAMSUNG, "revenue", "258935494000000")
s22_op = fy(2022, SAMSUNG, "operating_income", "43376630000000")
s23_op = fy(2023, SAMSUNG, "operating_income", "6566976000000")
s22_ni = fy(2022, SAMSUNG, "net_income", "55654077000000")
s23_ni = fy(2023, SAMSUNG, "net_income", "15487100000000")
n23_rev = fy(2023, NAVER, "revenue", "9670643576585")
n23_op = fy(2023, NAVER, "operating_income", "1488820269608")
m23_rev = msft_fy(2023, "revenue", "211915000000")
m24_rev = msft_fy(2024, "revenue", "245122000000")
m23_op = msft_fy(2023, "operating_income", "88523000000")
m24_op = msft_fy(2024, "operating_income", "109433000000")

yoy_case("yoy-samsung-fy2023-revenue",
         "Samsung Electronics consolidated revenue, FY2023 against FY2022 "
         "(verified pilot figures; the expected change is -14.33%).",
         "revenue", s22_rev, s23_rev)
assert cases[-1]["expected"]["result"]["percent_change"] == "-14.33"
yoy_case("yoy-samsung-fy2023-operating-income",
         "Samsung Electronics consolidated operating income, FY2023 against "
         "FY2022 (verified pilot figures).",
         "operating_income", s22_op, s23_op)
yoy_case("yoy-samsung-fy2023-net-income",
         "Samsung Electronics consolidated net income, FY2023 against FY2022 "
         "(verified pilot figures).",
         "net_income", s22_ni, s23_ni)
yoy_case("yoy-microsoft-fy2024-revenue",
         "Microsoft revenue, fiscal years ending June 30 (verified pilot figures).",
         "revenue", m23_rev, m24_rev)
yoy_case("yoy-microsoft-fy2024-operating-income",
         "Microsoft operating income, fiscal years ending June 30 "
         "(verified pilot figures).",
         "operating_income", m23_op, m24_op)
yoy_case("yoy-facts-in-reverse-order",
         "Facts may arrive newest first; the earlier period end is the baseline.",
         "revenue", s22_rev, s23_rev, order=[s23_rev, s22_rev])

# --- Synthetic normal cases --------------------------------------------------
yoy_case("yoy-eps-fractional-values",
         "Synthetic earnings per share with fractional values.",
         "eps", fy(2023, metric="eps", value="9.68", currency="USD",
                   unit="USD_PER_SHARE"),
         fy(2024, metric="eps", value="11.80", currency="USD",
            unit="USD_PER_SHARE"))
yoy_case("yoy-unchanged", "Synthetic: no change gives zero delta and 0.00%.",
         "revenue", fy(2023, value="100"), fy(2024, value="100"))
yoy_case("yoy-negative-current-positive-baseline",
         "A figure that turns negative against a positive baseline is a valid "
         "comparison; the sign stays on the delta and the percentage.",
         "operating_income", fy(2023, metric="operating_income", value="100"),
         fy(2024, metric="operating_income", value="-50"))
yoy_case("yoy-leap-year",
         "A leap year against a common year with the same month-day bounds.",
         "revenue", fy(2023, value="100"), fy(2024, value="120"))
yoy_case("yoy-quarter",
         "Synthetic first quarter against the same quarter a year earlier.",
         "revenue", fact(A, "revenue", "200", "2024-01-01", "2024-03-31"),
         fact(A, "revenue", "250", "2025-01-01", "2025-03-31"))
yoy_case("yoy-repeating-decimal-down",
         "One third more: 33.333... rounds to 33.33.",
         "revenue", fy(2023, value="3"), fy(2024, value="4"))
yoy_case("yoy-repeating-decimal-up",
         "Two thirds more: 66.666... rounds to 66.67.",
         "revenue", fy(2023, value="3"), fy(2024, value="5"))

# --- Rounding: ROUND_HALF_UP, ties away from zero -----------------------------
yoy_case("round-half-up-positive",
         "Exact result 12.345 rounds to 12.35.",
         "revenue", fy(2023, value="1000"), fy(2024, value="1123.45"))
assert cases[-1]["expected"]["result"]["percent_change"] == "12.35"
yoy_case("round-half-up-negative",
         "Exact result -12.345 rounds away from zero to -12.35.",
         "revenue", fy(2023, value="1000"), fy(2024, value="876.55"))
assert cases[-1]["expected"]["result"]["percent_change"] == "-12.35"
yoy_case("round-below-half",
         "Exact result 12.34499 rounds down to 12.34.",
         "revenue", fy(2023, value="1000"), fy(2024, value="1123.4499"))
yoy_case("round-half-up-carry",
         "Exact result 9.995 rounds to 10.00.",
         "revenue", fy(2023, value="1000"), fy(2024, value="1099.95"))
assert cases[-1]["expected"]["result"]["percent_change"] == "10.00"
yoy_case("round-half-up-smallest-positive",
         "Exact result 0.005 rounds to 0.01; banker's rounding would give 0.00.",
         "revenue", fy(2023, value="1000"), fy(2024, value="1000.05"))
assert cases[-1]["expected"]["result"]["percent_change"] == "0.01"
yoy_case("round-half-up-smallest-negative",
         "Exact result -0.005 rounds away from zero to -0.01.",
         "revenue", fy(2023, value="1000"), fy(2024, value="999.95"))
assert cases[-1]["expected"]["result"]["percent_change"] == "-0.01"
yoy_case("round-tiny-negative-is-zero",
         "A change too small to show rounds to 0.00, never -0.00.",
         "revenue", fy(2023, value="1000000"), fy(2024, value="999999.99"))
assert cases[-1]["expected"]["result"]["percent_change"] == "0.00"

# --- Zero and negative baseline ---------------------------------------------
refuse("baseline-zero", "No percentage of a zero baseline.",
       yoy_in("net_income", [fy(2023, metric="net_income", value="0"),
                             fy(2024, metric="net_income", value="500")]),
       "incompatible_comparison", "nonpositive_baseline")
refuse("baseline-negative-to-positive",
       "No percentage when the baseline is a loss.",
       yoy_in("net_income", [fy(2023, metric="net_income", value="-500"),
                             fy(2024, metric="net_income", value="1000")]),
       "incompatible_comparison", "nonpositive_baseline")
refuse("baseline-negative-to-negative",
       "No percentage between two losses.",
       yoy_in("operating_income",
              [fy(2023, metric="operating_income", value="-800"),
               fy(2024, metric="operating_income", value="-200")]),
       "incompatible_comparison", "nonpositive_baseline")

# --- Currency ---------------------------------------------------------------
refuse("currency-mismatch-yoy", "A KRW figure against a USD figure.",
       yoy_in("revenue", [fy(2023, value="100", currency="KRW"),
                          fy(2024, value="120", currency="USD")]),
       "incompatible_currency", "currency_mismatch")
refuse("currency-mismatch-margin",
       "Operating margin from revenue and operating income in different currencies.",
       margin_in([fy(2024, metric="revenue", value="1000", currency="KRW"),
                  fy(2024, metric="operating_income", value="100",
                     currency="USD")]),
       "incompatible_currency", "currency_mismatch")
refuse("cross-company-absolute-amount-currencies",
       "Revenue amounts of a KRW and a USD reporter are never set side by side.",
       cross_in("revenue", "absolute_amount", [s23_rev, m24_rev]),
       "incompatible_currency", "absolute_amount_across_currencies")

# --- Basis ------------------------------------------------------------------
refuse("basis-separate-yoy",
       "Separate (parent-only) statements are not supported.",
       yoy_in("revenue", [fy(2023, value="100", basis="separate"),
                          fy(2024, value="120", basis="separate")]),
       "unsupported_basis", "unsupported_basis")
refuse("basis-separate-margin",
       "Operating margin from separate statements is not supported.",
       margin_in([fy(2024, metric="revenue", value="1000", basis="separate"),
                  fy(2024, metric="operating_income", value="100",
                     basis="separate")]),
       "unsupported_basis", "unsupported_basis")
refuse("basis-mismatch-yoy",
       "Two supported bases may not be mixed within one company's comparison.",
       yoy_in("revenue", [fy(2023, value="100", basis="consolidated"),
                          fy(2024, value="120",
                             basis="consolidated_entity_total")]),
       "incompatible_comparison", "basis_mismatch")

# --- Period shape -----------------------------------------------------------
refuse("period-end-mismatch",
       "A December year-end against a June year-end.",
       yoy_in("revenue", [fact(A, "revenue", "100", "2022-07-01", "2023-06-30"),
                          fy(2024, value="120")]),
       "incompatible_comparison", "period_end_mismatch")
refuse("period-quarter-against-year",
       "A first quarter against a full year.",
       yoy_in("revenue", [fy(2024, value="400"),
                          fact(A, "revenue", "120", "2025-01-01", "2025-03-31")]),
       "incompatible_comparison", "period_end_mismatch")
refuse("period-start-mismatch",
       "Same year-end but a nine-month period against a twelve-month one.",
       yoy_in("revenue", [fact(A, "revenue", "100", "2023-04-01", "2023-12-31"),
                          fy(2024, value="120")]),
       "incompatible_comparison", "period_length_mismatch")
refuse("period-two-year-span",
       "Matching month-days but a two-year period against a one-year one.",
       yoy_in("revenue", [fy(2022, value="100"),
                          fact(A, "revenue", "220", "2023-01-01", "2024-12-31")]),
       "incompatible_comparison", "period_length_mismatch")
refuse("margin-period-mismatch",
       "Revenue and operating income from different periods.",
       margin_in([fy(2024, metric="revenue", value="1000"),
                  fy(2023, metric="operating_income", value="100")]),
       "incompatible_comparison", "period_end_mismatch")

# --- Missing periods --------------------------------------------------------
refuse("missing-prior-year", "Only the current year is available.",
       yoy_in("revenue", [fy(2024, value="120")]),
       "missing_period", "missing_fact")
refuse("missing-intervening-year",
       "FY2025 against FY2023 skips a year.",
       yoy_in("revenue", [fy(2023, value="100"), fy(2025, value="130")]),
       "missing_period", "non_consecutive_years")
refuse("missing-margin-input",
       "Operating margin without an operating income figure.",
       margin_in([fy(2024, metric="revenue", value="1000")]),
       "missing_period", "missing_fact")
refuse("missing-period-cross-company",
       "One company in a growth comparison lacks its prior year.",
       cross_in("revenue", "growth_rate", [s22_rev, s23_rev, m24_rev]),
       "missing_period", "missing_fact")

# --- Restated figures -------------------------------------------------------
yoy_case("restated-prior",
         "The prior-year figure is a restated one; the label is carried through.",
         "revenue", fy(2023, value="100", restated=True), fy(2024, value="110"))
yoy_case("restated-current",
         "The current figure is restated; the label is carried through.",
         "revenue", fy(2023, value="100"), fy(2024, value="90", restated=True))
margin_case("restated-margin-input",
            "A restated revenue figure marks the derived margin as restated.",
            fy(2024, metric="revenue", value="1000", restated=True),
            fy(2024, metric="operating_income", value="150"))

# --- Operating margin -------------------------------------------------------
margin_case("margin-samsung-fy2023",
            "Samsung Electronics FY2023 operating margin (verified pilot figures).",
            s23_rev, s23_op)
margin_case("margin-microsoft-fy2024",
            "Microsoft FY2024 operating margin (verified pilot figures).",
            m24_rev, m24_op)
margin_case("margin-negative-operating-income",
            "An operating loss against positive revenue gives a negative margin.",
            fy(2024, metric="revenue", value="1000"),
            fy(2024, metric="operating_income", value="-75"))
margin_case("margin-half-up-positive", "Exact margin 12.345 rounds to 12.35.",
            fy(2024, metric="revenue", value="1000"),
            fy(2024, metric="operating_income", value="123.45"))
margin_case("margin-half-up-negative",
            "Exact margin -12.345 rounds away from zero to -12.35.",
            fy(2024, metric="revenue", value="1000"),
            fy(2024, metric="operating_income", value="-123.45"))
refuse("margin-revenue-zero", "No margin when revenue is zero.",
       margin_in([fy(2024, metric="revenue", value="0"),
                  fy(2024, metric="operating_income", value="-10")]),
       "incompatible_comparison", "nonpositive_baseline")
refuse("margin-revenue-negative", "No margin when revenue is negative.",
       margin_in([fy(2024, metric="revenue", value="-5"),
                  fy(2024, metric="operating_income", value="1")]),
       "incompatible_comparison", "nonpositive_baseline")

# --- Cross-company ----------------------------------------------------------
def cross_rates(entries):
    return [{"company_id": c, "rate": r, "period_start": b, "period_end": e,
             "is_restated": s}
            for c, r, b, e, s in entries]


add("cross-company-growth-samsung-microsoft",
    "Revenue growth of a KRW and a USD reporter side by side: rates only, "
    "with the standards and year-end caveat.",
    cross_in("revenue", "growth_rate", [s22_rev, s23_rev, m23_rev, m24_rev]),
    {"result": {
        "metric": "revenue", "measure": "growth_rate",
        "caveat": "cross_company_standards_and_year_ends",
        "same_period_end": False,
        "companies": cross_rates([
            (SAMSUNG, pct(sub(s23_rev["value"], s22_rev["value"]),
                          s22_rev["value"]), "2023-01-01", "2023-12-31", False),
            (MSFT, pct(sub(m24_rev["value"], m23_rev["value"]),
                       m23_rev["value"]), "2023-07-01", "2024-06-30", False),
        ])}})
add("cross-company-margin-three",
    "Operating margins of Samsung Electronics, NAVER and Microsoft.",
    cross_in("operating_margin", "operating_margin",
             [s23_rev, s23_op, n23_rev, n23_op, m23_rev, m23_op]),
    {"result": {
        "metric": "operating_margin", "measure": "operating_margin",
        "caveat": "cross_company_standards_and_year_ends",
        "same_period_end": False,
        "companies": cross_rates([
            (SAMSUNG, pct(s23_op["value"], s23_rev["value"]), "2023-01-01", "2023-12-31", False),
            (NAVER, pct(n23_op["value"], n23_rev["value"]), "2023-01-01", "2023-12-31", False),
            (MSFT, pct(m23_op["value"], m23_rev["value"]), "2022-07-01", "2023-06-30", False),
        ])}})
add("cross-company-margin-same-year-end",
    "Two KRW reporters with the same year-end still carry the caveat.",
    cross_in("operating_margin", "operating_margin",
             [s23_rev, s23_op, n23_rev, n23_op]),
    {"result": {
        "metric": "operating_margin", "measure": "operating_margin",
        "caveat": "cross_company_standards_and_year_ends",
        "same_period_end": True,
        "companies": cross_rates([
            (SAMSUNG, pct(s23_op["value"], s23_rev["value"]), "2023-01-01", "2023-12-31", False),
            (NAVER, pct(n23_op["value"], n23_rev["value"]), "2023-01-01", "2023-12-31", False),
        ])}})
add("cross-company-growth-restated",
    "A restated baseline in one company is labelled on that company's rate.",
    cross_in("revenue", "growth_rate",
             [fy(2023, A, value="100", restated=True), fy(2024, A, value="110"),
              fy(2023, B, value="200"), fy(2024, B, value="190")]),
    {"result": {
        "metric": "revenue", "measure": "growth_rate",
        "caveat": "cross_company_standards_and_year_ends",
        "same_period_end": True,
        "companies": cross_rates([
            (A, "10.00", "2024-01-01", "2024-12-31", True),
            (B, "-5.00", "2024-01-01", "2024-12-31", False),
        ])}})
refuse("cross-company-absolute-amount-same-currency",
       "Amounts are not compared across companies even in one currency.",
       cross_in("revenue", "absolute_amount", [s23_rev, n23_rev]),
       "incompatible_comparison", "absolute_amount_across_companies")
refuse("cross-company-single-company",
       "A cross-company comparison needs at least two companies.",
       cross_in("revenue", "growth_rate", [s22_rev, s23_rev]),
       "ambiguous_request", "single_company")
refuse("cross-company-nonpositive-baseline",
       "One company's loss-making baseline refuses the whole comparison.",
       cross_in("net_income", "growth_rate",
                [fy(2023, A, "net_income", "-10"), fy(2024, A, "net_income", "5"),
                 fy(2023, B, "net_income", "10"), fy(2024, B, "net_income", "12")]),
       "incompatible_comparison", "nonpositive_baseline")
refuse("cross-company-margin-wrong-metric",
       "A margin comparison must name the operating_margin metric.",
       cross_in("revenue", "operating_margin", [s23_rev, s23_op, n23_rev, n23_op]),
       "metric_out_of_scope", "metric_not_supported_for_kind")

# --- Metric scope -----------------------------------------------------------
refuse("metric-unknown", "A metric outside the vocabulary.",
       yoy_in("free_cash_flow",
              [fy(2023, metric="free_cash_flow", value="100"),
               fy(2024, metric="free_cash_flow", value="120")]),
       "metric_out_of_scope", "unknown_metric")
refuse("metric-margin-yoy",
       "Year-over-year change of a margin is not offered in v1.",
       yoy_in("operating_margin",
              [fy(2023, metric="operating_margin", value="10"),
               fy(2024, metric="operating_margin", value="12")]),
       "metric_out_of_scope", "metric_not_supported_for_kind")
refuse("metric-margin-kind-wrong-metric",
       "The operating_margin kind with a reported metric.",
       margin_in([fy(2024, metric="revenue", value="1000"),
                  fy(2024, metric="operating_income", value="100")],
                 metric="revenue"),
       "metric_out_of_scope", "metric_not_supported_for_kind")

# --- Ambiguous requests -----------------------------------------------------
refuse("ambiguous-no-metric", "The request names no metric.",
       yoy_in(None, [fy(2023, value="100"), fy(2024, value="120")]),
       "ambiguous_request", "metric_not_specified")
refuse("ambiguous-duplicate-period",
       "An original and a restated figure for the same period, with no choice made.",
       yoy_in("revenue", [fy(2024, value="100"),
                          fy(2024, value="102", restated=True)]),
       "ambiguous_request", "duplicate_period")
refuse("ambiguous-three-facts", "Three years given for a two-period comparison.",
       yoy_in("revenue", [fy(2022, value="90"), fy(2023, value="100"),
                          fy(2024, value="120")]),
       "ambiguous_request", "too_many_facts")
refuse("ambiguous-no-measure",
       "A cross-company request that names no measure.",
       cross_in("revenue", None, [s23_rev, n23_rev]),
       "ambiguous_request", "measure_not_specified")
refuse("ambiguous-two-revenues",
       "Two revenue figures for one margin.",
       margin_in([fy(2024, metric="revenue", value="1000"),
                  fy(2024, metric="revenue", value="1010", restated=True),
                  fy(2024, metric="operating_income", value="100")]),
       "ambiguous_request", "duplicate_period")

# --- Other incompatible pairs -----------------------------------------------
refuse("incompatible-company",
       "Year over year across two companies.",
       yoy_in("revenue", [fy(2023, A, value="100"), fy(2024, B, value="120")]),
       "incompatible_comparison", "company_mismatch")
refuse("incompatible-unit",
       "Same currency, different unit.",
       yoy_in("eps", [fy(2023, metric="eps", value="5", unit="KRW_PER_SHARE"),
                      fy(2024, metric="eps", value="6", unit="KRW")]),
       "incompatible_comparison", "unit_mismatch")
refuse("incompatible-fact-metric",
       "A fact whose metric differs from the request.",
       yoy_in("revenue", [fy(2023, value="100"),
                          fy(2024, metric="net_income", value="120")]),
       "incompatible_comparison", "metric_mismatch")

# --- Period edge cases ------------------------------------------------------
refuse("period-overlapping",
       "Two-year periods a year apart overlap by a year; neither is a baseline "
       "for the other.",
       yoy_in("revenue", [fact(A, "revenue", "200", "2022-01-01", "2023-12-31"),
                          fact(A, "revenue", "220", "2023-01-01", "2024-12-31")]),
       "incompatible_comparison", "overlapping_periods")
yoy_case("period-february-leap-year-end",
         "A year ending on February 29 against one ending on February 28: both "
         "end on the last day of February, so the ends count as equal and no "
         "flag is set (D82).",
         "revenue", fact(A, "revenue", "100", "2023-03-01", "2024-02-29"),
         fact(A, "revenue", "110", "2024-03-01", "2025-02-28"))
assert cases[-1]["expected"]["result"]["period_ends_differ"] is False


def usd(value, start, end):
    return fact(A, "revenue", value, start, end, currency="USD")


def flags(ends, lengths):
    result = cases[-1]["expected"]["result"]
    assert (result["period_ends_differ"], result["period_lengths_differ"]) == (ends, lengths)


# --- 52/53-week fiscal years (D82) -------------------------------------------
yoy_case("yoy-fiscal-weeks-apple-like",
         "Apple-like 52-week years ending 2024-09-28 and 2025-09-27: full "
         "fiscal years a year apart whose ends differ by a day compare, with "
         "period_ends_differ set.",
         "revenue", usd("391035000000", "2023-10-01", "2024-09-28"),
         usd("416161000000", "2024-09-29", "2025-09-27"))
flags(True, False)
yoy_case("yoy-fiscal-weeks-53-week-year",
         "A 53-week year (371 days) after a 52-week year (364): the end moves "
         "six days later in month-day; both flags are set.",
         "revenue", usd("100", "2021-09-26", "2022-09-24"),
         usd("98", "2022-09-25", "2023-09-30"))
flags(True, True)
yoy_case("yoy-fiscal-weeks-across-new-year",
         "A year ending on December 30 against the next ending on January 1: "
         "the ends sit two days apart across the new year, so they compare.",
         "revenue", usd("100", "2023-01-01", "2023-12-30"),
         usd("105", "2023-12-31", "2025-01-01"))
flags(True, False)
yoy_case("yoy-equal-ends-no-flag",
         "Equal year-end month-days keep the calendar-year path and carry no "
         "flag.",
         "revenue", fy(2024, value="100"), fy(2025, value="110"))
flags(False, False)
yoy_case("yoy-fiscal-weeks-shortest-year",
         "A 357-day prior year, the shortest accepted, against a 364-day year: "
         "the lengths differ by exactly a week, so both flags are set.",
         "revenue", usd("100", "2023-10-08", "2024-09-28"),
         usd("110", "2024-09-29", "2025-09-27"))
flags(True, True)
yoy_case("yoy-fiscal-weeks-drift-seven-days-early",
         "The later end falls exactly seven days before the anniversary, the "
         "earliest accepted; the lengths differ by six days, so only the "
         "ends flag is set.",
         "revenue", usd("100", "2023-10-01", "2024-09-28"),
         usd("110", "2024-09-29", "2025-09-21"))
flags(True, False)
yoy_case("yoy-fiscal-weeks-year-9999",
         "Years ending in 9998 and 9999, the last representable year: the "
         "one-year anniversary is in range, so they compare.",
         "revenue", usd("100", "9997-12-31", "9998-12-29"),
         usd("110", "9998-12-30", "9999-12-28"))
flags(True, False)
refuse("fiscal-weeks-anniversary-past-9999",
       "Ends on 9999-01-01 and 9999-12-31: the only anniversary to test is in "
       "the year 10000, which cannot be represented, so it refuses.",
       yoy_in("revenue", [usd("100", "9998-01-03", "9999-01-01"),
                          usd("110", "9999-01-02", "9999-12-31")]),
       "incompatible_comparison", "period_end_mismatch")
refuse("fiscal-weeks-end-too-far",
       "Ends 2024-09-28 and 2025-10-10: both look like full years, but the "
       "later end is twelve days past the anniversary, so it refuses.",
       yoy_in("revenue", [usd("100", "2023-10-01", "2024-09-28"),
                          usd("110", "2024-10-12", "2025-10-10")]),
       "incompatible_comparison", "period_end_mismatch")
refuse("fiscal-weeks-end-eight-days-early",
       "Two full years whose ends are 357 days apart: the later end falls "
       "eight days before the anniversary, past the seven-day limit.",
       yoy_in("revenue", [usd("100", "2023-10-01", "2024-09-28"),
                          usd("110", "2024-09-29", "2025-09-20")]),
       "incompatible_comparison", "period_end_mismatch")
refuse("fiscal-weeks-end-gap-limit",
       "Two 364-day years whose ends are 372 days apart, seven days past the "
       "anniversary: lengths and drift pass, and the end-gap limit decides "
       "before the gap between the periods is checked.",
       yoy_in("revenue", [usd("100", "2023-10-01", "2024-09-28"),
                          usd("110", "2024-10-07", "2025-10-05")]),
       "incompatible_comparison", "period_end_mismatch")
refuse("fiscal-weeks-two-week-gap",
       "A 357-day year that starts fifteen days after the prior year ends: "
       "two weeks are missing between the periods, so it refuses.",
       yoy_in("revenue", [usd("100", "2023-10-01", "2024-09-28"),
                          usd("110", "2024-10-13", "2025-10-04")]),
       "missing_period", "non_consecutive_years")
refuse("fiscal-weeks-half-year-against-full-year",
       "A half year against a full fiscal year whose end differs by a day: "
       "the half year is not a full fiscal year, so it refuses.",
       yoy_in("revenue", [usd("100", "2023-10-01", "2024-09-28"),
                          usd("55", "2025-03-30", "2025-09-27")]),
       "incompatible_comparison", "period_end_mismatch")
refuse("fiscal-weeks-two-years-apart",
       "Two 52/53-week years with a year between them: the later end is near "
       "the second anniversary, so a year is missing.",
       yoy_in("revenue", [usd("100", "2022-09-25", "2023-09-30"),
                          usd("110", "2024-09-29", "2025-09-27")]),
       "missing_period", "non_consecutive_years")
refuse("fiscal-weeks-overlapping",
       "A 53-week year that starts before the prior 52-week year ends: the "
       "periods share days, so neither is a baseline.",
       yoy_in("revenue", [usd("100", "2023-09-24", "2024-09-21"),
                          usd("110", "2024-09-21", "2025-09-26")]),
       "incompatible_comparison", "overlapping_periods")
# Fiscal-year order: lengths, overlap, anniversary, years apart, end gap, gap
# between periods, baseline. Years apart against end gap is
# fiscal-weeks-two-years-apart; end gap against the gap is fiscal-weeks-end-gap-limit.
refuse("order-fiscal-length-before-overlap",
       "A half year that overlaps a full year with a different end: the length "
       "decides.",
       yoy_in("revenue", [usd("100", "2023-10-01", "2024-09-28"),
                          usd("60", "2024-06-01", "2024-11-30")]),
       "incompatible_comparison", "period_end_mismatch")
refuse("order-fiscal-overlap-before-anniversary",
       "A full year that overlaps the prior one and ends far from its "
       "anniversary: the overlap decides.",
       yoy_in("revenue", [usd("100", "2023-10-01", "2024-09-28"),
                          usd("110", "2024-03-01", "2025-02-28")]),
       "incompatible_comparison", "overlapping_periods")
refuse("order-fiscal-gap-before-baseline",
       "Two weeks missing between the periods and a zero baseline: the gap "
       "decides.",
       yoy_in("revenue", [usd("0", "2023-10-01", "2024-09-28"),
                          usd("110", "2024-10-13", "2025-10-04")]),
       "missing_period", "non_consecutive_years")
refuse("cross-company-growth-length-mismatch",
       "One company's full years against another's first quarters.",
       cross_in("revenue", "growth_rate",
                [fy(2023, A, value="100"), fy(2024, A, value="110"),
                 fact(B, "revenue", "30", "2024-01-01", "2024-03-31"),
                 fact(B, "revenue", "33", "2025-01-01", "2025-03-31")]),
       "incompatible_comparison", "period_length_mismatch")
refuse("cross-company-margin-length-mismatch",
       "One company's full-year margin against another's quarterly margin.",
       cross_in("operating_margin", "operating_margin",
                [fy(2024, A, "revenue", "1000"), fy(2024, A, "operating_income", "100"),
                 fact(B, "revenue", "300", "2025-01-01", "2025-03-31"),
                 fact(B, "operating_income", "30", "2025-01-01", "2025-03-31")]),
       "incompatible_comparison", "period_length_mismatch")

# --- Check order: each case fails two checks, and the earlier one decides -----
# Top level: measure, metric, basis, absolute amount, company count, per company.
refuse("order-measure-before-metric",
       "No measure and no metric: the missing measure is named first.",
       cross_in(None, None, [s23_rev, n23_rev]),
       "ambiguous_request", "measure_not_specified")
refuse("order-metric-before-basis-yoy",
       "An unknown metric on separate statements: the metric decides.",
       yoy_in("free_cash_flow",
              [fy(2023, metric="free_cash_flow", value="100", basis="separate"),
               fy(2024, metric="free_cash_flow", value="120", basis="separate")]),
       "metric_out_of_scope", "unknown_metric")
refuse("order-metric-before-basis-margin",
       "The margin kind with a reported metric on separate statements.",
       margin_in([fy(2024, metric="revenue", value="1000", basis="separate"),
                  fy(2024, metric="operating_income", value="100", basis="separate")],
                 metric="revenue"),
       "metric_out_of_scope", "metric_not_supported_for_kind")
refuse("order-metric-before-basis-cross-company",
       "Growth of a margin across companies, one on separate statements.",
       cross_in("operating_margin", "growth_rate",
                [fy(2023, A, "operating_margin", "10", basis="separate"),
                 fy(2024, A, "operating_margin", "12", basis="separate"),
                 fy(2023, B, "operating_margin", "20"),
                 fy(2024, B, "operating_margin", "22")]),
       "metric_out_of_scope", "metric_not_supported_for_kind")
refuse("order-basis-before-absolute-amount",
       "Amounts in two currencies, one on separate statements: the basis decides.",
       cross_in("revenue", "absolute_amount",
                [fy(2023, A, value="100", basis="separate"),
                 fy(2023, B, value="100", currency="USD")]),
       "unsupported_basis", "unsupported_basis")
refuse("order-absolute-amount-before-single-company",
       "Amounts asked of a single company are refused as an amount comparison.",
       cross_in("revenue", "absolute_amount",
                [fy(2023, A, value="100"), fy(2024, A, value="110")]),
       "incompatible_comparison", "absolute_amount_across_companies")
refuse("order-single-company-before-per-company",
       "One company with one figure: the company count decides.",
       cross_in("revenue", "growth_rate", [fy(2024, A, value="110")]),
       "ambiguous_request", "single_company")
refuse("order-first-company-decides",
       "Two companies fail different checks; the first listed decides.",
       cross_in("net_income", "growth_rate",
                [fy(2023, B, "net_income", "-10"), fy(2024, B, "net_income", "5"),
                 fy(2024, A, "net_income", "12")]),
       "incompatible_comparison", "nonpositive_baseline")
refuse("order-per-company-before-length",
       "A quarterly company with a loss-making baseline: its own check decides "
       "before the period lengths are compared.",
       cross_in("net_income", "growth_rate",
                [fy(2023, A, "net_income", "100"), fy(2024, A, "net_income", "110"),
                 fact(B, "net_income", "-3", "2024-01-01", "2024-03-31"),
                 fact(B, "net_income", "4", "2025-01-01", "2025-03-31")]),
       "incompatible_comparison", "nonpositive_baseline")

# Year over year: count, metric, company, basis, currency, unit, period-end
# month-day, period-start month-day, same period, overlap, length, gap, baseline.
refuse("order-count-before-metric",
       "Three figures, one for another metric: the count decides.",
       yoy_in("revenue", [fy(2022, value="90"), fy(2023, value="100"),
                          fy(2024, metric="net_income", value="120")]),
       "ambiguous_request", "too_many_facts")
refuse("order-yoy-metric-before-company",
       "Another company and another metric: the metric decides.",
       yoy_in("revenue", [fy(2023, A, value="100"),
                          fy(2024, B, metric="net_income", value="120")]),
       "incompatible_comparison", "metric_mismatch")
refuse("order-yoy-company-before-basis",
       "Another company on another supported basis: the company decides.",
       yoy_in("revenue", [fy(2023, A, value="100"),
                          fy(2024, B, value="120", basis="consolidated_entity_total")]),
       "incompatible_comparison", "company_mismatch")
refuse("order-yoy-basis-before-currency",
       "Another basis and another currency: the basis decides.",
       yoy_in("revenue", [fy(2023, value="100"),
                          fy(2024, value="120", currency="USD",
                             basis="consolidated_entity_total")]),
       "incompatible_comparison", "basis_mismatch")
refuse("order-yoy-unit-before-period-end",
       "Another unit and another year-end: the unit decides.",
       yoy_in("eps", [fact(A, "eps", "5", "2022-07-01", "2023-06-30",
                           unit="KRW_PER_SHARE"),
                      fy(2024, metric="eps", value="6")]),
       "incompatible_comparison", "unit_mismatch")
refuse("order-yoy-period-start-before-same-period",
       "Same year-end and year, different start: the length differs before the "
       "two are read as one period.",
       yoy_in("revenue", [fact(A, "revenue", "75", "2024-04-01", "2024-12-31"),
                          fy(2024, value="100")]),
       "incompatible_comparison", "period_length_mismatch")
refuse("order-yoy-overlap-before-length",
       "A two-year period starting with the prior year: the overlap decides.",
       yoy_in("revenue", [fy(2023, value="100"),
                          fact(A, "revenue", "220", "2023-01-01", "2024-12-31")]),
       "incompatible_comparison", "overlapping_periods")
refuse("order-yoy-gap-before-baseline",
       "A skipped year and a zero baseline: the skipped year decides.",
       yoy_in("revenue", [fy(2023, value="0"), fy(2025, value="100")]),
       "missing_period", "non_consecutive_years")

# Operating margin: metric, duplicate, missing, company, basis, currency, unit,
# period end, period start, baseline.
refuse("order-margin-metric-before-duplicate",
       "Two revenue figures and a net income figure: the stray metric decides.",
       margin_in([fy(2024, metric="revenue", value="1000"),
                  fy(2024, metric="revenue", value="1010", restated=True),
                  fy(2024, metric="net_income", value="80")]),
       "incompatible_comparison", "metric_mismatch")
refuse("order-margin-duplicate-before-missing",
       "Two revenue figures and no operating income: the duplicate decides.",
       margin_in([fy(2024, metric="revenue", value="1000"),
                  fy(2024, metric="revenue", value="1010", restated=True)]),
       "ambiguous_request", "duplicate_period")
refuse("order-margin-company-before-basis",
       "Inputs from two companies on two bases: the company decides.",
       margin_in([fy(2024, A, "revenue", "1000"),
                  fy(2024, B, "operating_income", "100",
                     basis="consolidated_entity_total")]),
       "incompatible_comparison", "company_mismatch")
refuse("order-margin-basis-before-currency",
       "Inputs on two bases and in two currencies: the basis decides.",
       margin_in([fy(2024, metric="revenue", value="1000"),
                  fy(2024, metric="operating_income", value="100", currency="USD",
                     basis="consolidated_entity_total")]),
       "incompatible_comparison", "basis_mismatch")
refuse("order-margin-unit-before-period-end",
       "Inputs in two units and from two years: the unit decides.",
       margin_in([fy(2024, metric="revenue", value="1000"),
                  fy(2023, metric="operating_income", value="100", unit="KRW_THOUSANDS")]),
       "incompatible_comparison", "unit_mismatch")
refuse("order-margin-period-start-before-baseline",
       "Inputs with different starts and zero revenue: the period decides.",
       margin_in([fact(A, "revenue", "0", "2024-04-01", "2024-12-31"),
                  fy(2024, metric="operating_income", value="100")]),
       "incompatible_comparison", "period_length_mismatch")

ids = [c["id"] for c in cases]
assert len(ids) == len(set(ids)), "duplicate ids"

contract = {
    "version": 1,
    "description": (
        "Shared comparison cases for the Python and Swift calculators. "
        "Rules: docs/comparison-rules.md."
    ),
    "rounding": "ROUND_HALF_UP to two decimal places, ties away from zero, "
                "applied only to the rounded_fields",
    "number_comparison": (
        "Results compare as canonical strings. A rounded field has exactly two "
        "fraction digits and a minus sign only when it is below zero, so -0.00 "
        "never appears. An exact field is plain decimal notation with no exponent, "
        "no trailing fractional zeros, no trailing point and no -0."
    ),
    "rounded_fields": ["percent_change", "operating_margin", "rate"],
    "exact_fields": ["prior_value", "current_value", "delta", "revenue",
                     "operating_income"],
    "kinds": ["yoy", "operating_margin", "cross_company"],
    "cross_company_measures": ["growth_rate", "operating_margin", "absolute_amount"],
    "supported_bases": ["consolidated", "consolidated_entity_total"],
    "caveats": ["cross_company_standards_and_year_ends"],
    "refusal_reasons": [
        "ambiguous_request", "unsupported_basis", "metric_out_of_scope",
        "missing_period", "incompatible_currency", "incompatible_comparison",
    ],
    "refusal_details": {
        "ambiguous_request": ["metric_not_specified", "measure_not_specified",
                              "too_many_facts", "duplicate_period",
                              "single_company"],
        "unsupported_basis": ["unsupported_basis"],
        "metric_out_of_scope": ["unknown_metric", "metric_not_supported_for_kind"],
        "missing_period": ["missing_fact", "non_consecutive_years"],
        "incompatible_currency": ["currency_mismatch",
                                  "absolute_amount_across_currencies"],
        "incompatible_comparison": ["absolute_amount_across_companies",
                                    "company_mismatch", "metric_mismatch",
                                    "basis_mismatch", "unit_mismatch",
                                    "period_end_mismatch",
                                    "period_length_mismatch",
                                    "overlapping_periods",
                                    "nonpositive_baseline"],
    },
    "cases": cases,
}
with open(OUTPUT, "w", encoding="utf-8") as fh:
    json.dump(contract, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
print(len(cases), "cases")
