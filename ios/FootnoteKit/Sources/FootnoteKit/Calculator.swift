import Foundation

/// Exact-decimal comparisons of figures, with named refusals: the Swift port of
/// `backend/app/compare/calculator.py`. Rules: `docs/comparison-rules.md`; both calculators
/// pass `contracts/comparison-cases.json`.

public enum RefusalReason: String, CaseIterable, Sendable, Hashable {
    case ambiguousRequest = "ambiguous_request"
    case unsupportedBasis = "unsupported_basis"
    case metricOutOfScope = "metric_out_of_scope"
    case missingPeriod = "missing_period"
    case incompatibleCurrency = "incompatible_currency"
    case incompatibleComparison = "incompatible_comparison"
}

public enum RefusalDetail: String, CaseIterable, Sendable, Hashable {
    case metricNotSpecified = "metric_not_specified"
    case measureNotSpecified = "measure_not_specified"
    case tooManyFacts = "too_many_facts"
    case duplicatePeriod = "duplicate_period"
    case singleCompany = "single_company"
    case unsupportedBasis = "unsupported_basis"
    case unknownMetric = "unknown_metric"
    case metricNotSupportedForKind = "metric_not_supported_for_kind"
    case missingFact = "missing_fact"
    case nonConsecutiveYears = "non_consecutive_years"
    case currencyMismatch = "currency_mismatch"
    case absoluteAmountAcrossCurrencies = "absolute_amount_across_currencies"
    case absoluteAmountAcrossCompanies = "absolute_amount_across_companies"
    case companyMismatch = "company_mismatch"
    case metricMismatch = "metric_mismatch"
    case basisMismatch = "basis_mismatch"
    case unitMismatch = "unit_mismatch"
    case periodEndMismatch = "period_end_mismatch"
    case periodLengthMismatch = "period_length_mismatch"
    case overlappingPeriods = "overlapping_periods"
    case nonpositiveBaseline = "nonpositive_baseline"
}

public enum CrossCompanyMeasure: String, CaseIterable, Sendable, Hashable {
    case growthRate = "growth_rate"
    case operatingMargin = "operating_margin"
    case absoluteAmount = "absolute_amount"
}

public enum FactError: Error, Equatable, Sendable {
    case nonFiniteValue
    case periodStartAfterEnd(start: CivilDate, end: CivilDate)
}

/// One reported figure as the calculator needs it.
public struct Fact: Sendable, Hashable {
    public let companyID: String
    public let metric: String
    public let value: Decimal
    public let unit: String
    public let currency: String?
    public let basis: String
    public let periodStart: CivilDate
    public let periodEnd: CivilDate
    public let isRestated: Bool

    public init(
        companyID: String, metric: String, value: Decimal, unit: String, currency: String?,
        basis: String, periodStart: CivilDate, periodEnd: CivilDate, isRestated: Bool = false
    ) throws(FactError) {
        if value.isNaN { throw .nonFiniteValue }
        if periodStart > periodEnd { throw .periodStartAfterEnd(start: periodStart, end: periodEnd) }
        self.companyID = companyID
        self.metric = metric
        self.value = value
        self.unit = unit
        self.currency = currency
        self.basis = basis
        self.periodStart = periodStart
        self.periodEnd = periodEnd
        self.isRestated = isRestated
    }
}

public struct Refusal: Error, Sendable, Hashable {
    public let reason: RefusalReason
    public let detail: RefusalDetail

    public init(_ reason: RefusalReason, _ detail: RefusalDetail) {
        self.reason = reason
        self.detail = detail
    }
}

/// A comparison either shows its result or names why it refused.
public enum Comparison<Value: Sendable & Hashable>: Sendable, Hashable {
    case result(Value)
    case refusal(Refusal)
}

public struct YearOverYear: Sendable, Hashable {
    public let companyID: String
    public let metric: String
    public let priorValue: Decimal
    public let currentValue: Decimal
    public let delta: Decimal
    /// Rounded half-up to two places.
    public let percentChange: Decimal
    public let currency: String?
    public let unit: String
    public let priorPeriodStart: CivilDate
    public let priorPeriodEnd: CivilDate
    public let currentPeriodStart: CivilDate
    public let currentPeriodEnd: CivilDate
    public let priorIsRestated: Bool
    public let currentIsRestated: Bool
    /// True when the two periods end on different month-days: consecutive 52/53-week
    /// fiscal years.
    public let periodEndsDiffer: Bool
}

