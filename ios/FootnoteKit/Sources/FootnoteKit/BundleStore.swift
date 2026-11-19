import Foundation
import SQLite3

public enum BundleError: Error, Equatable, Sendable {
    case cannotOpen(path: String, message: String)
    case sqlite(message: String)
    /// `build_meta` must hold exactly one row.
    case missingBuildMeta(rows: Int)
    case unsupportedSchemaVersion(found: Int, supported: Int)
    /// A stored value that breaks the bundle contract, such as an unknown category or a
    /// decimal that is not canonical.
    case invalidValue(table: String, column: String, value: String)
    /// A development bundle (`build_meta.allow_unapproved = 1`) where a release one is required.
    case developmentBundle
}

/// Every row of a bundled `footnote.sqlite`, read once into value types.
///
/// The file is opened read-only, checked for a known `schema_version` before any other table
/// is read, and closed before `init` returns. The schema is `backend/app/build/bundle.py`.
public struct BundleStore: Sendable {
    public static let supportedSchemaVersion = 3

    public let meta: BuildMeta
    /// By `sort_order`.
    public let companies: [Company]
    /// Newest first: `filed_on` descending, then `id` descending.
    public let filings: [Filing]
    /// Newest first, as `filings`.
    public let notices: [Notice]
    /// By filing, language, then section in `SummarySection` order.
    public let summaries: [FilingSummary]
    /// By filing, then position.
    public let facts: [FilingFact]
    /// By company, metric, then `period_end` descending.
    public let figures: [Figure]
    /// Quarter figures (I11): by company, metric, then `period_end` descending.
    public let quarterFigures: [QuarterFigure]
    /// By term key, then language.
    public let glossary: [GlossaryEntry]
    /// The 소식 feed, built once when the bundle is opened.
    private var builtNewsFeed: NewsFeed?

