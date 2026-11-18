import Foundation

/// The figure screen and its comparisons (DESIGN.md, Figure and Compare; boards 5A, 6, 6b, 7A,
/// 7, 8, 10): every value is a `Decimal` from the bundle and every change or rate comes from
/// `Calculator`. The SwiftUI views only lay these models out.

// MARK: - Accounting standard

/// The standard a company's statements follow. The bundle has no column for it (schema
/// version 2), so it follows the regulator: DART companies report under K-IFRS and SEC
/// companies under US GAAP.
public enum AccountingStandard: String, Sendable, Hashable {
    case kIFRS = "k_ifrs"
    case usGAAP = "us_gaap"

    /// `K-IFRS` or `US GAAP`, the same in both languages.
    public var label: String { self == .kIFRS ? "K-IFRS" : "US GAAP" }
}

extension Company {
    public var accountingStandard: AccountingStandard { regulator == .dart ? .kIFRS : .usGAAP }

    /// The month of `fiscal_year_end` (`09-26` -> 9). Nil unless the value is `MM-DD` with a
    /// month of one to twelve and a day of one to thirty-one, so bad data names no month.
    public var fiscalYearEndMonth: Int? {
        let parts = fiscalYearEnd.split(separator: "-", omittingEmptySubsequences: false)
        guard parts.count == 2, parts.allSatisfy({ $0.count == 2 }),
              let month = Int(parts[0]), let day = Int(parts[1]),
              (1...12).contains(month), (1...31).contains(day) else { return nil }
        return month
    }
}

// MARK: - Figure selection

enum FigureSelection {
    /// `consolidated` when the company has it, else the first basis it has. An unsupported
    /// basis is kept, so the calculator names it (`unsupported_basis`) instead of the screen
    /// showing nothing.
    static func basis(_ figures: [Figure]) -> String? {
        figures.contains { $0.basis == "consolidated" } ? "consolidated" : figures.map(\.basis).sorted().first
    }

    /// One metric of one company on its chosen basis, newest fiscal year first.
    static func years(_ store: BundleStore, _ companyID: String, _ metric: ReportedMetric) -> (String?, [Figure]) {
        let all = store.figures(forCompany: companyID, metric: metric)
        let basis = basis(all)
        return (basis, all.filter { $0.basis == basis }.sorted { $0.fiscalYear > $1.fiscalYear })
    }

    static func sources(_ store: BundleStore, _ figures: [Figure]) -> [String: Filing] {
        var sources: [String: Filing] = [:]
        for figure in figures { sources[figure.filingID] = store.filing(id: figure.filingID) }
        return sources
    }
}

// MARK: - Figure screen (board 5A)

/// One metric of one company: the meaning from the glossary, every year in the bundle, and
/// the change of the report's year (`fiscalYear`) against the year before.
public struct FigurePage: Sendable {
    public let company: Company
    public let metric: ReportedMetric
    /// The year of the report the screen was opened from (D83).
    public let fiscalYear: Int
    public let basis: String?
    /// Newest fiscal year first, all on `basis`.
    public let years: [Figure]
    private let sources: [String: Filing]
    private let meanings: [Language: GlossaryEntry]

    public init?(store: BundleStore, companyID: String, metric: ReportedMetric, fiscalYear: Int) {
        guard let company = store.company(id: companyID) else { return nil }
        self.company = company
        self.metric = metric
        self.fiscalYear = fiscalYear
        (basis, years) = FigureSelection.years(store, companyID, metric)
        sources = FigureSelection.sources(store, years)
        var meanings: [Language: GlossaryEntry] = [:]
        for language in Language.allCases {
            meanings[language] = store.glossaryEntry(termKey: "metric_\(metric.rawValue)", language: language)
        }
        self.meanings = meanings
        change = YearComparePage(
            company: company, metric: metric.rawValue, fiscalYear: fiscalYear, basis: basis,
            years: years, sources: sources).outcome
    }