public struct OperatingMargin: Sendable, Hashable {
    public let companyID: String
    public let revenue: Decimal
    public let operatingIncome: Decimal
    /// Rounded half-up to two places.
    public let operatingMargin: Decimal
    public let currency: String?
    public let periodStart: CivilDate
    public let periodEnd: CivilDate
    public let isRestated: Bool
}

public struct CompanyRate: Sendable, Hashable {
    public let companyID: String
    /// A percentage rounded half-up to two places.
    public let rate: Decimal
    public let periodStart: CivilDate
    public let periodEnd: CivilDate
    public let isRestated: Bool
}

public struct CrossCompany: Sendable, Hashable {
    public let metric: String
    public let measure: CrossCompanyMeasure
    /// In the order each company first appears in the input.
    public let companies: [CompanyRate]
    public let samePeriodEnd: Bool
    /// Always shown: accounting standards (K-IFRS, US GAAP) and year-ends differ.
    public let caveat: String
}

public enum Calculator {
    public static let supportedBases: Set<String> = ["consolidated", "consolidated_entity_total"]
    public static let crossCompanyCaveat = "cross_company_standards_and_year_ends"

    /// Division runs at this many significant digits, half to even, as the Python context
    /// does; the final half-up step to two places is the only rounding that can change a result.
    static let precision = 34
    /// Periods of companies set side by side may differ by a leap day or a 52/53-week year.
    static let maxCrossCompanyLengthDifferenceDays = 7
    /// A 52/53-week fiscal year runs 364 or 371 days, counting both ends; a calendar year
    /// runs 365 or 366. Both fall in this range, and so does the step from one such year
    /// end to the next.
    static let fiscalYearDays = 357...371
    /// How far a 52/53-week year end may drift from the prior end's anniversary.
    static let maxYearEndDriftDays = 7

    private static let reported = Set(ReportedMetric.allCases.map(\.rawValue))
    private static let margin: Set<String> = [DerivedMetric.operatingMargin.rawValue]
    private static let known = reported.union(DerivedMetric.allCases.map(\.rawValue))

    /// `numerator / baseline * 100` rounded half-up to two places; nil when the baseline is
    /// zero or negative, because such a percentage reads as a direction it does not have.
    public static func percentage(_ numerator: Decimal, of baseline: Decimal) -> Decimal? {
        if baseline <= 0 { return nil }
        let quotient = DecimalText.roundSignificant(numerator * 100 / baseline, digits: precision)
        // A tiny negative change rounds to -0.00; it is shown as 0.00.
        return DecimalText.roundHalfUp(quotient, scale: 2)
    }

    /// One company's figure against the same figure a year earlier.
    public static func yearOverYear(metric: String?, facts: [Fact]) -> Comparison<YearOverYear> {
        if let refusal = checkMetric(metric, allowed: reported) ?? checkBases(facts) {
            return .refusal(refusal)
        }
        return wrap { () throws(Refusal) in try yearOverYear(metric!, facts) }
    }

    /// Operating income as a percentage of revenue for one period.
    public static func operatingMargin(
        metric: String?, facts: [Fact]
    ) -> Comparison<OperatingMargin> {
        if let refusal = checkMetric(metric, allowed: margin) ?? checkBases(facts) {
            return .refusal(refusal)
        }
        return wrap { () throws(Refusal) in try operatingMargin(facts) }
    }