    public init(contentsOf url: URL) throws(BundleError) {
        let db = try Database(path: url.path)
        // The version alone first: another schema may name build_meta's other columns differently.
        let versions = try db.rows("build_meta", "SELECT schema_version FROM build_meta") {
            row throws(BundleError) in try row.int(0)
        }
        guard versions.count == 1 else { throw .missingBuildMeta(rows: versions.count) }
        guard versions[0] == Self.supportedSchemaVersion else {
            throw .unsupportedSchemaVersion(found: versions[0], supported: Self.supportedSchemaVersion)
        }
        let metaRows = try db.rows(
            "build_meta",
            "SELECT schema_version, data_as_of, source_revision, llm_model, prompt_version, "
                + "content_sha256, allow_unapproved FROM build_meta"
        ) { row throws(BundleError) in
            BuildMeta(
                schemaVersion: try row.int(0), dataAsOf: try row.date(1),
                sourceRevision: try row.text(2), llmModel: try row.text(3),
                promptVersion: try row.text(4), contentSHA256: try row.text(5),
                allowUnapproved: try row.bool(6))
        }
        meta = metaRows[0]

        companies = try db.rows(
            "companies",
            "SELECT id, regulator, ticker, name_ko, name_en, market, currency, fiscal_year_end, "
                + "sort_order FROM companies ORDER BY sort_order, id"
        ) { row throws(BundleError) in
            Company(
                id: try row.text(0), regulator: try row.choice(1), ticker: try row.text(2),
                nameKo: try row.text(3), nameEn: try row.text(4), market: try row.optionalText(5),
                currency: try row.text(6), fiscalYearEnd: try row.text(7),
                sortOrder: try row.int(8))
        }
        filings = try db.rows(
            "filings",
            "SELECT id, company_id, kind, category, form, sec_items, title_original, filed_on, "
                + "period_label, source_url, is_corrected, source_text_sha256 FROM filings "
                + "ORDER BY filed_on DESC, id DESC"
        ) { row throws(BundleError) in
            Filing(
                id: try row.text(0), companyID: try row.text(1), kind: try row.choice(2),
                category: try row.choice(3), form: try row.text(4),
                secItems: try row.optionalText(5), titleOriginal: try row.text(6),
                filedOn: try row.date(7), periodLabel: try row.optionalText(8),
                sourceURL: try row.text(9), isCorrected: try row.bool(10),
                sourceTextSHA256: try row.text(11))
        }
        notices = try db.rows(
            "notices",
            "SELECT id, company_id, category, title_original, filed_on, source_url, is_corrected "
                + "FROM notices ORDER BY filed_on DESC, id DESC"
        ) { row throws(BundleError) in
            Notice(
                id: try row.text(0), companyID: try row.text(1), category: try row.choice(2),
                titleOriginal: try row.text(3), filedOn: try row.date(4),
                sourceURL: try row.text(5), isCorrected: try row.bool(6))
        }
        let sectionOrder = Dictionary(
            uniqueKeysWithValues: SummarySection.allCases.enumerated().map { ($1, $0) })
        summaries = try db.rows(
            "filing_summaries",
            "SELECT filing_id, lang, section, line1, line2, line3, review_state, input_sha256 "
                + "FROM filing_summaries ORDER BY filing_id, lang"
        ) { row throws(BundleError) in
            guard try row.text(6) == "approved" else {
                throw .invalidValue(
                    table: "filing_summaries", column: "review_state", value: try row.text(6))
            }
            let lines = [try row.text(3), try row.optionalText(4), try row.optionalText(5)]
            return FilingSummary(
                filingID: try row.text(0), language: try row.choice(1),
                section: try row.choice(2), lines: lines.compactMap { $0 },
                inputSHA256: try row.text(7))
        }.sorted {
            ($0.filingID, $0.language.rawValue, sectionOrder[$0.section]!)
                < ($1.filingID, $1.language.rawValue, sectionOrder[$1.section]!)
        }
        facts = try db.rows(
            "filing_facts",
            "SELECT filing_id, position, fact_key, value_kind, value_text, unit, origin "
                + "FROM filing_facts ORDER BY filing_id, position"
        ) { row throws(BundleError) in
            let kind: FactValueKind = try row.choice(3)
            let value: FactValue = switch kind {
            case .amount: .amount(try row.decimal(4))
            case .shares: .shares(try row.decimal(4))
            case .ratio: .ratio(try row.decimal(4))
            case .date: .date(try row.date(4))
            case .text: .text(try row.text(4))
            }
            return FilingFact(
                filingID: try row.text(0), position: try row.int(1), key: try row.text(2),
                value: value, unit: try row.optionalText(5), origin: try row.text(6))
        }
        figures = try db.rows(
            "figures",
            "SELECT id, company_id, filing_id, metric, fiscal_year, period_start, period_end, "
                + "value, unit, currency, basis, is_restated, regulator_tag FROM figures "
                + "ORDER BY company_id, metric, period_end DESC, id"
        ) { row throws(BundleError) in
            let start = try row.date(5), end = try row.date(6)
            guard start <= end else {
                throw .invalidValue(table: "figures", column: "period_start", value: start.iso)
            }
            return Figure(
                id: try row.text(0), companyID: try row.text(1), filingID: try row.text(2),
                metric: try row.choice(3), fiscalYear: try row.int(4),
                periodStart: start, periodEnd: end,
                value: try row.decimal(7), unit: try row.text(8), currency: try row.optionalText(9),
                basis: try row.text(10), isRestated: try row.bool(11),
                regulatorTag: try row.text(12))
        }
        quarterFigures = try db.rows(
            "quarter_figures",
            "SELECT id, company_id, filing_id, metric, fiscal_year, fiscal_quarter, period_start, "
                + "period_end, value, unit, currency, basis, regulator_tag FROM quarter_figures "
                + "ORDER BY company_id, metric, period_end DESC, id"
        ) { row throws(BundleError) in
            let start = try row.date(6), end = try row.date(7)
            guard start <= end else {
                throw .invalidValue(table: "quarter_figures", column: "period_start", value: start.iso)
            }
            return QuarterFigure(
                id: try row.text(0), companyID: try row.text(1), filingID: try row.text(2),
                metric: try row.choice(3), fiscalYear: try row.int(4), fiscalQuarter: try row.int(5),
                periodStart: start, periodEnd: end, value: try row.decimal(8), unit: try row.text(9),
                currency: try row.optionalText(10), basis: try row.text(11),
                regulatorTag: try row.text(12))
        }
        glossary = try db.rows(
            "glossary",
            "SELECT term_key, lang, term, plain, formal FROM glossary ORDER BY term_key, lang"
        ) { row throws(BundleError) in
            GlossaryEntry(
                termKey: try row.text(0), language: try row.choice(1), term: try row.text(2),
                plain: try row.text(3), formal: try row.optionalText(4))
        }
        builtNewsFeed = NewsFeed(store: self)
    }