    /// The glossary entry for the metric (`metric_<key>`, D81), when the bundle has one.
    public func meaning(_ language: Language) -> GlossaryEntry? { meanings[language] }

    public func figure(fiscalYear: Int) -> Figure? { years.first { $0.fiscalYear == fiscalYear } }

    /// The figure of the report's year; nil when the filings do not state it.
    public var current: Figure? { figure(fiscalYear: fiscalYear) }

    /// The report's year against the year before, or the calculator's refusal.
    public let change: Comparison<YearOverYear>

    public var hasRestated: Bool { years.contains(where: \.isRestated) }

    /// The filing a figure comes from.
    public func source(of figure: Figure) -> Filing? { sources[figure.filingID] }
}

// MARK: - Compare with last year (board 6)

/// One company's figure against the same figure a year earlier.
public struct YearComparePage: Sendable {
    public let company: Company
    /// The metric as requested; a key the app does not cover is refused, not dropped.
    public let metric: String?
    public let fiscalYear: Int
    public let basis: String?
    public let prior: Figure?
    public let current: Figure?
    public let outcome: Comparison<YearOverYear>
    private let sources: [String: Filing]

    /// `metric` is a key from `contracts/financial-vocabulary.json`; nil or an unknown key is
    /// refused by the calculator.
    public init?(store: BundleStore, companyID: String, metric: String?, fiscalYear: Int) {
        guard let company = store.company(id: companyID) else { return nil }
        let reported = metric.flatMap(ReportedMetric.init(rawValue:))
        let (basis, years) = reported.map { FigureSelection.years(store, companyID, $0) } ?? (nil, [])
        self.init(company: company, metric: metric, fiscalYear: fiscalYear, basis: basis, years: years,
                  sources: FigureSelection.sources(store, years))
    }

    init(company: Company, metric: String?, fiscalYear: Int, basis: String?, years: [Figure],
         sources: [String: Filing]) {
        self.company = company
        self.metric = metric
        self.fiscalYear = fiscalYear
        self.basis = basis
        self.sources = sources
        current = years.first { $0.fiscalYear == fiscalYear }
        prior = years.first { $0.fiscalYear == fiscalYear - 1 }
        outcome = Calculator.yearOverYear(
            metric: metric, facts: [prior, current].compactMap { $0?.fact })
    }

    public var reportedMetric: ReportedMetric? { metric.flatMap(ReportedMetric.init(rawValue:)) }

    /// The calculation and the checks it passed; nil when the comparison is refused.
    public var calculation: YearCalculation? {
        guard case .result(let result) = outcome, let prior, let current, let reportedMetric else { return nil }
        return YearCalculation(
            company: company, metric: reportedMetric, result: result, prior: prior, current: current,
            priorSource: sources[prior.filingID], currentSource: sources[current.filingID])
    }

    /// Why the comparison is refused and what is possible instead; nil for a result.
    public var explanation: RefusalExplanation? {
        guard case .refusal(let refusal) = outcome else { return nil }
        let missing: MissingYear? = refusal.reason == .missingPeriod
            ? MissingYear(companyID: company.id, fiscalYear: current == nil ? fiscalYear : fiscalYear - 1,
                          metric: reportedMetric)
            : nil
        let baseline = refusal.detail == .nonpositiveBaseline ? prior : nil
        return RefusalExplanation(
            refusal: refusal, context: .lastYear, companies: [company], culpritID: company.id,
            metric: reportedMetric, missing: missing, baseline: baseline,
            actions: RefusalAction.forLastYear(refusal, company: company))
    }
}

/// A year-over-year result with its inputs: both exact values, their filings and periods.
public struct YearCalculation: Sendable, Hashable {
    public let company: Company
    public let metric: ReportedMetric
    public let result: YearOverYear
    public let prior: Figure
    public let current: Figure
    public let priorSource: Filing?
    public let currentSource: Filing?

