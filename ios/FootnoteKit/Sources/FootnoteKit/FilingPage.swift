import Foundation

/// What an event filing's page shows, derived from a bundle (DESIGN.md, Screens; board 12A).
/// The order is fixed for every type: sentences, then numbers, then the original. Every list
/// is already capped and ordered, so the view only lays it out.
public struct FilingPage: Sendable {
    /// DESIGN.md: up to six numbers per filing page.
    public static let maxNumbers = 6

    public let filing: Filing
    public let company: Company
    public let dataAsOf: CivilDate
    /// The numbers the filing states, grouped. Empty when it states none: the section is
    /// then removed (board 19, no_numbers).
    public let blocks: [FactBlock]
    public let source: SourceDetails
    /// A clarification's status, read from the report name DART gives it.
    public let clarificationStatus: ClarificationStatus?
    /// An outlook table filing whose every outlook cell is `-` (board 19,
    /// outlook_without_figures). A prose outlook filing (장래사업ㆍ경영계획) is never one.
    public let outlookHasNoFigures: Bool
    private let summaries: [FilingSummary]

    public init?(store: BundleStore, filingID: String) {
        guard let filing = store.filing(id: filingID),
              let company = store.company(id: filing.companyID)
        else { return nil }
        self.filing = filing
        self.company = company
        dataAsOf = store.meta.dataAsOf
        summaries = store.summaries.filter { $0.filingID == filing.id }
        source = SourceDetails(filing: filing, regulator: company.regulator)
        let facts = store.facts(forFiling: filing.id)
        let reportName = Titles.parseDart(filing.titleOriginal).base
        blocks = Self.blocks(facts: facts, reportName: reportName)
        clarificationStatus = filing.category == .clarification
            ? ClarificationStatus(reportName: filing.titleOriginal) : nil
        outlookHasNoFigures = filing.category == .outlook
            && Self.outlookTables.contains(reportName)
            && !facts.contains { $0.origin.hasPrefix("dartdoc:outlook.") && $0.value.decimal != nil }
    }

    /// DART report names whose content is the outlook table (D78); 장래사업ㆍ경영계획 is prose.
    static let outlookTables: Set<String> = ["영업실적등에대한전망", "연결재무제표기준영업실적등에대한전망"]

    public var isOutlook: Bool { filing.category == .outlook }

    /// The approved lines in `language` (the bundle holds nothing else); empty while the
    /// summary is in review.
    public func summaryLines(_ language: Language) -> [String] {
        summaries.first { $0.language == language && $0.section == .summary }?.lines ?? []
    }

    /// How many numbers the blocks show, for the six-number budget.
    public var numberCount: Int { blocks.map(\.count).reduce(0, +) }

    static func blocks(facts: [FilingFact], reportName: String) -> [FactBlock] {
        var blocks: [FactBlock] = []
        if let results = ComparisonBlock.results(facts, reportName: reportName) {
            blocks.append(.comparison(results))
        }
        if let change = ComparisonBlock.change(facts) { blocks.append(.comparison(change)) }
        if let units = ComparisonBlock.units(facts) { blocks.append(.comparison(units)) }
        blocks += OutlookBlock.blocks(facts).map(FactBlock.outlook)
        let rows = FactRowValue.rows(facts)
        if !rows.isEmpty { blocks.append(.rows(rows)) }
        // The budget holds across blocks: later blocks lose rows first.
        var left = maxNumbers
        return blocks.compactMap { block in
            let capped = block.capped(to: left)
            left -= capped?.count ?? 0
            return capped
        }
    }
}

// MARK: - Blocks

public enum FactBlock: Sendable, Hashable {
    /// Figures the filing states for this period and for a base period, such as preliminary
    /// results against the same period a year earlier.
    case comparison(ComparisonBlock)
    /// Figures the company gave as its outlook; never compared with anything.
    case outlook(OutlookBlock)
    /// Plain label and value rows (a buyback's shares and price, a dividend's dates).
    case rows([FactRowValue])

    var count: Int {
        switch self {
        case .comparison(let block): block.rows.count
        case .outlook(let block): block.items.count
        case .rows(let rows): rows.count
        }
    }

    func capped(to limit: Int) -> FactBlock? {
        guard limit > 0 else { return nil }
        switch self {
        case .comparison(var block):
            block.rows = Array(block.rows.prefix(limit))
            return .comparison(block)
        case .outlook(var block):
            block.items = Array(block.items.prefix(limit))
            return .outlook(block)
        case .rows(let rows):
            return .rows(Array(rows.prefix(limit)))
        }
    }
}

