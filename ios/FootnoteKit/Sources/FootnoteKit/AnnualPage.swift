import Foundation

/// What an annual report's page shows (DESIGN.md, Annual at a glance; board 4): the approved
/// summary sections, then every metric for the report's fiscal year and the year before, on
/// one basis, with the change worked out by `Calculator`.
public struct AnnualPage: Sendable {
    public let filing: Filing
    public let company: Company
    public let dataAsOf: CivilDate
    /// The report's fiscal year (`FY2025` -> 2025); nil when the filing names none, and then
    /// no figures are shown.
    public let fiscalYear: Int?
    /// `consolidated` when the company has consolidated figures for these years.
    public let basis: String?
    /// One row per reported metric that has a figure in either year, in vocabulary order.
    public let rows: [AnnualFigureRow]
    /// Operating income over revenue, for each year that has both.
    public let margin: AnnualMarginRow?
    /// Reported metrics with no figure in either year.
    public let notStated: [ReportedMetric]
    public let source: SourceDetails
    private let summaries: [FilingSummary]

    public init?(store: BundleStore, filingID: String) {
        guard let filing = store.filing(id: filingID), filing.kind == .annual,
              let company = store.company(id: filing.companyID)
        else { return nil }
        self.filing = filing
        self.company = company
        dataAsOf = store.meta.dataAsOf
        summaries = store.summaries.filter { $0.filingID == filing.id }
        source = SourceDetails(filing: filing, regulator: company.regulator)
        let year = Self.fiscalYear(filing)
        fiscalYear = year
        guard let year else {
            basis = nil
            rows = []
            margin = nil
            notStated = []
            return
        }
        let years = store.figures.filter {
            $0.companyID == company.id && ($0.fiscalYear == year || $0.fiscalYear == year - 1)
                && Calculator.supportedBases.contains($0.basis)
        }
        let basis = years.contains { $0.basis == "consolidated" } ? "consolidated" : years.first?.basis
        self.basis = basis
        let onBasis = years.filter { $0.basis == basis }
        func figure(_ metric: ReportedMetric, _ fiscalYear: Int) -> Figure? {
            onBasis.first { $0.metric == metric && $0.fiscalYear == fiscalYear }
        }
        var rows: [AnnualFigureRow] = []
        var notStated: [ReportedMetric] = []
        for metric in ReportedMetric.allCases {
            let current = figure(metric, year), prior = figure(metric, year - 1)
            guard current != nil || prior != nil else {
                notStated.append(metric)
                continue
            }
            rows.append(AnnualFigureRow(metric: metric, current: current, prior: prior))
        }
        self.rows = rows
        self.notStated = notStated
        let margins = [year, year - 1].map { fiscalYear -> Comparison<OperatingMargin>? in
            guard let revenue = figure(.revenue, fiscalYear),
                  let income = figure(.operatingIncome, fiscalYear)
            else { return nil }
            return Calculator.operatingMargin(
                metric: DerivedMetric.operatingMargin.rawValue, facts: [revenue.fact, income.fact])
        }
        margin = margins.contains { $0 != nil }
            ? AnnualMarginRow(fiscalYear: year, current: margins[0], prior: margins[1]) : nil
    }

    /// `FY2025` -> 2025.
    static func fiscalYear(_ filing: Filing) -> Int? {
        guard let label = filing.periodLabel, label.hasPrefix("FY"), label.count == 6 else { return nil }
        return Int(label.dropFirst(2))
    }

    /// The currency of the figures, or the company's.
    public var currency: String {
        rows.lazy.compactMap { ($0.current ?? $0.prior)?.currency }.first ?? company.currency
    }

    /// The approved lines of one section in `language`; empty while it is in review.
    public func lines(_ section: SummarySection, _ language: Language) -> [String] {
        summaries.first { $0.language == language && $0.section == section }?.lines ?? []
    }

    /// The sections board 4 shows below the one line, in order. Risks appear only when the
    /// report has them.
    public static let sections: [SummarySection] = [.business, .changes, .risks]

    /// True when no section of the annual summary is approved in `language`.
    public func summaryInReview(_ language: Language) -> Bool {
        ([.oneLine] + Self.sections).allSatisfy { lines($0, language).isEmpty }
    }
}

/// One metric for the report's year and the year before.
public struct AnnualFigureRow: Sendable, Hashable, Identifiable {
    public let metric: ReportedMetric
    public let current: Figure?
    public let prior: Figure?

    public var id: String { metric.rawValue }

    /// Nil when either year has no figure; otherwise the result or the calculator's refusal.
    public var comparison: Comparison<YearOverYear>? {
        guard let current, let prior else { return nil }
        return Calculator.yearOverYear(metric: metric.rawValue, facts: [prior.fact, current.fact])
    }

    public var isRestated: Bool { current?.isRestated == true || prior?.isRestated == true }
}

/// The derived operating margin for both years; a year without both inputs is nil.
public struct AnnualMarginRow: Sendable, Hashable {
    public let fiscalYear: Int
    public let current: Comparison<OperatingMargin>?
    public let prior: Comparison<OperatingMargin>?
}