    /// The checks a result has passed (docs/comparison-rules.md), in board 6b's order.
    public var checks: [CalculationCheck] {
        [
            .sameCompany(company),
            .sameMetric(metric),
            .sameCurrency(result.currency),
            .sameBasis(prior.basis),
            .consecutiveYears(priorDays: prior.periodStart.days(to: prior.periodEnd) + 1,
                              currentDays: current.periodStart.days(to: current.periodEnd) + 1),
            .positiveBaseline(prior),
        ]
    }
}

/// One check a comparison passed, with the value it was checked on.
public enum CalculationCheck: Sendable, Hashable {
    case sameCompany(Company)
    case sameMetric(ReportedMetric)
    case sameCurrency(String?)
    case sameBasis(String)
    /// The two periods' lengths, counting both end days.
    case consecutiveYears(priorDays: Int, currentDays: Int)
    case positiveBaseline(Figure)
}

// MARK: - Compare with another company (boards 7A, 7, 8)

/// Growth rates or operating margins of two companies side by side. Amounts are never set
/// side by side, so no currency is converted: an amount request is always refused.
public struct CompanyComparePage: Sendable {
    /// The company the screen was opened from, then the one picked.
    public let companies: [Company]
    /// The figure the screen was opened from (`revenue`); the margin measure uses
    /// `operating_margin` instead.
    public let metric: String?
    /// As requested; nil or an unknown measure is refused as ambiguous.
    public let measure: String?
    /// The figures behind each company's rate, in `companies` order.
    public let inputs: [CompanyInputs]
    public let outcome: Comparison<CrossCompany>
    public let caveat: CrossCompanyCaveat

    public init?(store: BundleStore, companyID: String, peerID: String, metric: String?,
                 measure: String?, fiscalYear: Int) {
        guard let company = store.company(id: companyID), let peer = store.company(id: peerID) else { return nil }
        companies = [company, peer]
        self.metric = metric
        self.measure = measure
        let chosen = measure.flatMap(CrossCompanyMeasure.init(rawValue:))
        inputs = [
            CompanyInputs(store: store, company: company, metric: metric, measure: chosen, fiscalYear: fiscalYear),
            CompanyInputs(store: store, company: peer, metric: metric, measure: chosen, fiscalYear: nil),
        ]
        caveat = CrossCompanyCaveat(companies: companies, inputs: inputs)
        let calculatorMetric = chosen == .operatingMargin ? DerivedMetric.operatingMargin.rawValue : metric
        var outcome = Calculator.crossCompany(
            metric: calculatorMetric, measure: measure, facts: inputs.flatMap { $0.figures.map(\.fact) })
        // A company with no figure at all drops out of the facts, which the calculator reads
        // as a single company. The figure is missing, so say that.
        if case .refusal(let refusal) = outcome, refusal.detail == .singleCompany,
           inputs.contains(where: \.figures.isEmpty) {
            outcome = .refusal(Refusal(.missingPeriod, .missingFact))
        }
        // Likewise an amount request where one company has no figure: that company's
        // reporting currency still decides whether it is a currency refusal.
        let currencies = inputs.map { $0.figures.first?.currency ?? $0.company.currency }
        if case .refusal(let refusal) = outcome, refusal.detail == .absoluteAmountAcrossCompanies,
           Set(currencies).count > 1 {
            outcome = .refusal(Refusal(.incompatibleCurrency, .absoluteAmountAcrossCurrencies))
        }
        self.outcome = outcome
    }

    public var chosenMeasure: CrossCompanyMeasure? { measure.flatMap(CrossCompanyMeasure.init(rawValue:)) }

    public var reportedMetric: ReportedMetric? { metric.flatMap(ReportedMetric.init(rawValue:)) }

    /// The absolute difference of the two rates in percentage points, exact. It says how far
    /// apart they are, not which one is higher.
    public var difference: Decimal? {
        guard case .result(let result) = outcome, result.companies.count == 2 else { return nil }
        let delta = result.companies[0].rate - result.companies[1].rate
        return delta < 0 ? -delta : delta
    }