/// A plain or bilingual name for a row.
public struct RowName: Sendable, Hashable {
    public let ko: String
    public let en: String

    public init(_ ko: String, _ en: String) {
        self.ko = ko
        self.en = en
    }

    public func text(_ language: Language) -> String { language == .ko ? ko : en }
}

public struct ComparisonBlock: Sendable, Hashable {
    public enum Kind: Sendable, Hashable {
        /// 잠정실적: this period against the same period a year earlier.
        case results
        /// 매출액또는손익구조 변경: this fiscal year against the previous one.
        case change
        /// 판매 실적: units sold against the same period a year earlier.
        case units
    }

    public enum Basis: Sendable, Hashable { case consolidated, separate }

    public let kind: Kind
    /// Only what the filing says: nil when it does not name its basis.
    public let basis: Basis?
    public let period: DatePeriod?
    public let basePeriod: DatePeriod?
    public internal(set) var rows: [ComparedValue]

    /// Board 15's names: 매출, 영업이익, 순이익, 지배주주 순이익.
    static let metrics: [(key: String, name: RowName)] = [
        ("revenue", RowName("매출", "Revenue")),
        ("operating_income", RowName("영업이익", "Operating income")),
        ("net_income", RowName("순이익", "Net income")),
        ("net_income_attributable", RowName("지배주주 순이익", "Net income, owners")),
    ]

    static func results(_ facts: [FilingFact], reportName: String) -> ComparisonBlock? {
        let table = Table(facts, prefix: "dartdoc:results.results_")
        let rows = metrics.compactMap { metric in
            table.compared(metric.name, current: "\(metric.key)_current", base: "\(metric.key)_year_ago")
        }
        guard !rows.isEmpty else { return nil }
        return ComparisonBlock(
            kind: .results,
            basis: reportName.hasPrefix("연결") ? .consolidated : nil,
            period: table.period("period_start", "period_end"),
            basePeriod: table.period("year_ago_start", "year_ago_end"),
            rows: rows)
    }

    static func change(_ facts: [FilingFact]) -> ComparisonBlock? {
        let table = Table(facts, prefix: "dartdoc:change.change_")
        let rows = metrics.compactMap { metric in
            table.compared(metric.name, current: "\(metric.key)_current", base: "\(metric.key)_prior")
        }
        guard !rows.isEmpty else { return nil }
        let statement = table.text("statement") ?? ""
        let basis: Basis? = statement.contains("연결") ? .consolidated
            : statement.contains("별도") ? .separate : nil
        return ComparisonBlock(
            kind: .change, basis: basis,
            period: table.period("period_start", "period_end"),
            basePeriod: table.period("prior_start", "prior_end"),
            rows: rows)
    }

    static func units(_ facts: [FilingFact]) -> ComparisonBlock? {
        let table = Table(facts, prefix: "dartdoc:units.units_")
        let parts: [(String, RowName)] = [
            ("total", RowName("전체 판매", "Total units sold")),
            ("domestic", RowName("국내", "Korea")),
            ("overseas", RowName("해외", "Overseas")),
        ]
        var rows = parts.compactMap { key, name in
            table.compared(name, current: "\(key)_current", base: "\(key)_year_ago")
        }
        if let cumulative = table.compared(
            RowName("올해 누적 판매", "Year to date, total"),
            current: "total_cumulative", base: "total_cumulative_year_ago", yearToDate: true)
        {
            rows.append(cumulative)
        }
        guard !rows.isEmpty else { return nil }
        return ComparisonBlock(
            kind: .units, basis: nil, period: table.period("period_start", "period_end"),
            basePeriod: nil, rows: rows)
    }
}

/// One figure the filing states, with the base-period figure it states beside it.
public struct ComparedValue: Sendable, Hashable {
    public let name: RowName
    public let current: Decimal
    public let base: Decimal?
    /// The fact's unit as stored (`백만원`, `대`).
    public let unit: String?
    /// The change from the base in percent, rounded half-up to two places; nil when the
    /// filing states no base or the base is zero or negative.
    public let change: Decimal?
    /// The cumulative row of a unit-sales table (year to date).
    public let isYearToDate: Bool

    /// True when the filing states a base that is zero or negative, so no rate is shown.
    public var baseNotPositive: Bool { base.map { $0 <= 0 } ?? false }
}

/// A DART table's facts by key, after a fixed origin prefix.
private struct Table {
    let values: [String: FilingFact]

