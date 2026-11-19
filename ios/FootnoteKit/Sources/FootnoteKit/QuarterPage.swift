import Foundation

/// One quarter's figure from a quarterly report (`quarter_figures`, I11): the quarter's own
/// three months, never the year to date.
public struct QuarterFigure: Sendable, Hashable, Identifiable {
    public let id: String
    public let companyID: String
    public let filingID: String
    public let metric: ReportedMetric
    public let fiscalYear: Int
    /// 1, 2 or 3.
    public let fiscalQuarter: Int
    public let periodStart: CivilDate
    public let periodEnd: CivilDate
    public let value: Decimal
    public let unit: String
    public let currency: String?
    public let basis: String
    public let regulatorTag: String
}

/// A quarter against the same quarter a year earlier.
public struct QuarterChange: Sendable, Hashable {
    public let priorValue: Decimal
    public let currentValue: Decimal
    public let delta: Decimal
    /// Rounded half-up to two places by `Calculator.percentage`.
    public let percentChange: Decimal
}

public enum QuarterComparison {
    /// The three months a year earlier may end a few days apart (52/53-week quarters), so
    /// the two ends lie this many days apart, as a fiscal year's two ends do.
    static let yearApartDays = Calculator.fiscalYearDays
    /// A quarter of three calendar months or of 13 or 14 weeks, counting both ends.
    static let quarterDays = 89...98

    /// `current` against `prior`: same company, metric, basis, currency and unit; both one
    /// quarter long and a year apart. A base of zero or below is refused, as
    /// `Calculator.yearOverYear` refuses it.
    public static func compare(prior: QuarterFigure, current: QuarterFigure) -> Comparison<QuarterChange> {
        if prior.metric != current.metric { return .refusal(Refusal(.incompatibleComparison, .metricMismatch)) }
        if prior.companyID != current.companyID {
            return .refusal(Refusal(.incompatibleComparison, .companyMismatch))
        }
        if prior.basis != current.basis { return .refusal(Refusal(.incompatibleComparison, .basisMismatch)) }
        if prior.currency != current.currency {
            return .refusal(Refusal(.incompatibleCurrency, .currencyMismatch))
        }
        if prior.unit != current.unit { return .refusal(Refusal(.incompatibleComparison, .unitMismatch)) }
        func days(_ figure: QuarterFigure) -> Int { figure.periodStart.days(to: figure.periodEnd) + 1 }
        if !quarterDays.contains(days(prior)) || !quarterDays.contains(days(current)) {
            return .refusal(Refusal(.incompatibleComparison, .periodLengthMismatch))
        }
        if !yearApartDays.contains(prior.periodEnd.days(to: current.periodEnd)) {
            return .refusal(Refusal(.incompatibleComparison, .periodEndMismatch))
        }
        let delta = current.value - prior.value
        guard let percent = Calculator.percentage(delta, of: prior.value) else {
            return .refusal(Refusal(.incompatibleComparison, .nonpositiveBaseline))
        }
        return .result(QuarterChange(
            priorValue: prior.value, currentValue: current.value, delta: delta, percentChange: percent))
    }
}

/// One of the quarter report's figures with the same quarter a year earlier.
public struct QuarterFigureRow: Sendable, Hashable, Identifiable {
    public let metric: ReportedMetric
    public let current: QuarterFigure
    /// The same quarter a year earlier; nil when the report does not state it.
    public let prior: QuarterFigure?

    public var id: String { metric.rawValue }

    /// The change, or why there is none: a missing prior quarter is `missing_period`.
    public var comparison: Comparison<QuarterChange> {
        guard let prior else { return .refusal(Refusal(.missingPeriod, .missingFact)) }
        return QuarterComparison.compare(prior: prior, current: current)
    }
}

/// What the quarter report shows (DESIGN.md, Quarter report; board 15): three figures, each
/// against the same quarter a year earlier, the preliminary results filed before the report,
/// and the investor event notice. Never the change from the quarter before.
public struct QuarterPage: Sendable {
    /// Revenue, operating income, then net income attributable to owners, or net income
    /// when the report states no attributable figure.
    public static let metrics: [ReportedMetric] = [.revenue, .operatingIncome, .netIncomeAttributable]

    public let filing: Filing
    public let company: Company
    public let dataAsOf: CivilDate
    /// The consolidated figures of the report's own quarter; rows with no current figure are
    /// left out.
    public let rows: [QuarterFigureRow]
    /// The preliminary results the company filed after the quarter ended and before this
    /// report; nil when the bundle has none.
    public let preliminary: Filing?
    /// The newest investor event notice in the same span; nil when there is none.
    public let investorEvent: Notice?
    public let source: SourceDetails

    public init?(store: BundleStore, filingID: String) {
        guard let filing = store.filing(id: filingID), filing.kind == .quarterly,
              let company = store.company(id: filing.companyID)
        else { return nil }
        self.filing = filing
        self.company = company
        dataAsOf = store.meta.dataAsOf
        source = SourceDetails(filing: filing, regulator: company.regulator)
        rows = Self.rows(store.quarterFigures.filter { $0.filingID == filing.id && $0.basis == "consolidated" })
        let quarterEnd = rows.first?.current.periodEnd
        func inSpan(_ date: CivilDate) -> Bool {
            guard let quarterEnd else { return false }
            return date > quarterEnd && date <= filing.filedOn
        }
        preliminary = store.eventFilings(forCompany: company.id)
            .first { $0.category == .earnings && inSpan($0.filedOn) }
        investorEvent = store.notices(forCompany: company.id)
            .first { $0.category == .irEvent && inSpan($0.filedOn) }
    }

    static func rows(_ figures: [QuarterFigure]) -> [QuarterFigureRow] {
        guard let end = figures.map(\.periodEnd).max() else { return [] }
        func row(_ metric: ReportedMetric) -> QuarterFigureRow? {
            guard let current = figures.first(where: { $0.metric == metric && $0.periodEnd == end })
            else { return nil }
            let prior = figures.first { $0.metric == metric && $0.periodEnd < end }
            return QuarterFigureRow(metric: metric, current: current, prior: prior)
        }
        let income = row(.netIncomeAttributable) ?? row(.netIncome)
        return [row(.revenue), row(.operatingIncome), income].compactMap { $0 }
    }

    /// The quarter's first and last day.
    public var period: (start: CivilDate, end: CivilDate)? {
        rows.first.map { ($0.current.periodStart, $0.current.periodEnd) }
    }

    /// The same quarter a year earlier, from the first row that states it.
    public var priorPeriod: (start: CivilDate, end: CivilDate)? {
        rows.lazy.compactMap(\.prior).first.map { ($0.periodStart, $0.periodEnd) }
    }

    /// The currency of the figures, or the company's.
    public var currency: String { rows.first?.current.currency ?? company.currency }
}

/// The company page's quarterly row (board 14): the newest quarterly report with its revenue
/// against the same quarter a year earlier.
public struct QuarterReport: Sendable, Hashable {
    public let filing: Filing
    public let revenue: QuarterFigureRow?

    init?(store: BundleStore, companyID: String) {
        guard let filing = store.quarterlyFilings(forCompany: companyID).first else { return nil }
        self.filing = filing
        revenue = QuarterPage.rows(
            store.quarterFigures.filter { $0.filingID == filing.id && $0.basis == "consolidated" }
        ).first { $0.metric == .revenue }
    }

    /// The revenue change, when it could be worked out.
    public var change: QuarterChange? {
        if case .result(let change)? = revenue?.comparison { return change }
        return nil
    }
}