    /// Each company's own calculation, for the calculation screen.
    public var calculations: [CompanyCalculation] {
        guard case .result = outcome, let chosen = chosenMeasure else { return [] }
        return inputs.compactMap { input in
            switch chosen {
            case .growthRate:
                guard let reportedMetric, input.figures.count == 2,
                      case .result(let result) = Calculator.yearOverYear(
                        metric: reportedMetric.rawValue, facts: input.figures.map(\.fact))
                else { return nil }
                return .growth(YearCalculation(
                    company: input.company, metric: reportedMetric, result: result,
                    prior: input.figures[0], current: input.figures[1],
                    priorSource: input.sources[input.figures[0].filingID],
                    currentSource: input.sources[input.figures[1].filingID]))
            case .operatingMargin:
                guard input.figures.count == 2,
                      case .result(let result) = Calculator.operatingMargin(
                        metric: DerivedMetric.operatingMargin.rawValue, facts: input.figures.map(\.fact))
                else { return nil }
                return .margin(MarginCalculation(
                    company: input.company, result: result, revenue: input.figures[0],
                    operatingIncome: input.figures[1], source: input.sources[input.figures[0].filingID]))
            case .absoluteAmount:
                return nil
            }
        }
    }

    /// Why the comparison is refused and what is possible instead; nil for a result.
    public var explanation: RefusalExplanation? {
        guard case .refusal(let refusal) = outcome else { return nil }
        let chosen = chosenMeasure
        // The company whose own figures fail, for the reason sentence and the actions.
        // An amount request is refused before any company's own check runs, so a basis
        // refusal there falls back to the company whose figures are not on a supported basis.
        let culprit = inputs.first { $0.refusal(metric: metric, measure: chosen) == refusal }
            ?? (refusal.reason == .unsupportedBasis
                ? inputs.first { $0.figures.contains { !Calculator.supportedBases.contains($0.basis) } } : nil)
        var missing: MissingYear?
        if refusal.reason == .missingPeriod, let input = culprit ?? inputs.first(where: \.figures.isEmpty) {
            missing = input.missingYear(metric: reportedMetric, measure: chosen)
        }
        let baseline = refusal.detail == .nonpositiveBaseline ? culprit?.figures.first : nil
        return RefusalExplanation(
            refusal: refusal, context: .company(chosen), companies: companies,
            culpritID: culprit?.company.id, metric: reportedMetric, missing: missing, baseline: baseline,
            actions: RefusalAction.forCompany(
                refusal, measure: chosen, metric: reportedMetric, culprit: culprit?.company ?? companies[0],
                base: companies[0]))
    }
}

/// One company's figures behind its rate.
public struct CompanyInputs: Sendable, Hashable {
    public let company: Company
    /// The year whose rate is shown; nil when the company has no figure for it.
    public let fiscalYear: Int?
    public let basis: String?
    /// Growth: the prior then the current year. Margin: revenue then operating income.
    /// Amount: the current year.
    public let figures: [Figure]
    let sources: [String: Filing]