    /// Growth rates or operating margins of several companies side by side. Amounts are never
    /// compared across companies, so no currency is converted.
    public static func crossCompany(
        metric: String?, measure: String?, facts: [Fact]
    ) -> Comparison<CrossCompany> {
        guard let measure, let chosen = CrossCompanyMeasure(rawValue: measure) else {
            return .refusal(Refusal(.ambiguousRequest, .measureNotSpecified))
        }
        let allowed = chosen == .operatingMargin ? margin : reported
        if let refusal = checkMetric(metric, allowed: allowed) ?? checkBases(facts) {
            return .refusal(refusal)
        }
        let metric = metric!

        if chosen == .absoluteAmount {
            if Set(facts.map(\.currency)).count > 1 {
                return .refusal(Refusal(.incompatibleCurrency, .absoluteAmountAcrossCurrencies))
            }
            return .refusal(Refusal(.incompatibleComparison, .absoluteAmountAcrossCompanies))
        }

        var order: [String] = []
        var byCompany: [String: [Fact]] = [:]
        for fact in facts {
            if byCompany[fact.companyID] == nil { order.append(fact.companyID) }
            byCompany[fact.companyID, default: []].append(fact)
        }
        if order.count < 2 { return .refusal(Refusal(.ambiguousRequest, .singleCompany)) }

        return wrap { () throws(Refusal) in
            var rates: [CompanyRate] = []
            for companyID in order {
                let companyFacts = byCompany[companyID]!
                if chosen == .growthRate {
                    let result = try yearOverYear(metric, companyFacts)
                    rates.append(CompanyRate(
                        companyID: companyID, rate: result.percentChange,
                        periodStart: result.currentPeriodStart,
                        periodEnd: result.currentPeriodEnd,
                        isRestated: result.priorIsRestated || result.currentIsRestated))
                } else {
                    let result = try operatingMargin(companyFacts)
                    rates.append(CompanyRate(
                        companyID: companyID, rate: result.operatingMargin,
                        periodStart: result.periodStart, periodEnd: result.periodEnd,
                        isRestated: result.isRestated))
                }
            }
            let lengths = rates.map { $0.periodStart.days(to: $0.periodEnd) }
            if lengths.max()! - lengths.min()! > maxCrossCompanyLengthDifferenceDays {
                throw Refusal(.incompatibleComparison, .periodLengthMismatch)
            }
            return CrossCompany(
                metric: metric, measure: chosen, companies: rates,
                samePeriodEnd: Set(rates.map(\.periodEnd)).count == 1,
                caveat: crossCompanyCaveat)
        }
    }

    // MARK: - Checks

    private static func wrap<T>(_ body: () throws(Refusal) -> T) -> Comparison<T> {
        do { return .result(try body()) } catch { return .refusal(error) }
    }

