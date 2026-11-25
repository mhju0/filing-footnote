import Foundation

/// What the company page shows, derived from a bundle (DESIGN.md, Screens). Every list is
/// already capped and ordered, so the view only lays it out.
public struct CompanyPage: Sendable {
    public static let maxPeriodicReports = 2
    public static let maxFilings = 10

    public let company: Company
    public let dataAsOf: CivilDate
    /// The newest quarterly report (I11), shown above the annual reports.
    public let quarterReport: QuarterReport?
    /// Annual reports, newest first: at most two, less one when there is a quarterly report.
    public let periodicReports: [PeriodicReport]
    /// Event filings, newest first, at most ten, grouped by the month they were filed in.
    public let months: [FilingMonth]
    /// Notices filed in the span the listed event filings cover, newest first.
    public let notices: [Notice]
    /// The first day of that span: the oldest listed event filing's date when ten are
    /// listed, otherwise the first day of the 12-month window.
    public let noticesSince: CivilDate
    /// True when ten filings are listed, so older ones in the 12-month window may be left out.
    public let isCapped: Bool

    public init?(store: BundleStore, companyID: String) {
        guard let company = store.company(id: companyID) else { return nil }
        self.company = company
        let dataAsOf = store.meta.dataAsOf
        self.dataAsOf = dataAsOf
        let quarterReport = QuarterReport(store: store, companyID: companyID)
        self.quarterReport = quarterReport
        periodicReports = store.annualFilings(forCompany: companyID)
            .prefix(Self.maxPeriodicReports - (quarterReport == nil ? 0 : 1))
            .map { PeriodicReport(filing: $0, store: store) }
        let windowStart = Self.windowStart(endingOn: dataAsOf)
        let inWindow = store.eventFilings(forCompany: companyID)
            .filter { $0.filedOn >= windowStart && $0.filedOn <= dataAsOf }
        let events = Array(inWindow.prefix(Self.maxFilings))
        months = FilingMonth.group(events)
        isCapped = inWindow.count >= Self.maxFilings
        let since = isCapped ? events.last?.filedOn ?? windowStart : windowStart
        noticesSince = since
        notices = store.notices(forCompany: companyID).filter { $0.filedOn >= since && $0.filedOn <= dataAsOf }
    }

    /// The first day of the 12 months ending on `date`, both ends inclusive: the day after
    /// the same day a year before (28 February for 29 February). The backend's event ingest
    /// uses the same window (`backend/app/ingest/events.py`, `window_bounds`).
    public static func windowStart(endingOn date: CivilDate) -> CivilDate {
        let year = date.year - 1
        let sameDay = CivilDate(year: year, month: date.month, day: date.day)
            ?? CivilDate(year: year, month: date.month, day: 28)!
        return sameDay.nextDay
    }

    public var filings: [Filing] { months.flatMap(\.filings) }

    /// Notice categories by how many there are, most first; ties keep category order.
    public var noticeCounts: [(category: NoticeCategory, count: Int)] {
        NoticeCategory.allCases
            .map { category in (category, notices.filter { $0.category == category }.count) }
            .filter { $0.1 > 0 }
            .enumerated()
            .sorted { ($0.element.1, -$0.offset) > ($1.element.1, -$1.offset) }
            .map { (category: $0.element.0, count: $0.element.1) }
    }

    /// Every filing of the company on the regulator's own site.
    public var allFilingsURL: URL? { Links.allFilings(of: company) }
}

/// An annual report with its one figure: revenue, and the change from the year before when
/// both years are on the same basis.
public struct PeriodicReport: Sendable, Hashable {
    public let filing: Filing
    public let revenue: Figure?
    /// The year before's revenue on the same basis, when the change could be worked out.
    public let prior: Figure?
    public let change: YearOverYear?

    /// The figures on this row that a later report restated, current year first.
    public var restated: [Figure] { [revenue, prior].compactMap { $0 }.filter(\.isRestated) }

    init(filing: Filing, store: BundleStore) {
        self.filing = filing
        let revenues = store.figures(forCompany: filing.companyID, metric: .revenue)
            .filter { Calculator.supportedBases.contains($0.basis) }
        // Consolidated first, then the figure this filing itself states.
        func rank(_ figure: Figure) -> (Int, Int) {
            (figure.basis == "consolidated" ? 0 : 1, figure.filingID == filing.id ? 0 : 1)
        }
        let current = revenues.filter { $0.fiscalYear == filingYear(filing) }
            .min { rank($0) < rank($1) }
        revenue = current
        guard let current,
              let prior = revenues.first(where: {
                  $0.fiscalYear == current.fiscalYear - 1 && $0.basis == current.basis
              })
        else {
            prior = nil
            change = nil
            return
        }
        self.prior = prior
        switch Calculator.yearOverYear(metric: "revenue", facts: [prior.fact, current.fact]) {
        case .result(let result): change = result
        case .refusal: change = nil
        }
    }
}