    /// 소식 / News for this bundle (D86).
    public var newsFeed: NewsFeed { builtNewsFeed ?? NewsFeed(store: self) }

    /// Throws for a development bundle, which may hold summaries the owner has not approved.
    /// A release build of the app calls this after opening its bundle.
    public func requireRelease() throws(BundleError) {
        if meta.allowUnapproved { throw .developmentBundle }
    }

    // MARK: - Queries the screens use

    public func company(id: String) -> Company? { companies.first { $0.id == id } }

    public func filing(id: String) -> Filing? { filings.first { $0.id == id } }

    /// One group per market, in the order the first company of each market appears in
    /// `sort_order`; companies keep `sort_order` inside a group. A nil market is its own group.
    public func companiesByMarket() -> [MarketGroup] {
        var groups: [MarketGroup] = []
        for company in companies {
            if let index = groups.firstIndex(where: { $0.market == company.market }) {
                groups[index].companies.append(company)
            } else {
                groups.append(MarketGroup(market: company.market, companies: [company]))
            }
        }
        return groups
    }

    public func companies(inMarket market: String?) -> [Company] {
        companies.filter { $0.market == market }
    }

    /// Newest first: `filed_on` descending, then `id` descending.
    public func filings(forCompany companyID: String) -> [Filing] {
        filings.filter { $0.companyID == companyID }
    }

    public func annualFilings(forCompany companyID: String) -> [Filing] {
        filings.filter { $0.companyID == companyID && $0.kind == .annual }
    }

    /// Quarterly reports, newest first.
    public func quarterlyFilings(forCompany companyID: String) -> [Filing] {
        filings.filter { $0.companyID == companyID && $0.kind == .quarterly }
    }

    public func eventFilings(forCompany companyID: String) -> [Filing] {
        filings.filter { $0.companyID == companyID && $0.kind == .event }
    }

    /// Newest first, as `filings(forCompany:)`.
    public func notices(forCompany companyID: String) -> [Notice] {
        notices.filter { $0.companyID == companyID }
    }

    /// In `position` order.
    public func facts(forFiling filingID: String) -> [FilingFact] {
        facts.filter { $0.filingID == filingID }
    }

    /// In `SummarySection` order.
    public func summaries(forFiling filingID: String, language: Language) -> [FilingSummary] {
        summaries.filter { $0.filingID == filingID && $0.language == language }
    }

    public func summary(
        forFiling filingID: String, language: Language, section: SummarySection
    ) -> FilingSummary? {
        summaries.first {
            $0.filingID == filingID && $0.language == language && $0.section == section
        }
    }

    /// Every stored year of one metric, newest `period_end` first.
    public func figures(forCompany companyID: String, metric: ReportedMetric) -> [Figure] {
        figures.filter { $0.companyID == companyID && $0.metric == metric }
    }

    /// Every stored year of one metric on one basis (for example `consolidated`), newest first.
    public func figures(
        forCompany companyID: String, metric: ReportedMetric, basis: String
    ) -> [Figure] {
        figures(forCompany: companyID, metric: metric).filter { $0.basis == basis }
    }

