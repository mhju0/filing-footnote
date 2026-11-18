"""Exact-decimal comparisons of Financial Facts, with named refusals.

The rules live in ``docs/comparison-rules.md`` and the shared cases in
``contracts/comparison-cases.json``; the Swift calculator must pass the same cases.
"""

import calendar
import datetime
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Context, Decimal, localcontext
from enum import StrEnum

from app.financials.vocabulary import DerivedMetric, ReportedMetric

SUPPORTED_BASES = frozenset({"consolidated", "consolidated_entity_total"})
CROSS_COMPANY_CAVEAT = "cross_company_standards_and_year_ends"

_HUNDREDTH = Decimal("0.01")
# Subtraction, division and the final rounding all run in this context, never
# the caller's thread context. 34 digits keeps subtraction of any reported figure
# exact and leaves the final half-up step as the only rounding that can change a
# result; Swift's Decimal keeps 38 digits.
_PRECISION = 34
_ARITHMETIC = Context(prec=_PRECISION, rounding=ROUND_HALF_EVEN)
# Periods of companies set side by side may differ by a leap day or a
# 52/53-week year, not by a quarter.
_MAX_CROSS_COMPANY_LENGTH_DIFFERENCE_DAYS = 7
# A 52/53-week fiscal year runs 364 or 371 days, counting both ends; a calendar
# year runs 365 or 366. Both fall in this range, and so does the step from one
# such year end to the next.
_FISCAL_YEAR_DAYS = range(357, 372)
# How far a 52/53-week year end may drift from the prior end's anniversary.
_MAX_YEAR_END_DRIFT_DAYS = 7
# Two periods whose lengths differ by this much: one of them has an extra week.
_WEEK_DAYS = 7


class RefusalReason(StrEnum):
    ambiguous_request = "ambiguous_request"
    unsupported_basis = "unsupported_basis"
    metric_out_of_scope = "metric_out_of_scope"
    missing_period = "missing_period"
    incompatible_currency = "incompatible_currency"
    incompatible_comparison = "incompatible_comparison"


class RefusalDetail(StrEnum):
    metric_not_specified = "metric_not_specified"
    measure_not_specified = "measure_not_specified"
    too_many_facts = "too_many_facts"
    duplicate_period = "duplicate_period"
    single_company = "single_company"
    unsupported_basis = "unsupported_basis"
    unknown_metric = "unknown_metric"
    metric_not_supported_for_kind = "metric_not_supported_for_kind"
    missing_fact = "missing_fact"
    non_consecutive_years = "non_consecutive_years"
    currency_mismatch = "currency_mismatch"
    absolute_amount_across_currencies = "absolute_amount_across_currencies"
    absolute_amount_across_companies = "absolute_amount_across_companies"
    company_mismatch = "company_mismatch"
    metric_mismatch = "metric_mismatch"
    basis_mismatch = "basis_mismatch"
    unit_mismatch = "unit_mismatch"
    period_end_mismatch = "period_end_mismatch"
    period_length_mismatch = "period_length_mismatch"
    overlapping_periods = "overlapping_periods"
    nonpositive_baseline = "nonpositive_baseline"


class CrossCompanyMeasure(StrEnum):
    growth_rate = "growth_rate"
    operating_margin = "operating_margin"
    absolute_amount = "absolute_amount"


@dataclass(frozen=True)
class Fact:
    """One reported figure as the calculator needs it."""

    company_id: str
    metric: str
    value: Decimal
    unit: str
    currency: str | None
    basis: str
    period_start: datetime.date
    period_end: datetime.date
    is_restated: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal):
            raise TypeError("Fact value must be a Decimal")
        if not self.value.is_finite():
            raise ValueError("Fact value must be finite")
        if self.period_start > self.period_end:
            raise ValueError("Fact period_start must not follow period_end")


@dataclass(frozen=True)
class Refusal:
    reason: RefusalReason
    detail: RefusalDetail


@dataclass(frozen=True)
class YearOverYear:
    company_id: str
    metric: str
    prior_value: Decimal
    current_value: Decimal
    delta: Decimal
    percent_change: Decimal
    currency: str | None
    unit: str
    prior_period_start: datetime.date
    prior_period_end: datetime.date
    current_period_start: datetime.date
    current_period_end: datetime.date
    prior_is_restated: bool
    current_is_restated: bool
    # True when the two periods end on different month-days: consecutive
    # 52/53-week fiscal years.
    period_ends_differ: bool
    # True when the two lengths differ by a week or more: a 53-week year
    # against a 52-week one.
    period_lengths_differ: bool


@dataclass(frozen=True)
class OperatingMargin:
    company_id: str
    revenue: Decimal
    operating_income: Decimal
    operating_margin: Decimal
    currency: str | None
    period_start: datetime.date
    period_end: datetime.date
    is_restated: bool


