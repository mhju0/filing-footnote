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

    /// The unit of a rate difference (`%포인트` / percentage points), linked from 차이.
    public static let percentagePoint = "percentage_point"

    /// 자주 보는 용어 / Key terms, in this order, above the dictionary (2026-11-26 review,
    /// issue 12): the figures a first-time reader meets first.
    public static let keyTerms = [
        "metric_revenue", "metric_operating_income", "metric_net_income", "metric_eps",
        "metric_operating_margin",
    ]

    /// The reasons a comparison is refused (`refusal_<reason>`): their own group at the end,
    /// not mixed in with the terms.
    public static func isRefusal(_ termKey: String) -> Bool { termKey.hasPrefix("refusal_") }

    /// The heading a term is filed under: its first Hangul consonant (`매출액` -> `ㅁ`), its
    /// first Latin letter in upper case, or `#`.
    public static func initial(of term: String) -> String {
        guard let first = term.first else { return "#" }
        let consonants = Array("ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ")
        if let scalar = String(first).precomposedStringWithCanonicalMapping.unicodeScalars.first,
           (0xAC00...0xD7A3).contains(scalar.value) {
            return String(consonants[Int((scalar.value - 0xAC00) / 588)])
        }
        if consonants.contains(first) { return String(first) }
        let latin = String(first).folding(options: [.diacriticInsensitive, .widthInsensitive], locale: nil)
            .uppercased()
        return latin.count == 1 && "ABCDEFGHIJKLMNOPQRSTUVWXYZ".contains(latin) ? latin : "#"
    }
}

/// One group of the glossary list: the key terms, the terms under one initial, or the
/// refusal reasons.
public struct GlossarySection: Sendable, Hashable, Identifiable {
    public enum Kind: Sendable, Hashable {
        case keyTerms
        case initial(String)
        case refusals
    }

    public let kind: Kind
    public let entries: [GlossaryEntry]

    public var id: String {
        switch kind {
        case .keyTerms: "key-terms"
        case .initial(let initial): "initial-\(initial)"
        case .refusals: "refusals"
        }
    }
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

    /// The glossary as the list shows it: the key terms first in `Glossary.keyTerms` order,
    /// then the other terms by initial in dictionary order, then the refusal reasons. Each
    /// entry appears once. A search keeps the groups and drops the entries that do not match;
    /// an empty group is left out.
    public func glossarySections(language: Language, matching query: String = "") -> [GlossarySection] {
        let entries = sortedGlossary(language: language, matching: query)
        let keyTerms = Glossary.keyTerms.compactMap { key in entries.first { $0.termKey == key } }
        let refusals = entries.filter { Glossary.isRefusal($0.termKey) }
        var sections = keyTerms.isEmpty ? [] : [GlossarySection(kind: .keyTerms, entries: keyTerms)]
        var initials: [String] = []
        var byInitial: [String: [GlossaryEntry]] = [:]
        for entry in entries where !Glossary.keyTerms.contains(entry.termKey) && !Glossary.isRefusal(entry.termKey) {
            let initial = Glossary.initial(of: entry.term)
            if byInitial[initial] == nil { initials.append(initial) }
            byInitial[initial, default: []].append(entry)
        }
        sections += initials.map { GlossarySection(kind: .initial($0), entries: byInitial[$0]!) }
        if !refusals.isEmpty { sections.append(GlossarySection(kind: .refusals, entries: refusals)) }
        return sections
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