    /// The fiscal years `figures(forCompany:metric:)` covers, newest first.
    public func figureYears(forCompany companyID: String, metric: ReportedMetric) -> [Int] {
        figures(forCompany: companyID, metric: metric).map(\.fiscalYear)
    }

    public func glossary(language: Language) -> [GlossaryEntry] {
        glossary.filter { $0.language == language }
    }

    public func glossaryEntry(termKey: String, language: Language) -> GlossaryEntry? {
        glossary.first { $0.termKey == termKey && $0.language == language }
    }
}

public struct MarketGroup: Sendable, Hashable {
    public let market: String?
    public internal(set) var companies: [Company]
}

// MARK: - SQLite

/// A read-only connection, closed when the value is released.
private final class Database {
    private let handle: OpaquePointer

    init(path: String) throws(BundleError) {
        var handle: OpaquePointer?
        let status = sqlite3_open_v2(path, &handle, SQLITE_OPEN_READONLY, nil)
        guard status == SQLITE_OK, let handle else {
            let message = handle.map { String(cString: sqlite3_errmsg($0)) }
                ?? String(cString: sqlite3_errstr(status))
            sqlite3_close(handle)
            throw .cannotOpen(path: path, message: message)
        }
        self.handle = handle
    }

    deinit { sqlite3_close(handle) }

    func rows<T>(
        _ table: String, _ sql: String, _ make: (Row) throws(BundleError) -> T
    ) throws(BundleError) -> [T] {
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(handle, sql, -1, &statement, nil) == SQLITE_OK, let statement
        else { throw .sqlite(message: String(cString: sqlite3_errmsg(handle))) }
        defer { sqlite3_finalize(statement) }
        var result: [T] = []
        while true {
            let step = sqlite3_step(statement)
            if step == SQLITE_DONE { return result }
            guard step == SQLITE_ROW else {
                throw .sqlite(message: String(cString: sqlite3_errmsg(handle)))
            }
            result.append(try make(Row(statement: statement, table: table)))
        }
    }
}

private struct Row {
    let statement: OpaquePointer
    let table: String

    private func column(_ index: Int32) -> String {
        String(cString: sqlite3_column_name(statement, index))
    }

    private func invalid(_ index: Int32, _ value: String) -> BundleError {
        .invalidValue(table: table, column: column(index), value: value)
    }

    func optionalText(_ index: Int32) throws(BundleError) -> String? {
        switch sqlite3_column_type(statement, index) {
        case SQLITE_NULL: return nil
        case SQLITE_TEXT:
            guard let bytes = sqlite3_column_text(statement, index) else { return nil }
            return String(cString: bytes)
        default: throw invalid(index, "not text")
        }
    }

    func text(_ index: Int32) throws(BundleError) -> String {
        guard let value = try optionalText(index) else { throw invalid(index, "NULL") }
        return value
    }

    func int(_ index: Int32) throws(BundleError) -> Int {
        guard sqlite3_column_type(statement, index) == SQLITE_INTEGER else {
            throw invalid(index, "not an integer")
        }
        return Int(sqlite3_column_int64(statement, index))
    }

    func bool(_ index: Int32) throws(BundleError) -> Bool {
        switch try int(index) {
        case 0: return false
        case 1: return true
        case let other: throw invalid(index, String(other))
        }
    }

    func date(_ index: Int32) throws(BundleError) -> CivilDate {
        let value = try text(index)
        guard let date = CivilDate(iso: value) else { throw invalid(index, value) }
        return date
    }

    func decimal(_ index: Int32) throws(BundleError) -> Decimal {
        let value = try text(index)
        guard let decimal = DecimalText.parseCanonical(value) else { throw invalid(index, value) }
        return decimal
    }

    func choice<T: RawRepresentable>(_ index: Int32) throws(BundleError) -> T
    where T.RawValue == String {
        let value = try text(index)
        guard let choice = T(rawValue: value) else { throw invalid(index, value) }
        return choice
    }
}
