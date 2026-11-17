# Comparison rules

Filing Footnote compares figures only when the comparison means what it appears to
mean. Every comparison shows its inputs and its arithmetic. When a comparison would
mislead, the app refuses it and names the reason.

These rules are the contract for two calculators: Python (`backend/app/compare/`) and,
later, Swift. Both must pass every case in `contracts/comparison-cases.json`. When this
document and the case file disagree, fix one of them; neither silently wins.

The rules follow the comparison logic of the filing-agent prototype
(`slice/financial.py`, `calculated()`), extended to operating margin and to
cross-company comparisons.

## Inputs

A comparison takes reported figures (facts). Each fact carries a company, a metric, an
exact decimal value, a unit, a currency, a basis, a period start and end date, and a
flag saying whether the filing restated it.

Values are decimal strings in the contract and `Decimal` in code. No step uses binary
floating point.

## Kinds of comparison

### Year over year (`yoy`)

One company, one metric, two periods a year apart.

- `delta` is the current value minus the prior value, exact.
- `percent_change` is `delta × 100 ÷ prior value`, rounded as described below.
- The earlier period end is the baseline, whatever order the facts arrive in.

Both facts must share company, metric, basis, currency and unit. Their period start
dates must have the same month and day, and so must their period end dates. The end
years must be exactly one apart, and the start years must move by the same amount as
the end years, so both periods have the same length. A leap day inside one of the
periods is allowed. The current period must start after the prior period ends: two
two-year periods a year apart share a year, so neither is a baseline for the other
(`overlapping_periods`).

Two year-ends fail the month-day check and are refused in v1:

- A fiscal year that ends on a different date each year (a 52/53-week year).
- A year that ends on the last day of February: February 29 in a leap year against
  February 28 in the next year is refused as `period_end_mismatch`, even though both
  are the last day of the month.

### Operating margin (`operating_margin`)

One company, one period: `operating income × 100 ÷ revenue`, rounded as below.

The revenue and operating income facts must share company, basis, currency, unit,
period start and period end. An operating loss on positive revenue gives a negative
margin, which is shown.

### Cross-company (`cross_company`)

Two or more companies side by side. Only rates are compared:

- `growth_rate`: each company's year-over-year `percent_change` for one metric, each
  checked by the year-over-year rules on its own.
- `operating_margin`: each company's operating margin, each checked by the
  operating-margin rules on its own.

Amounts are never set side by side across companies (`absolute_amount` is always
refused), so no currency is ever converted. Companies may differ in currency and in
supported basis, because each rate is computed inside one company's own figures.

Every cross-company result carries the caveat key
`cross_company_standards_and_year_ends`. The UI uses it to say that the companies may
report under different accounting standards (K-IFRS, US GAAP) and fiscal year-ends.
The caveat is always attached, even when the year-ends match. The result also says
whether every company's period ends on the same date (`same_period_end`), so the UI
can name a year-end difference.