@dataclass(frozen=True)
class CompanyRate:
    company_id: str
    rate: Decimal
    period_start: datetime.date
    period_end: datetime.date
    is_restated: bool


@dataclass(frozen=True)
class CrossCompany:
    metric: str
    measure: CrossCompanyMeasure
    companies: tuple[CompanyRate, ...]
    same_period_end: bool
    caveat: str = CROSS_COMPANY_CAVEAT


def percentage(numerator: Decimal, baseline: Decimal) -> Decimal | None:
    """Return ``numerator / baseline * 100`` rounded half-up to two places.

    ``None`` when the baseline is zero or negative: a percentage of such a
    baseline reads as a direction it does not have.
    """
    if baseline <= 0:
        return None
    with localcontext(_ARITHMETIC):
        rounded = (numerator * 100 / baseline).quantize(
            _HUNDREDTH, rounding=ROUND_HALF_UP
        )
    # A tiny negative change rounds to -0.00; it is shown as 0.00.
    return rounded.copy_abs() if rounded.is_zero() else rounded


def _refuse(reason: RefusalReason, detail: RefusalDetail) -> Refusal:
    return Refusal(reason=reason, detail=detail)


def _check_metric(
    metric: str | None, allowed: frozenset[str]
) -> Refusal | None:
    if metric is None or not metric.strip():
        return _refuse(
            RefusalReason.ambiguous_request, RefusalDetail.metric_not_specified
        )
    known = {m.value for m in ReportedMetric} | {m.value for m in DerivedMetric}
    if metric not in known:
        return _refuse(RefusalReason.metric_out_of_scope, RefusalDetail.unknown_metric)
    if metric not in allowed:
        return _refuse(
            RefusalReason.metric_out_of_scope,
            RefusalDetail.metric_not_supported_for_kind,
        )
    return None


def _check_bases(facts: Sequence[Fact]) -> Refusal | None:
    if any(fact.basis not in SUPPORTED_BASES for fact in facts):
        return _refuse(
            RefusalReason.unsupported_basis, RefusalDetail.unsupported_basis
        )
    return None


def _days(fact: Fact) -> int:
    """The period's length, counting both end days."""
    return (fact.period_end - fact.period_start).days + 1


def _is_last_of_february(date: datetime.date) -> bool:
    return date.month == 2 and date.day == (29 if calendar.isleap(date.year) else 28)


def _same_end_day(a: datetime.date, b: datetime.date) -> bool:
    """Same month-day, or both the last day of February."""
    return (a.month, a.day) == (b.month, b.day) or (
        _is_last_of_february(a) and _is_last_of_february(b)
    )


def _anniversary(date: datetime.date, years: int) -> datetime.date | None:
    """The same month-day ``years`` later (February 29 becomes February 28);
    ``None`` past the last representable year."""
    year = date.year + years
    if year > datetime.MAXYEAR:
        return None
    if (date.month, date.day) == (2, 29) and not calendar.isleap(year):
        return datetime.date(year, 2, 28)
    return date.replace(year=year)


def _years_between_ends(prior: Fact, current: Fact) -> int | None:
    """The whole number of years, at least one, whose anniversary of the prior
    end lies within a week of the current end; ``None`` when there is none."""
    base = current.period_end.year - prior.period_end.year
    for years in (base - 1, base, base + 1):
        if years < 1:
            continue
        anniversary = _anniversary(prior.period_end, years)
        if (
            anniversary is not None
            and abs((current.period_end - anniversary).days) <= _MAX_YEAR_END_DRIFT_DAYS
        ):
            return years
    return None


def _check_fiscal_years(prior: Fact, current: Fact) -> Refusal | None:
    """Periods whose ends differ in month-day compare only as consecutive full
    fiscal years, as 52/53-week years are (docs/DECISIONS.md D82)."""
    if _days(prior) not in _FISCAL_YEAR_DAYS or _days(current) not in _FISCAL_YEAR_DAYS:
        return _refuse(
            RefusalReason.incompatible_comparison, RefusalDetail.period_end_mismatch
        )
    if current.period_start <= prior.period_end:
        return _refuse(
            RefusalReason.incompatible_comparison, RefusalDetail.overlapping_periods
        )
    years = _years_between_ends(prior, current)
    if years is None:
        return _refuse(
            RefusalReason.incompatible_comparison, RefusalDetail.period_end_mismatch
        )
    if years > 1:
        return _refuse(
            RefusalReason.missing_period, RefusalDetail.non_consecutive_years
        )
    if (current.period_end - prior.period_end).days not in _FISCAL_YEAR_DAYS:
        return _refuse(
            RefusalReason.incompatible_comparison, RefusalDetail.period_end_mismatch
        )
    # The current year starts the day after the prior one ends: no days between.
    if (current.period_start - prior.period_end).days > 1:
        return _refuse(
            RefusalReason.missing_period, RefusalDetail.non_consecutive_years
        )
    return None