    private static func checkMetric(_ metric: String?, allowed: Set<String>) -> Refusal? {
        guard let metric, !metric.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return Refusal(.ambiguousRequest, .metricNotSpecified)
        }
        if !known.contains(metric) { return Refusal(.metricOutOfScope, .unknownMetric) }
        if !allowed.contains(metric) {
            return Refusal(.metricOutOfScope, .metricNotSupportedForKind)
        }
        return nil
    }

    private static func checkBases(_ facts: [Fact]) -> Refusal? {
        facts.contains { !supportedBases.contains($0.basis) }
            ? Refusal(.unsupportedBasis, .unsupportedBasis) : nil
    }

    private static func yearOverYear(
        _ metric: String, _ facts: [Fact]
    ) throws(Refusal) -> YearOverYear {
        if facts.count < 2 { throw Refusal(.missingPeriod, .missingFact) }
        if facts.count > 2 { throw Refusal(.ambiguousRequest, .tooManyFacts) }
        // A stable sort by period end, as Python's `sorted`.
        let ordered = facts.enumerated()
            .sorted { ($0.element.periodEnd, $0.offset) < ($1.element.periodEnd, $1.offset) }
            .map(\.element)
        let prior = ordered[0], current = ordered[1]
        if prior.metric != metric || current.metric != metric {
            throw Refusal(.incompatibleComparison, .metricMismatch)
        }
        if prior.companyID != current.companyID {
            throw Refusal(.incompatibleComparison, .companyMismatch)
        }
        if prior.basis != current.basis { throw Refusal(.incompatibleComparison, .basisMismatch) }
        if prior.currency != current.currency {
            throw Refusal(.incompatibleCurrency, .currencyMismatch)
        }
        if prior.unit != current.unit { throw Refusal(.incompatibleComparison, .unitMismatch) }

        func monthDay(_ date: CivilDate) -> [Int] { [date.month, date.day] }
        let endsDiffer = monthDay(prior.periodEnd) != monthDay(current.periodEnd)
        if endsDiffer {
            if !consecutiveFiscalYears(prior, current) {
                throw Refusal(.incompatibleComparison, .periodEndMismatch)
            }
            if current.periodStart <= prior.periodEnd {
                throw Refusal(.incompatibleComparison, .overlappingPeriods)
            }
        } else {
            if monthDay(prior.periodStart) != monthDay(current.periodStart) {
                throw Refusal(.incompatibleComparison, .periodLengthMismatch)
            }
            let endGap = current.periodEnd.year - prior.periodEnd.year
            let startGap = current.periodStart.year - prior.periodStart.year
            if endGap == 0 && startGap == 0 { throw Refusal(.ambiguousRequest, .duplicatePeriod) }
            if current.periodStart <= prior.periodEnd {
                throw Refusal(.incompatibleComparison, .overlappingPeriods)
            }
            if startGap != endGap { throw Refusal(.incompatibleComparison, .periodLengthMismatch) }
            if endGap > 1 { throw Refusal(.missingPeriod, .nonConsecutiveYears) }
        }

        let delta = current.value - prior.value
        guard let percent = percentage(delta, of: prior.value) else {
            throw Refusal(.incompatibleComparison, .nonpositiveBaseline)
        }
        return YearOverYear(
            companyID: current.companyID, metric: metric, priorValue: prior.value,
            currentValue: current.value, delta: delta, percentChange: percent,
            currency: current.currency, unit: current.unit,
            priorPeriodStart: prior.periodStart, priorPeriodEnd: prior.periodEnd,
            currentPeriodStart: current.periodStart, currentPeriodEnd: current.periodEnd,
            priorIsRestated: prior.isRestated, currentIsRestated: current.isRestated,
            periodEndsDiffer: endsDiffer)
    }

    /// Whether two periods whose ends differ in month-day are consecutive full fiscal years,
    /// as 52/53-week years are (docs/DECISIONS.md D82).
    private static func consecutiveFiscalYears(_ prior: Fact, _ current: Fact) -> Bool {
        func days(_ fact: Fact) -> Int { fact.periodStart.days(to: fact.periodEnd) + 1 }
        // The same month-day a year later; February 29 becomes February 28.
        let end = prior.periodEnd
        let anniversary = CivilDate(year: end.year + 1, month: end.month, day: end.day)
            ?? CivilDate(year: end.year + 1, month: 2, day: 28)!
        let drift = anniversary.days(to: current.periodEnd)
        return fiscalYearDays.contains(days(prior))
            && fiscalYearDays.contains(days(current))
            && fiscalYearDays.contains(prior.periodEnd.days(to: current.periodEnd))
            && abs(drift) <= maxYearEndDriftDays
    }

    private static func operatingMargin(_ facts: [Fact]) throws(Refusal) -> OperatingMargin {
        let revenueKey = ReportedMetric.revenue.rawValue
        let incomeKey = ReportedMetric.operatingIncome.rawValue
        if facts.contains(where: { $0.metric != revenueKey && $0.metric != incomeKey }) {
            throw Refusal(.incompatibleComparison, .metricMismatch)
        }
        let revenues = facts.filter { $0.metric == revenueKey }
        let incomes = facts.filter { $0.metric == incomeKey }
        if revenues.count > 1 || incomes.count > 1 {
            throw Refusal(.ambiguousRequest, .duplicatePeriod)
        }
        guard let revenue = revenues.first, let income = incomes.first else {
            throw Refusal(.missingPeriod, .missingFact)
        }
        if revenue.companyID != income.companyID {
            throw Refusal(.incompatibleComparison, .companyMismatch)
        }
        if revenue.basis != income.basis { throw Refusal(.incompatibleComparison, .basisMismatch) }
        if revenue.currency != income.currency {
            throw Refusal(.incompatibleCurrency, .currencyMismatch)
        }
        if revenue.unit != income.unit { throw Refusal(.incompatibleComparison, .unitMismatch) }
        if revenue.periodEnd != income.periodEnd {
            throw Refusal(.incompatibleComparison, .periodEndMismatch)
        }
        if revenue.periodStart != income.periodStart {
            throw Refusal(.incompatibleComparison, .periodLengthMismatch)
        }
        guard let margin = percentage(income.value, of: revenue.value) else {
            throw Refusal(.incompatibleComparison, .nonpositiveBaseline)
        }
        return OperatingMargin(
            companyID: revenue.companyID, revenue: revenue.value,
            operatingIncome: income.value, operatingMargin: margin, currency: revenue.currency,
            periodStart: revenue.periodStart, periodEnd: revenue.periodEnd,
            isRestated: revenue.isRestated || income.isRestated)
    }
}