    /// `fiscalYear` nil picks the company's newest year that has the figures the measure needs.
    init(store: BundleStore, company: Company, metric: String?, measure: CrossCompanyMeasure?, fiscalYear: Int?) {
        self.company = company
        let all = store.figures.filter { $0.companyID == company.id }
        let basis = FigureSelection.basis(all)
        self.basis = basis
        let onBasis = all.filter { $0.basis == basis }
        func figure(_ metric: ReportedMetric, _ year: Int) -> Figure? {
            onBasis.first { $0.metric == metric && $0.fiscalYear == year }
        }
        let reported = metric.flatMap(ReportedMetric.init(rawValue:))
        let needed: [ReportedMetric] = measure == .operatingMargin
            ? [.revenue, .operatingIncome] : reported.map { [$0] } ?? []
        // The years that have every metric the measure needs: for the margin, revenue and
        // operating income of the same year.
        let candidates = needed
            .map { metric in Set(onBasis.filter { $0.metric == metric }.map(\.fiscalYear)) }
            .reduce(nil) { (common: Set<Int>?, years: Set<Int>) in common?.intersection(years) ?? years } ?? []
        let year = fiscalYear ?? candidates.max()
        self.fiscalYear = year
        guard let year, let measure, !needed.isEmpty else {
            figures = []
            sources = [:]
            return
        }
        let chosen: [Figure?] = switch measure {
        case .growthRate: [figure(needed[0], year - 1), figure(needed[0], year)]
        case .operatingMargin: [figure(.revenue, year), figure(.operatingIncome, year)]
        case .absoluteAmount: [figure(needed[0], year)]
        }
        figures = chosen.compactMap { $0 }
        sources = FigureSelection.sources(store, figures)
    }

    /// This company's own refusal, as the calculator would give it alone.
    func refusal(metric: String?, measure: CrossCompanyMeasure?) -> Refusal? {
        let outcome: Comparison<Bool> = switch measure {
        case .growthRate?:
            Calculator.yearOverYear(metric: metric, facts: figures.map(\.fact)).map { _ in true }
        case .operatingMargin?:
            Calculator.operatingMargin(
                metric: DerivedMetric.operatingMargin.rawValue, facts: figures.map(\.fact)).map { _ in true }
        default: .result(true)
        }
        if case .refusal(let refusal) = outcome { return refusal }
        return nil
    }

    /// The year this company has no figure for.
    func missingYear(metric: ReportedMetric?, measure: CrossCompanyMeasure?) -> MissingYear? {
        guard let fiscalYear else { return MissingYear(companyID: company.id, fiscalYear: nil, metric: metric) }
        switch measure {
        case .growthRate?:
            let has = Set(figures.map(\.fiscalYear))
            return MissingYear(companyID: company.id, fiscalYear: has.contains(fiscalYear) ? fiscalYear - 1 : fiscalYear,
                               metric: metric)
        case .operatingMargin?:
            let has = Set(figures.map(\.metric))
            return MissingYear(companyID: company.id, fiscalYear: fiscalYear,
                               metric: has.contains(.revenue) ? .operatingIncome : .revenue)
        default:
            return MissingYear(companyID: company.id, fiscalYear: fiscalYear, metric: metric)
        }
    }
}

extension Comparison {
    func map<T: Sendable & Hashable>(_ transform: (Value) -> T) -> Comparison<T> {
        switch self {
        case .result(let value): .result(transform(value))
        case .refusal(let refusal): .refusal(refusal)
        }
    }
}

/// One company's operating margin with its two inputs.
public struct MarginCalculation: Sendable, Hashable {
    public let company: Company
    public let result: OperatingMargin
    public let revenue: Figure
    public let operatingIncome: Figure
    public let source: Filing?
}

public enum CompanyCalculation: Sendable, Hashable {
    case growth(YearCalculation)
    case margin(MarginCalculation)

    public var company: Company {
        switch self {
        case .growth(let calculation): calculation.company
        case .margin(let calculation): calculation.company
        }
    }
}

/// What the cross-company caveat names (PRODUCT.md: K-IFRS vs US GAAP and year-ends). It is
/// always shown, also when both match.
public struct CrossCompanyCaveat: Sendable, Hashable {
    public let companies: [Company]
    public let standards: [AccountingStandard]
    /// Nil for a company whose `fiscal_year_end` is not a valid `MM-DD`.
    public let yearEndMonths: [Int?]
    /// The fiscal year each company's rate is for, and the day that year ends.
    public let fiscalYears: [Int?]
    public let periodEnds: [CivilDate?]

