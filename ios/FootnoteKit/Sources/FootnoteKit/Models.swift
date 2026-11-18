import Foundation

/// The single `build_meta` row.
public struct BuildMeta: Sendable, Hashable {
    public let schemaVersion: Int
    public let dataAsOf: CivilDate
    public let sourceRevision: String
    public let llmModel: String
    public let promptVersion: String
    public let contentSHA256: String
    /// True for a development bundle; a release bundle never has it.
    public let allowUnapproved: Bool
}

public struct Company: Sendable, Hashable, Identifiable {
    public let id: String
    public let regulator: Regulator
    public let ticker: String
    public let nameKo: String
    public let nameEn: String
    /// For example `KOSPI`; nil when the regulator gives none (SEC companies today).
    public let market: String?
    public let currency: String
    /// `MM-DD`.
    public let fiscalYearEnd: String
    public let sortOrder: Int

    public func name(_ language: Language) -> String { language == .ko ? nameKo : nameEn }
}

public struct Filing: Sendable, Hashable, Identifiable {
    public let id: String
    public let companyID: String
    public let kind: FilingKind
    public let category: FilingCategory
    public let form: String
    /// SEC 8-K item numbers, comma separated.
    public let secItems: String?
    public let titleOriginal: String
    public let filedOn: CivilDate
    public let periodLabel: String?
    public let sourceURL: String
    public let isCorrected: Bool
    public let sourceTextSHA256: String
}

public struct Notice: Sendable, Hashable, Identifiable {
    public let id: String
    public let companyID: String
    public let category: NoticeCategory
    public let titleOriginal: String
    public let filedOn: CivilDate
    public let sourceURL: String
    public let isCorrected: Bool
}

public struct FilingSummary: Sendable, Hashable {
    public let filingID: String
    public let language: Language
    public let section: SummarySection
    /// One to three lines, in order.
    public let lines: [String]
    public let inputSHA256: String
}

public enum FactValue: Sendable, Hashable {
    case amount(Decimal)
    case shares(Decimal)
    case ratio(Decimal)
    case date(CivilDate)
    case text(String)

    public var kind: FactValueKind {
        switch self {
        case .amount: .amount
        case .shares: .shares
        case .ratio: .ratio
        case .date: .date
        case .text: .text
        }
    }

    /// The exact number for amount, shares and ratio facts.
    public var decimal: Decimal? {
        switch self {
        case .amount(let value), .shares(let value), .ratio(let value): value
        case .date, .text: nil
        }
    }
}

public struct FilingFact: Sendable, Hashable {
    public let filingID: String
    public let position: Int
    public let key: String
    public let value: FactValue
    /// For example `KRW`, `shares` or `percent`.
    public let unit: String?
    public let origin: String
}

public struct Figure: Sendable, Hashable, Identifiable {
    public let id: String
    public let companyID: String
    public let filingID: String
    public let metric: ReportedMetric
    public let fiscalYear: Int
    public let periodStart: CivilDate
    public let periodEnd: CivilDate
    public let value: Decimal
    /// For example `KRW`, `USD` or `KRW_PER_SHARE`.
    public let unit: String
    public let currency: String?
    public let basis: String
    public let isRestated: Bool
    public let regulatorTag: String

    /// The figure as the calculator takes it. `BundleStore` refuses a figure whose period
    /// starts after it ends, and its values are canonical decimals, so this cannot fail.
    public var fact: Fact {
        try! Fact(companyID: companyID, metric: metric.rawValue, value: value, unit: unit,
             currency: currency, basis: basis, periodStart: periodStart, periodEnd: periodEnd,
             isRestated: isRestated)
    }
}

public struct GlossaryEntry: Sendable, Hashable {
    public let termKey: String
    public let language: Language
    public let term: String
    public let plain: String
    public let formal: String?
}