_REPORTED = frozenset(m.value for m in ReportedMetric)
_MARGIN = frozenset({DerivedMetric.operating_margin.value})


def _year_over_year(metric: str, facts: Sequence[Fact]) -> YearOverYear | Refusal:
    if len(facts) < 2:
        return _refuse(RefusalReason.missing_period, RefusalDetail.missing_fact)
    if len(facts) > 2:
        return _refuse(RefusalReason.ambiguous_request, RefusalDetail.too_many_facts)
    prior, current = sorted(facts, key=lambda fact: fact.period_end)
    if prior.metric != metric or current.metric != metric:
        return _refuse(
            RefusalReason.incompatible_comparison, RefusalDetail.metric_mismatch
        )
    if prior.company_id != current.company_id:
        return _refuse(
            RefusalReason.incompatible_comparison, RefusalDetail.company_mismatch
        )
    if prior.basis != current.basis:
        return _refuse(
            RefusalReason.incompatible_comparison, RefusalDetail.basis_mismatch
        )
    if prior.currency != current.currency:
        return _refuse(
            RefusalReason.incompatible_currency, RefusalDetail.currency_mismatch
        )
    if prior.unit != current.unit:
        return _refuse(
            RefusalReason.incompatible_comparison, RefusalDetail.unit_mismatch
        )

    def month_day(date: datetime.date) -> tuple[int, int]:
        return date.month, date.day

    ends_differ = not _same_end_day(prior.period_end, current.period_end)
    if ends_differ:
        refusal = _check_fiscal_years(prior, current)
        if refusal is not None:
            return refusal
    else:
        if month_day(prior.period_start) != month_day(current.period_start):
            return _refuse(
                RefusalReason.incompatible_comparison,
                RefusalDetail.period_length_mismatch,
            )
        end_gap = current.period_end.year - prior.period_end.year
        start_gap = current.period_start.year - prior.period_start.year
        if end_gap == 0 and start_gap == 0:
            return _refuse(
                RefusalReason.ambiguous_request, RefusalDetail.duplicate_period
            )
        if current.period_start <= prior.period_end:
            return _refuse(
                RefusalReason.incompatible_comparison,
                RefusalDetail.overlapping_periods,
            )
        if start_gap != end_gap:
            return _refuse(
                RefusalReason.incompatible_comparison,
                RefusalDetail.period_length_mismatch,
            )
        if end_gap > 1:
            return _refuse(
                RefusalReason.missing_period, RefusalDetail.non_consecutive_years
            )

    with localcontext(_ARITHMETIC):
        delta = current.value - prior.value
    percent = percentage(delta, prior.value)
    if percent is None:
        return _refuse(
            RefusalReason.incompatible_comparison, RefusalDetail.nonpositive_baseline
        )
    return YearOverYear(
        company_id=current.company_id,
        metric=metric,
        prior_value=prior.value,
        current_value=current.value,
        delta=delta,
        percent_change=percent,
        currency=current.currency,
        unit=current.unit,
        prior_period_start=prior.period_start,
        prior_period_end=prior.period_end,
        current_period_start=current.period_start,
        current_period_end=current.period_end,
        prior_is_restated=prior.is_restated,
        current_is_restated=current.is_restated,
        period_ends_differ=ends_differ,
        period_lengths_differ=abs(_days(prior) - _days(current)) >= _WEEK_DAYS,
    )