    init(_ facts: [FilingFact], prefix: String) {
        var values: [String: FilingFact] = [:]
        for fact in facts where fact.origin.hasPrefix(prefix) {
            values[String(fact.origin.dropFirst(prefix.count))] = fact
        }
        self.values = values
    }

    func compared(
        _ name: RowName, current: String, base: String, yearToDate: Bool = false
    ) -> ComparedValue? {
        guard let fact = values[current], let value = fact.value.decimal else { return nil }
        let baseFact = values[base].flatMap { $0.unit == fact.unit ? $0 : nil }
        let baseValue = baseFact?.value.decimal
        return ComparedValue(
            name: name, current: value, base: baseValue, unit: fact.unit,
            change: baseValue.flatMap { Calculator.percentage(value - $0, of: $0) },
            isYearToDate: yearToDate)
    }

    func period(_ start: String, _ end: String) -> DatePeriod? {
        guard case .date(let first)? = values[start]?.value, case .date(let last)? = values[end]?.value,
              first <= last
        else { return nil }
        return DatePeriod(start: first, end: last)
    }

    func text(_ key: String) -> String? {
        if case .text(let text)? = values[key]?.value { return text }
        return nil
    }
}

/// One column of a company outlook table (D78): the year it covers and its items. A
/// corrected outlook carries each corrected item's value before the correction.
public struct OutlookBlock: Sendable, Hashable {
    /// As the filing writes it, for example `2026`.
    public let year: String?
    public internal(set) var items: [OutlookItem]

    static let metricNames: [(key: String, filingName: String, name: RowName)] = [
        ("revenue", "매출액", RowName("매출", "Revenue")),
        ("operating_income", "영업이익", RowName("영업이익", "Operating income")),
        ("pretax_income", "법인세비용차감전계속사업이익", RowName("세전 이익", "Income before taxes")),
        ("net_income", "당기순이익", RowName("순이익", "Net income")),
    ]

    static func blocks(_ facts: [FilingFact]) -> [OutlookBlock] {
        let table = Table(facts, prefix: "dartdoc:outlook.outlook_")
        let corrections: [(label: String, before: Decimal, after: Decimal)] = (1...6).compactMap {
            guard let label = table.text("change\($0)_label"),
                  let before = table.values["change\($0)_before"]?.value.decimal,
                  let after = table.values["change\($0)_after"]?.value.decimal
            else { return nil }
            return (label, before, after)
        }
        var used: Set<Int> = []
        func before(label: String, filingName: String?, value: Decimal) -> Decimal? {
            for (index, correction) in corrections.enumerated() where !used.contains(index) {
                let named = correction.label == label
                    || filingName.map { correction.label.hasSuffix($0) } ?? false
                if named && correction.after == value {
                    used.insert(index)
                    return correction.before
                }
            }
            return nil
        }
        var blocks: [OutlookBlock] = []
        for column in 1...3 {
            var items: [OutlookItem] = []
            for metric in metricNames {
                guard let fact = table.values["\(metric.key)_y\(column)"],
                      let value = fact.value.decimal
                else { continue }
                items.append(OutlookItem(
                    label: .metric(metric.name), value: value, unit: fact.unit,
                    before: before(label: metric.filingName, filingName: metric.filingName, value: value)))
            }
            for item in 1...6 {
                guard let label = table.text("item\(item)_label"),
                      let fact = table.values["item\(item)_y\(column)"],
                      let value = fact.value.decimal
                else { continue }
                items.append(OutlookItem(
                    label: .filing(label), value: value, unit: fact.unit,
                    before: before(label: label, filingName: nil, value: value)))
            }
            if !items.isEmpty {
                blocks.append(OutlookBlock(year: table.text("year_y\(column)"), items: items))
            }
        }
        return blocks
    }
}

public struct OutlookItem: Sendable, Hashable {
    public enum Label: Sendable, Hashable {
        /// One of the table's fixed rows (매출액, 영업이익 and so on).
        case metric(RowName)
        /// A row the company named itself, as written (`2026년 판매목표(대수)-국내`).
        case filing(String)
    }

    public let label: Label
    public let value: Decimal
    public let unit: String?
    /// The value before the correction, when this filing corrected the item.
    public let before: Decimal?

    /// The row name. A company-named row keeps the company's words, except the sales-target
    /// rows of the DART form (`2026년 판매목표(대수)-국내`), which read as 전체, 국내 and 해외
    /// / Total, Korea and Overseas under a heading that names the year. A label for another
    /// year than `blockYear`, or any other label, stays as written in both languages.
    public func name(_ language: Language, blockYear: String?) -> String {
        switch label {
        case .metric(let name): return name.text(language)
        case .filing(let text): return Self.filingName(text, language, blockYear: blockYear)
        }
    }