/// `FY2025` -> 2025.
private func filingYear(_ filing: Filing) -> Int? {
    guard let label = filing.periodLabel, label.hasPrefix("FY") else { return nil }
    return Int(label.dropFirst(2))
}

/// Filings filed in one calendar month, newest first.
public struct FilingMonth: Sendable, Hashable, Identifiable {
    public let year: Int
    public let month: Int
    public let filings: [Filing]

    public var id: String { "\(year)-\(month)" }

    /// Groups filings already sorted newest first, keeping their order.
    public static func group(_ filings: [Filing]) -> [FilingMonth] {
        var result: [FilingMonth] = []
        var current: [Filing] = []
        for filing in filings {
            if let first = current.first,
               (first.filedOn.year, first.filedOn.month) != (filing.filedOn.year, filing.filedOn.month) {
                result.append(FilingMonth(year: first.filedOn.year, month: first.filedOn.month, filings: current))
                current = []
            }
            current.append(filing)
        }
        if let first = current.first {
            result.append(FilingMonth(year: first.filedOn.year, month: first.filedOn.month, filings: current))
        }
        return result
    }
}

public enum Freshness {
    /// Days a filing counts as new: the data date and the six days before it.
    public static let newDays = 7

    /// Filed within seven days of the bundle's data date.
    public static func isNew(_ filedOn: CivilDate, dataAsOf: CivilDate) -> Bool {
        let age = filedOn.days(to: dataAsOf)
        return age >= 0 && age < newDays
    }

    /// 새 공시 / New: an event filing filed within seven days of the data date. Annual and
    /// quarterly reports never get the tag: every company files them in the same weeks, so
    /// the tag would mark them all and tell nothing apart (2026-11-26 review, issue 2).
    public static func isNew(_ filing: Filing, dataAsOf: CivilDate) -> Bool {
        filing.kind == .event && isNew(filing.filedOn, dataAsOf: dataAsOf)
    }
}

/// A company's newest filing or notice, for the Companies list: its date and type
/// (`11월 16일 · 분기 보고서`). The "Latest filing" sort orders companies by the same date.
public struct LatestFiling: Sendable, Hashable {
    public enum Kind: Sendable, Hashable {
        case filing(FilingCategory, halfYear: Bool)
        case notice(NoticeCategory)
    }

    public let filedOn: CivilDate
    public let kind: Kind

    /// The type in the reader's language: the category label, or 반기보고서 / Half-year report
    /// for a DART half-year report, which shares the quarterly category.
    public func label(_ language: Language) -> String {
        switch kind {
        case .filing(_, halfYear: true): language == .ko ? "반기보고서" : "Half-year report"
        case .filing(let category, halfYear: false): category.label(language)
        case .notice(let category): category.label(language)
        }
    }
}

extension BundleStore {
    /// The newest of the company's filings and notices. On the same day a filing wins over a
    /// notice, and the later receipt number over the earlier one.
    public func latestFiling(companyID: String) -> LatestFiling? {
        let filing = filings(forCompany: companyID).max {
            ($0.filedOn, $0.id) < ($1.filedOn, $1.id)
        }
        let notice = notices(forCompany: companyID).max {
            ($0.filedOn, $0.id) < ($1.filedOn, $1.id)
        }
        if let filing, notice.map({ $0.filedOn <= filing.filedOn }) ?? true {
            return LatestFiling(
                filedOn: filing.filedOn,
                kind: .filing(filing.category, halfYear: filing.form == "반기보고서"))
        }
        return notice.map { LatestFiling(filedOn: $0.filedOn, kind: .notice($0.category)) }
    }
}

public enum Links {
    /// DART's filing search for one company, or SEC EDGAR's company page.
    public static func allFilings(of company: Company) -> URL? {
        switch company.regulator {
        case .dart:
            let code = company.id.hasPrefix("dart:") ? String(company.id.dropFirst(5)) : company.id
            var components = URLComponents(string: "https://dart.fss.or.kr/dsab007/main.do")
            components?.queryItems = [
                URLQueryItem(name: "autoSearch", value: "Y"),
                URLQueryItem(name: "option", value: "corp"),
                URLQueryItem(name: "textCrpCik", value: code),
                URLQueryItem(name: "textCrpNm", value: company.nameKo),
            ]
            return components?.url
        case .sec:
            let cik = company.id.hasPrefix("sec:") ? String(company.id.dropFirst(4)) : company.id
            var components = URLComponents(string: "https://www.sec.gov/cgi-bin/browse-edgar")
            components?.queryItems = [
                URLQueryItem(name: "action", value: "getcompany"),
                URLQueryItem(name: "CIK", value: cik),
            ]
            return components?.url
        }
    }
}
