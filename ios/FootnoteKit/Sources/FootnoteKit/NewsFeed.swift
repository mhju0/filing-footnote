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
    /// True when more eligible filings matched than the feed shows.
    public let isCapped: Bool

    private let eligible: [Filing]

    public init(store: BundleStore) {
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
        self.init(dataAsOf: store.meta.dataAsOf, eligible: listed)
    }

    private init(dataAsOf: CivilDate, eligible: [Filing]) {
        self.dataAsOf = dataAsOf
        self.eligible = eligible
        isCapped = eligible.count > Self.maxFilings
        days = FilingDay.group(Array(eligible.prefix(Self.maxFilings)))
    }

    /// Types available across the company pages, including filings beyond the feed's first page.
    public var availableCategories: [FilingCategory] {
        let present = Set(eligible.map(\.category))
        return FilingCategory.allCases.filter { present.contains($0) }
    }

    /// Applies the type before the overall cap so an older match can still appear.
    public func filtered(to category: FilingCategory) -> NewsFeed {
        NewsFeed(dataAsOf: dataAsOf, eligible: eligible.filter { $0.category == category })
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
    public func sortedGlossary(language: Language, matching query: String = "") -> [GlossaryEntry] {
        let locale = Locale(identifier: language == .ko ? "ko_KR" : "en_US")
        let entries = glossary(language: language)
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        let matching = trimmed.isEmpty ? entries : glossaryMatches(entries, query: trimmed)
        return matching.sorted {
            switch $0.term.compare($1.term, options: [.caseInsensitive], range: nil, locale: locale) {
            case .orderedAscending: true
            case .orderedDescending: false
            case .orderedSame: $0.termKey < $1.termKey
            }
        }
    }

    /// Terms and formal names in either language match the same dictionary entry.
    private func glossaryMatches(_ entries: [GlossaryEntry], query: String) -> [GlossaryEntry] {
        let keys = Set(glossary.compactMap { entry -> String? in
            let names = [entry.term, entry.formal].compactMap { $0 }
            return names.contains {
                $0.range(of: query, options: [.caseInsensitive, .diacriticInsensitive, .widthInsensitive]) != nil
            } ? entry.termKey : nil
        })
        return entries.filter { keys.contains($0.termKey) }
    }
}
