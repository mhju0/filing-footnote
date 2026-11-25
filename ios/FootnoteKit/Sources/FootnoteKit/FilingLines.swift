import Foundation

// A filing row's second line and the search across filings and terms (2026-11-26 review,
// issues 3, 13 and 15; D100). The second line is only ever an approved summary line: the
// bundle holds nothing else (`BundleStore` refuses any other review state).

extension BundleStore {
    /// The first line of a filing's approved summary in `language`; nil when it has none, so
    /// the row then shows no second line.
    public func firstSummaryLine(filingID: String, language: Language) -> String? {
        summary(forFiling: filingID, language: language, section: .summary)?.lines.first
    }
}

extension Titles {
    /// The ids of the filings whose title in `language` another filing in `filings` shares
    /// (`기타 경영 사항` twice on one company page).
    public static func repeatedTitleIDs(_ filings: [Filing], language: Language) -> Set<String> {
        let titles = filings.map { ($0.id, title(for: $0, language: language)) }
        var counts: [String: Int] = [:]
        for (_, title) in titles { counts[title, default: 0] += 1 }
        return Set(titles.filter { counts[$0.1, default: 0] > 1 }.map(\.0))
    }
}

/// Search text compared the way the Companies field compares it: case, accents, width,
/// spaces, dots and hyphens ignored.
public enum SearchText {
    public static func normalized(_ text: String) -> String {
        text.folding(options: [.caseInsensitive, .diacriticInsensitive, .widthInsensitive], locale: nil)
            .filter { !$0.isWhitespace && $0 != "." && $0 != "-" }
    }
}

/// What the Companies search finds besides companies: recent filings whose type or title
/// matches (`배당` finds the dividend decisions), and glossary terms.
public struct DirectoryMatches: Sendable {
    /// At most this many of each kind, so companies stay the first thing the field finds.
    public static let maxFilings = 5
    public static let maxTerms = 5

    /// Newest first, from the filings the company pages list (`NewsFeed`).
    public let filings: [Filing]
    /// How many filings matched, including those not shown.
    public let filingCount: Int
    /// In dictionary order for `language`.
    public let terms: [GlossaryEntry]

    public var isEmpty: Bool { filings.isEmpty && terms.isEmpty }
}

extension BundleStore {
    /// Filings and terms that match `query` in either language. An empty query matches
    /// nothing.
    public func directoryMatches(_ query: String, language: Language) -> DirectoryMatches {
        let needle = SearchText.normalized(query)
        guard !needle.isEmpty else { return DirectoryMatches(filings: [], filingCount: 0, terms: []) }
        let matched = newsFeed.allFilings.filter { filing in
            Language.allCases.contains { language in
                SearchText.normalized(filing.category.label(language)).contains(needle)
                    || SearchText.normalized(Titles.title(for: filing, language: language)).contains(needle)
            }
        }
        let terms = sortedGlossary(language: language, matching: query)
        return DirectoryMatches(
            filings: Array(matched.prefix(DirectoryMatches.maxFilings)), filingCount: matched.count,
            terms: Array(terms.prefix(DirectoryMatches.maxTerms)))
    }
}
