import Foundation

/// What the company page shows, derived from a bundle (DESIGN.md, Screens). Every list is
/// already capped and ordered, so the view only lays it out.
public struct CompanyPage: Sendable {
    public static let maxPeriodicReports = 2
    public static let maxFilings = 10

    public let company: Company
    public let dataAsOf: CivilDate
    /// Annual reports, newest first, at most two.
    public let periodicReports: [PeriodicReport]
    /// Event filings, newest first, at most ten, grouped by the month they were filed in.
    public let months: [FilingMonth]
    /// Notices filed in the span the listed event filings cover, newest first.
    public let notices: [Notice]
    /// The first day of that span: the oldest listed event filing's date.
    public let noticesSince: CivilDate?

    public init?(store: BundleStore, companyID: String) {
        guard let company = store.company(id: companyID) else { return nil }
        self.company = company
        dataAsOf = store.meta.dataAsOf
        periodicReports = store.annualFilings(forCompany: companyID)
            .prefix(Self.maxPeriodicReports)
            .map { PeriodicReport(filing: $0, store: store) }
        let events = Array(store.eventFilings(forCompany: companyID).prefix(Self.maxFilings))
        months = FilingMonth.group(events)
        let since = events.last?.filedOn
        noticesSince = since
        notices = since.map { since in
            store.notices(forCompany: companyID).filter {
                $0.filedOn >= since && $0.filedOn <= store.meta.dataAsOf
            }
        } ?? []
    }

    public var filings: [Filing] { months.flatMap(\.filings) }

    /// True when ten filings are listed, so older ones in the 12-month window may be left out.
    public var isCapped: Bool { filings.count >= Self.maxFilings }

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
    public let change: YearOverYear?

    init(filing: Filing, store: BundleStore) {
        self.filing = filing
        let revenues = store.figures(forCompany: filing.companyID, metric: .revenue)
            .filter { Calculator.supportedBases.contains($0.basis) }
        let current = revenues.first { $0.filingID == filing.id && filingYear(filing) == $0.fiscalYear }
            ?? revenues.first { $0.fiscalYear == filingYear(filing) }
        revenue = current
        guard let current,
              let prior = revenues.first(where: {
                  $0.fiscalYear == current.fiscalYear - 1 && $0.basis == current.basis
              })
        else {
            change = nil
            return
        }
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

    /// 새 공시 / New: filed within seven days of the bundle's data date.
    public static func isNew(_ filedOn: CivilDate, dataAsOf: CivilDate) -> Bool {
        let age = filedOn.days(to: dataAsOf)
        return age >= 0 && age < newDays
    }
}

extension BundleStore {
    /// True when a filing the company page lists is new.
    public func hasNewFiling(companyID: String) -> Bool {
        guard let page = CompanyPage(store: self, companyID: companyID) else { return false }
        return (page.periodicReports.map(\.filing) + page.filings)
            .contains { Freshness.isNew($0.filedOn, dataAsOf: meta.dataAsOf) }
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