def _operating_margin(facts: Sequence[Fact]) -> OperatingMargin | Refusal:
    if any(
        fact.metric
        not in (ReportedMetric.revenue.value, ReportedMetric.operating_income.value)
        for fact in facts
    ):
        return _refuse(
            RefusalReason.incompatible_comparison, RefusalDetail.metric_mismatch
        )
    revenues = [f for f in facts if f.metric == ReportedMetric.revenue.value]
    incomes = [f for f in facts if f.metric == ReportedMetric.operating_income.value]
    if len(revenues) > 1 or len(incomes) > 1:
        return _refuse(
            RefusalReason.ambiguous_request, RefusalDetail.duplicate_period
        )
    if not revenues or not incomes:
        return _refuse(RefusalReason.missing_period, RefusalDetail.missing_fact)
    revenue, income = revenues[0], incomes[0]
    if revenue.company_id != income.company_id:
        return _refuse(
            RefusalReason.incompatible_comparison, RefusalDetail.company_mismatch
        )
    if revenue.basis != income.basis:
        return _refuse(
            RefusalReason.incompatible_comparison, RefusalDetail.basis_mismatch
        )
    if revenue.currency != income.currency:
        return _refuse(
            RefusalReason.incompatible_currency, RefusalDetail.currency_mismatch
        )
    if revenue.unit != income.unit:
        return _refuse(
            RefusalReason.incompatible_comparison, RefusalDetail.unit_mismatch
        )
    if revenue.period_end != income.period_end:
        return _refuse(
            RefusalReason.incompatible_comparison, RefusalDetail.period_end_mismatch
        )
    if revenue.period_start != income.period_start:
        return _refuse(
            RefusalReason.incompatible_comparison,
            RefusalDetail.period_length_mismatch,
        )

    margin = percentage(income.value, revenue.value)
    if margin is None:
        return _refuse(
            RefusalReason.incompatible_comparison, RefusalDetail.nonpositive_baseline
        )
    return OperatingMargin(
        company_id=revenue.company_id,
        revenue=revenue.value,
        operating_income=income.value,
        operating_margin=margin,
        currency=revenue.currency,
        period_start=revenue.period_start,
        period_end=revenue.period_end,
        is_restated=revenue.is_restated or income.is_restated,
    )


def year_over_year(
    metric: str | None, facts: Sequence[Fact]
) -> YearOverYear | Refusal:
    """Compare one company's figure with the same figure a year earlier."""
    refusal = _check_metric(metric, _REPORTED) or _check_bases(facts)
    if refusal is not None:
        return refusal
    assert metric is not None
    return _year_over_year(metric, facts)


def operating_margin(
    metric: str | None, facts: Sequence[Fact]
) -> OperatingMargin | Refusal:
    """Derive operating income as a percentage of revenue for one period."""
    refusal = _check_metric(metric, _MARGIN) or _check_bases(facts)
    if refusal is not None:
        return refusal
    return _operating_margin(facts)


def cross_company(
    metric: str | None, measure: str | None, facts: Sequence[Fact]
) -> CrossCompany | Refusal:
    """Set growth rates or operating margins of several companies side by side.

    Amounts are never compared across companies, so no currency is converted.
    """
    try:
        chosen = CrossCompanyMeasure(measure) if measure is not None else None
    except ValueError:
        chosen = None
    if chosen is None:
        return _refuse(
            RefusalReason.ambiguous_request, RefusalDetail.measure_not_specified
        )
    allowed = _MARGIN if chosen is CrossCompanyMeasure.operating_margin else _REPORTED
    refusal = _check_metric(metric, allowed) or _check_bases(facts)
    if refusal is not None:
        return refusal
    assert metric is not None

    if chosen is CrossCompanyMeasure.absolute_amount:
        if len({fact.currency for fact in facts}) > 1:
            return _refuse(
                RefusalReason.incompatible_currency,
                RefusalDetail.absolute_amount_across_currencies,
            )
        return _refuse(
            RefusalReason.incompatible_comparison,
            RefusalDetail.absolute_amount_across_companies,
        )

    by_company: dict[str, list[Fact]] = {}
    for fact in facts:
        by_company.setdefault(fact.company_id, []).append(fact)
    if len(by_company) < 2:
        return _refuse(RefusalReason.ambiguous_request, RefusalDetail.single_company)

    rates: list[CompanyRate] = []
    for company_id, company_facts in by_company.items():
        if chosen is CrossCompanyMeasure.growth_rate:
            result = _year_over_year(metric, company_facts)
            if isinstance(result, Refusal):
                return result
            rates.append(
                CompanyRate(
                    company_id=company_id,
                    rate=result.percent_change,
                    period_start=result.current_period_start,
                    period_end=result.current_period_end,
                    is_restated=result.prior_is_restated
                    or result.current_is_restated,
                )
            )
        else:
            margin = _operating_margin(company_facts)
            if isinstance(margin, Refusal):
                return margin
            rates.append(
                CompanyRate(
                    company_id=company_id,
                    rate=margin.operating_margin,
                    period_start=margin.period_start,
                    period_end=margin.period_end,
                    is_restated=margin.is_restated,
                )
            )
    lengths = [(rate.period_end - rate.period_start).days for rate in rates]
    if max(lengths) - min(lengths) > _MAX_CROSS_COMPANY_LENGTH_DIFFERENCE_DAYS:
        return _refuse(
            RefusalReason.incompatible_comparison,
            RefusalDetail.period_length_mismatch,
        )
    return CrossCompany(
        metric=metric,
        measure=chosen,
        companies=tuple(rates),
        same_period_end=len({rate.period_end for rate in rates}) == 1,
    )
