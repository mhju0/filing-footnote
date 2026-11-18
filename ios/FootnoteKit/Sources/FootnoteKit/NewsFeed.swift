import Foundation

/// 소식 / News: the event filings the company pages list, across every company, newest first
/// and grouped by the day they were filed (D86). Built on `CompanyPage`, so a filing shows here
/// only when its company page lists it, and 새 공시 follows the same `Freshness` rule.
public struct NewsFeed: Sendable {
    /// At most this many filings, so the feed stays a short read (DESIGN.md: each screen
    /// shows less). Every company's own page still lists up to ten.
    public static let maxFilings = 30

    public let dataAsOf: CivilDate
    /// Newest day first; each day's filings newest first.
    public let days: [FilingDay]
    /// True when more filings were listed on the company pages than the feed shows.
    public let isCapped: Bool

    public init(store: BundleStore) {
        dataAsOf = store.meta.dataAsOf
        let order = Dictionary(uniqueKeysWithValues: store.companies.map { ($0.id, $0.sortOrder) })
        let listed = store.companies
            .compactMap { CompanyPage(store: store, companyID: $0.id) }
            .flatMap(\.filings)
            // Newest first; on the same day, companies in list order, then the filing id.
            .sorted {
                if $0.filedOn != $1.filedOn { return $0.filedOn > $1.filedOn }
                let left = order[$0.companyID] ?? .max, right = order[$1.companyID] ?? .max
                if left != right { return left < right }
                return $0.id > $1.id
            }
        isCapped = listed.count > Self.maxFilings
        days = FilingDay.group(Array(listed.prefix(Self.maxFilings)))
    }

    public var filings: [Filing] { days.flatMap(\.filings) }

    public var isEmpty: Bool { days.isEmpty }
}

/// Filings filed on one day, in the order given.
public struct FilingDay: Sendable, Hashable, Identifiable {
    public let date: CivilDate
    public let filings: [Filing]

    public var id: String { date.iso }

    /// Groups filings already sorted by date, keeping their order.
    public static func group(_ filings: [Filing]) -> [FilingDay] {
        var result: [FilingDay] = []
        for filing in filings {
            if let last = result.last, last.date == filing.filedOn {
                result[result.count - 1] = FilingDay(date: last.date, filings: last.filings + [filing])
            } else {
                result.append(FilingDay(date: filing.filedOn, filings: [filing]))
            }
        }
        return result
    }
}

extension GlossaryEntry: Identifiable {
    public var id: String { termKey }
}

public enum Glossary {
    /// The entry that explains a filing's category (D81 keys: `category_<key>`).
    public static func key(for category: FilingCategory) -> String { "category_\(category.rawValue)" }

    /// The entry that explains a reported metric (`metric_<key>`).
    public static func key(for metric: ReportedMetric) -> String { "metric_\(metric.rawValue)" }
}

extension BundleStore {
    /// The glossary in one language, ordered like a dictionary by the term the reader sees.
    public func sortedGlossary(language: Language) -> [GlossaryEntry] {
        let locale = Locale(identifier: language == .ko ? "ko_KR" : "en_US")
        return glossary(language: language).sorted {
            switch $0.term.compare($1.term, options: [.caseInsensitive], range: nil, locale: locale) {
            case .orderedAscending: true
            case .orderedDescending: false
            case .orderedSame: $0.termKey < $1.termKey
            }
        }
    }
}