    static let salesTarget = "판매목표(대수)"

    static func filingName(_ text: String, _ language: Language, blockYear: String?) -> String {
        guard let blockYear else { return text }
        // Spaces are ignored: DART forms differ in where they put them.
        let prefix = "\(blockYear)년\(salesTarget)"
        let compact = text.replacingOccurrences(of: " ", with: "")
        guard compact.hasPrefix(prefix) else { return text }
        switch compact.dropFirst(prefix.count) {
        case "": return language == .ko ? "전체" : "Total"
        case "-국내": return language == .ko ? "국내" : "Korea"
        case "-해외": return language == .ko ? "해외" : "Overseas"
        default: return text
        }
    }

    /// True for the sales-target rows, so the block can be titled as targets.
    public var isSalesTarget: Bool {
        if case .filing(let text) = label { return text.contains(Self.salesTarget) }
        return false
    }
}

/// A label and value row.
public struct FactRowValue: Sendable, Hashable {
    public enum Value: Sendable, Hashable {
        case stated(Decimal, unit: String?)
        case date(CivilDate)
        case dateRange(CivilDate, CivilDate)
        case text(String)
    }

    public let name: RowName
    public let value: Value
    /// The fact's origin, for VoiceOver and tests.
    public let origin: String

    /// Facts with a plain name, in `FactNames` order. A `_start` date with its `_end` is
    /// one row: a single day when both match, a period otherwise.
    static func rows(_ facts: [FilingFact]) -> [FactRowValue] {
        let byOrigin = Dictionary(facts.map { ($0.origin, $0) }, uniquingKeysWith: { first, _ in first })
        var rows: [(rank: Int, row: FactRowValue)] = []
        for fact in facts {
            guard let name = FactNames.name(origin: fact.origin), let rank = FactNames.rank[fact.origin]
            else { continue }
            let value: Value
            switch fact.value {
            case .amount(let amount), .shares(let amount), .ratio(let amount):
                value = .stated(amount, unit: fact.unit)
            case .text(let text):
                value = .text(text)
            case .date(let start):
                if let endOrigin = endOrigin(for: fact.origin),
                   case .date(let end)? = byOrigin[endOrigin]?.value, end != start
                {
                    rows.append((rank, FactRowValue(
                        name: RowName(name.periodKo ?? name.ko, name.periodEn ?? name.en),
                        value: .dateRange(start, end), origin: fact.origin)))
                    continue
                }
                value = .date(start)
            }
            rows.append((rank, FactRowValue(name: RowName(name.ko, name.en), value: value, origin: fact.origin)))
        }
        return rows.sorted { $0.rank < $1.rank }.map(\.row)
    }

    /// The end of a period whose start is `origin`: `…_bgd` pairs with `…_edd`.
    static func endOrigin(for origin: String) -> String? {
        let pairs = ["aqexpd_bgd": "aqexpd_edd", "dpprpd_bgd": "dpprpd_edd"]
        for (start, end) in pairs where origin.hasSuffix(start) {
            return String(origin.dropLast(start.count)) + end
        }
        return nil
    }
}

// MARK: - Clarification and source

public enum ClarificationStatus: Sendable, Hashable {
    /// 미확정: the company says the matter is not decided yet.
    case undecided

    init?(reportName: String) {
        if reportName.contains("(미확정)") { self = .undecided } else { return nil }
    }
}

/// A span of days, both ends inclusive.
public struct DatePeriod: Sendable, Hashable {
    public let start: CivilDate
    public let end: CivilDate
}

/// What the bundle says about the original document, readable offline.
public struct SourceDetails: Sendable, Hashable {
    public let regulator: Regulator
    /// As the regulator names it: `사업보고서`, `8-K`.
    public let form: String
    public let filedOn: CivilDate
    /// DART's 접수번호 or SEC's accession number.
    public let receiptNumber: String
    public let url: URL?

    init(filing: Filing, regulator: Regulator) {
        self.regulator = regulator
        form = filing.form
        filedOn = filing.filedOn
        let prefix = regulator == .dart ? "dart:" : "sec:"
        receiptNumber = filing.id.hasPrefix(prefix) ? String(filing.id.dropFirst(prefix.count)) : filing.id
        url = URL(string: filing.sourceURL)
    }
}