    init(companies: [Company], inputs: [CompanyInputs]) {
        self.companies = companies
        standards = companies.map(\.accountingStandard)
        yearEndMonths = companies.map(\.fiscalYearEndMonth)
        fiscalYears = inputs.map(\.fiscalYear)
        periodEnds = inputs.map { $0.figures.last?.periodEnd }
    }

    public var standardsDiffer: Bool { Set(standards).count > 1 }
    /// Every company's year-end month is known; otherwise the caveat leaves year-ends out.
    public var yearEndsKnown: Bool { !yearEndMonths.contains(nil) }
    public var yearEndsDiffer: Bool { yearEndsKnown && Set(yearEndMonths).count > 1 }

    /// The two years compared are not the same period: their labels differ, or they end
    /// more than a month apart.
    public var periodsDiffer: Bool {
        let years = fiscalYears.compactMap { $0 }
        if years.count == fiscalYears.count, Set(years).count > 1 { return true }
        let ends = periodEnds.compactMap { $0 }
        guard ends.count == 2, ends.count == periodEnds.count else { return false }
        return abs(ends[0].days(to: ends[1])) > 31
    }
}

// MARK: - Refusals (boards 8, 10)

/// The company and year a comparison needed and the bundle does not have.
public struct MissingYear: Sendable, Hashable {
    public let companyID: String
    /// Nil when the company has no figure for the metric in any year.
    public let fiscalYear: Int?
    public let metric: ReportedMetric?
}

/// A refusal with the data its explanation names and the comparisons still possible.
public struct RefusalExplanation: Sendable, Hashable {
    public enum Context: Sendable, Hashable {
        case lastYear
        /// The measure that was asked for.
        case company(CrossCompanyMeasure?)
    }

    public let refusal: Refusal
    public let context: Context
    public let companies: [Company]
    /// The company whose own figures caused the refusal, when one did.
    public let culpritID: String?
    public let metric: ReportedMetric?
    public let missing: MissingYear?
    /// The zero or negative baseline of a `nonpositive_baseline` refusal.
    public let baseline: Figure?
    /// At least one, in the order the screen lists them.
    public let actions: [RefusalAction]
}

/// What the refusal screen offers instead (board 10: "at least one comparison that is
/// possible").
public enum RefusalAction: Sendable, Hashable {
    /// Back to the figure to choose what to compare.
    case chooseFigure
    /// The years the bundle has for a company's figure.
    case showYears(companyID: String)
    /// The figures the app covers: the company's annual page.
    case coveredFigures(companyID: String)
    /// The same two companies with another measure.
    case compare(CrossCompanyMeasure)

    static func forLastYear(_ refusal: Refusal, company: Company) -> [RefusalAction] {
        switch refusal.reason {
        case .ambiguousRequest: [.chooseFigure]
        case .metricOutOfScope: [.coveredFigures(companyID: company.id)]
        case .unsupportedBasis, .missingPeriod, .incompatibleCurrency, .incompatibleComparison:
            [.showYears(companyID: company.id)]
        }
    }

    static func forCompany(
        _ refusal: Refusal, measure: CrossCompanyMeasure?, metric: ReportedMetric?, culprit: Company,
        base: Company
    ) -> [RefusalAction] {
        // Growth needs a reported metric; the margin always has its two inputs' metrics.
        let rates: [CrossCompanyMeasure] = metric == nil ? [.operatingMargin] : [.operatingMargin, .growthRate]
        let others = rates.filter { $0 != measure }.map(RefusalAction.compare)
        switch refusal.reason {
        case .ambiguousRequest:
            return rates.map(RefusalAction.compare)
        case .metricOutOfScope:
            return others + [.coveredFigures(companyID: base.id)]
        case .unsupportedBasis, .missingPeriod:
            return others + [.showYears(companyID: culprit.id)]
        case .incompatibleCurrency:
            return others
        case .incompatibleComparison:
            return measure == .absoluteAmount ? others : others + [.showYears(companyID: culprit.id)]
        }
    }
}