The companies' periods must have about the same length: the period behind each rate
(the current period for growth, the margin's period for margins) may differ in length
by at most seven days, enough for a leap day or a 52/53-week year. A full year against
a quarter is refused as `period_length_mismatch`, for growth and for margins.

If one company's figures fail a check, the whole comparison is refused with that
company's reason. Showing the remaining companies alone would look like a complete
comparison when it is not.

## Rounding

- Only the final percentage is rounded: `percent_change`, `operating_margin` and each
  cross-company `rate`. Deltas and input values stay exact.
- Rounding is to two decimal places, half-up in the `ROUND_HALF_UP` sense: a tie goes
  away from zero. `12.345` becomes `12.35`, `-12.345` becomes `-12.35`, `0.005`
  becomes `0.01` and `-0.005` becomes `-0.01`. This is not banker's rounding, which
  would give `0.00` for `0.005`. Swift's `NSDecimalRound` with `.plain` rounds the same
  way and is expected to match.
- Subtraction, division and the final rounding run in a fixed decimal context of 34
  significant digits (intermediate rounding half-even), never the caller's thread
  context. Subtraction of any reported figure is exact at that precision, and the
  division's 34th digit cannot move a two-place result, so the only rounding that can
  change a result is the last one. Figures with more than 34 significant digits are
  out of scope.
- A result that rounds to zero is shown as `0.00`, never `-0.00`.

## Comparing results

Results are compared as canonical strings, so the Swift port must produce the same
text, not just the same number:

- A rounded field (`percent_change`, `operating_margin`, `rate`) has exactly two
  fraction digits and a minus sign only when it is below zero: `-14.33`, `10.00`,
  `0.00`, never `-0.00`.
- An exact field (`prior_value`, `current_value`, `delta`, `revenue`,
  `operating_income`) is plain decimal notation: no exponent, no trailing fractional
  zeros, no trailing point and no `-0`. `11.80 - 9.68` is written `2.12`, `100 - 100`
  is `0`, and an input of `11.80` comes back as `11.8`.

Swift's `Decimal` does not keep trailing zeros, so its formatter has to add them for
rounded fields.

## Signs and baselines

- A negative delta against a positive baseline is a valid comparison. The sign stays
  on both the delta and the percentage: `100` to `-50` is a delta of `-150` and
  `-150.00%`.
- When the baseline is zero or negative, the whole comparison is refused
  (`incompatible_comparison`, detail `nonpositive_baseline`). This applies to the
  prior value in a year-over-year comparison and to revenue in an operating margin.

  The alternative was to show the delta and drop only the percentage. We follow
  filing-agent and refuse the whole comparison instead. A delta from a loss to a profit
  is exact, but placed next to other comparisons it invites a growth reading the
  figures do not support, and a delta with no percentage would be the one comparison on
  screen that looks different without saying why. The UI explains the refusal and can
  still show the two reported figures on their own.

## Restated figures

A restated figure is compared like any other; a restated prior year is often the right
baseline. The restatement flag is carried into the result (`prior_is_restated`,
`current_is_restated`, `is_restated`, and each cross-company rate's `is_restated`) so
the UI can label it.

An original and a restated figure for the same period, with no choice made between
them, is an ambiguous request.

## Refusals

A refusal has a reason, which the UI explains in words, and a detail, which says
exactly which check failed. The six reasons:

| Reason | Meaning | Details |
| --- | --- | --- |
| `ambiguous_request` | The request does not say what to compare. | `metric_not_specified`, `measure_not_specified`, `too_many_facts`, `duplicate_period`, `single_company` |
| `unsupported_basis` | A figure is not on a consolidated basis. Supported bases: `consolidated`, `consolidated_entity_total`. | `unsupported_basis` |
| `metric_out_of_scope` | The metric is not in `contracts/financial-vocabulary.json`, or that kind of comparison does not apply to it (for example, year-over-year change of a margin). | `unknown_metric`, `metric_not_supported_for_kind` |
| `missing_period` | A figure the comparison needs is not available, or the years are not consecutive. | `missing_fact`, `non_consecutive_years` |
| `incompatible_currency` | The figures are in different currencies, or amounts in different currencies were asked to be set side by side. | `currency_mismatch`, `absolute_amount_across_currencies` |
| `incompatible_comparison` | The figures exist but do not measure the same thing in the same way. | `absolute_amount_across_companies`, `company_mismatch`, `metric_mismatch`, `basis_mismatch`, `unit_mismatch`, `period_end_mismatch`, `period_length_mismatch`, `overlapping_periods`, `nonpositive_baseline` |

### Order of checks

When more than one check fails, the first in this order decides the refusal. Both
calculators must use the same order. The case file has a case for each adjacent pair
of checks that can fail together (ids starting `order-`, plus a few older cases), so
swapping any two such checks fails at least one case.

1. Cross-company only: the measure is named (`ambiguous_request`).
2. The metric is named, known, and valid for the kind and measure.
3. Every figure has a supported basis.
4. Cross-company only: an `absolute_amount` request is refused here, as
   `incompatible_currency` when currencies differ and `incompatible_comparison`
   otherwise.
5. Cross-company only: at least two companies are present (`ambiguous_request`).
6. Per comparison. For cross-company, each company in the order it first appears; the
   first company that fails decides.
   - Year over year: fewer than two figures (`missing_period`), more than two
     (`ambiguous_request`), then metric, company, basis, currency, unit, period-end
     month-day, period-start month-day, same period (`ambiguous_request`), overlapping
     periods, period length, consecutive years, and last the baseline.
   - Operating margin: a figure for another metric, two figures for one metric
     (`ambiguous_request`), a missing figure (`missing_period`), then company, basis,
     currency, unit, period end, period start, and last the baseline.
7. Cross-company only: the companies' period lengths.

Two pairs cannot fail together, so their order is not observable: fewer than two
against more than two figures, and a missing margin input against a company mismatch
(a mismatch needs both inputs).

### Where the order differs from filing-agent

filing-agent checks the request first (ambiguity, then basis, then metric, then whether
every period was found), then currency across the selected figures, and only then compares the two
figures, reporting any company, metric, basis or period problem as one
`incompatible_comparison`. Filing Footnote differs in three places:

- **Metric before basis.** The metric belongs to the request and the basis to the
  figures. A request for a metric the app does not cover should say so, rather than
  point at the basis of figures that could never answer it.
- **Currency after company, metric and basis.** A pair from two companies, or of two
  metrics, is not one series at all. Calling it a currency problem would suggest that
  converting the currency would fix it.
- **More checks.** filing-agent has no unit, same-period, overlap, period-length or
  consecutive-year check (its figures are selected by fiscal year, so a skipped year
  shows up as a missing period). Each is placed after the period-end and period-start
  month-day checks, which filing-agent also has, and before the baseline, which
  filing-agent also checks last.

## The digest's year-over-year figure

The inherited digest (`compute_yoy_deltas` in `backend/app/financials/calculations.py`)
uses this calculator's percentage and rounding, so its numbers match. It does not run
the full rules above. Database rows carry no basis, no restatement flag, and in legacy
DART rows no period dates, so the digest keeps its own checks instead: same reporting
kind, fiscal quarter, currency, unit and scale; consecutive fiscal years; known
durations within seven days of each other, or both unknown; and a positive baseline.
This is a known limitation until the digest reads figures that carry a basis and
period dates.
