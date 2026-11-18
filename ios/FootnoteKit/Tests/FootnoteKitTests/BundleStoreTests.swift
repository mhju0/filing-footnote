import Foundation
import SQLite3
import Testing
@testable import FootnoteKit

/// BundleStore against the committed fixture written by `backend/tests/footnotekit_fixture.py`
/// through the real exporter (development mode).
@Suite("Bundle store")
struct BundleStoreTests {
    static let samsung = "dart:00126380"
    static let apple = "sec:0000320193"
    static let samsungAnnual = "dart:20260310000123"
    static let buyback = "dart:20260821000616"

    let store: BundleStore

    init() throws {
        store = try BundleStore(contentsOf: Support.fixtureURL)
    }

    @Test func buildMeta() {
        #expect(store.meta.schemaVersion == BundleStore.supportedSchemaVersion)
        #expect(store.meta.dataAsOf == Support.date("2026-11-17"))
        #expect(store.meta.sourceRevision == "footnotekit-fixture")
        #expect(store.meta.allowUnapproved)
        #expect(store.meta.contentSHA256.count == 64)
    }

    @Test func everyTableHasRows() {
        #expect(store.companies.count == 2)
        #expect(store.filings.count == 17)
        #expect(store.notices.count == 9)
        #expect(store.summaries.count == 6)
        #expect(store.facts.count == 25)
        #expect(store.figures.count == 17)
        #expect(store.glossary.count == 4)
    }

    @Test func companiesByMarket() throws {
        #expect(store.companies.map(\.id) == [Self.samsung, Self.apple])
        let samsung = try #require(store.company(id: Self.samsung))
        #expect(samsung.regulator == .dart)
        #expect(samsung.name(.ko) == "삼성전자")
        #expect(samsung.currency == "KRW")
        let groups = store.companiesByMarket()
        #expect(groups.map(\.market) == ["KOSPI", nil])
        #expect(groups.map { $0.companies.map(\.id) } == [[Self.samsung], [Self.apple]])
        #expect(store.companies(inMarket: "KOSPI").map(\.id) == [Self.samsung])
    }

    @Test func filingsNewestFirstThenIDDescending() {
        let filings = store.filings(forCompany: Self.samsung)
        #expect(filings.count == 11)
        #expect(Array(filings.prefix(3)).map(\.id)
            == ["dart:20261029800752", "dart:20261029800748", "dart:20261029800102"])
        for (earlier, later) in zip(filings, filings.dropFirst()) {
            #expect(earlier.filedOn > later.filedOn
                || (earlier.filedOn == later.filedOn && earlier.id > later.id))
        }
        #expect(store.annualFilings(forCompany: Self.samsung).map(\.id) == [Self.samsungAnnual])
        #expect(store.eventFilings(forCompany: Self.samsung).count == 10)
        #expect(store.eventFilings(forCompany: Self.apple).count == 5)
        let annual = store.filing(id: Self.samsungAnnual)
        #expect(annual?.category == .annual)
        #expect(annual?.periodLabel == "FY2025")
        let corrected = store.filing(id: "sec:0001140361-26-035325")
        #expect(corrected?.isCorrected == true)
        #expect(corrected?.secItems == "5.02")
        #expect(corrected?.category == .leadership)
    }

    @Test func notices() {
        let notices = store.notices(forCompany: Self.samsung)
        #expect(notices.count == 9)
        #expect(notices.first?.id == "dart:20261113801115")
        #expect(notices.first?.category == .irEvent)
        #expect(notices.filter(\.isCorrected).count == 2)
        #expect(store.notices(forCompany: Self.apple).isEmpty)
    }

    @Test func summariesByLanguageAndSection() throws {
        let annual = store.summaries(forFiling: Self.samsungAnnual, language: .ko)
        #expect(annual.map(\.section) == [.oneLine, .business])
        #expect(annual.allSatisfy { $0.lines.count == 1 })
        let event = try #require(store.summary(forFiling: Self.buyback, language: .en, section: .summary))
        #expect(event.lines.count == 3)
        #expect(event.lines[0] == "The company said it filed this report.")
        #expect(store.summary(forFiling: Self.buyback, language: .ko, section: .risks) == nil)
    }

    @Test func factsInPositionOrderWithExactValues() {
        let facts = store.facts(forFiling: Self.buyback)
        #expect(facts.map(\.position) == Array(1...8))
        #expect(facts[0].value == .shares(Support.decimal("53285968")))
        #expect(facts[1].key == "acquire_amount_common")
        #expect(facts[1].value == .amount(Support.decimal("14999999992000")))
        #expect(facts[1].unit == "KRW")
        #expect(facts[2].value == .date(Support.date("2026-08-24")))
        #expect(facts[4].value == .text("임직원 주식보상"))
        #expect(facts[6].value == .ratio(Support.decimal("1.4")))
        #expect(facts[6].value.decimal.map(DecimalText.canonical) == "1.4")
    }

    @Test func figuresWithYears() throws {
        let revenue = store.figures(forCompany: Self.samsung, metric: .revenue)
        #expect(store.figureYears(forCompany: Self.samsung, metric: .revenue) == [2025, 2024])
        #expect(revenue.map { DecimalText.canonical($0.value) }
            == ["300870903000000", "258935494000000"])
        #expect(revenue[0].periodStart == Support.date("2025-01-01"))
        #expect(revenue[0].basis == "consolidated")
        #expect(revenue[0].filingID == Self.samsungAnnual)
        let eps = try #require(store.figures(forCompany: Self.apple, metric: .eps).first)
        #expect(DecimalText.canonical(eps.value) == "7.49")
        #expect(eps.unit == "USD_PER_SHARE")
        #expect(store.figureYears(forCompany: Self.apple, metric: .revenue) == [2025])
    }

    @Test func figuresFeedTheCalculator() throws {
        let revenue = store.figures(forCompany: Self.samsung, metric: .revenue).map(\.fact)
        guard case .result(let change) = Calculator.yearOverYear(metric: "revenue", facts: revenue)
        else { Issue.record("refused"); return }
        #expect(DecimalText.twoPlaces(change.percentChange) == "16.20")
        #expect(DecimalText.canonical(change.delta) == "41935409000000")

        let margin = [ReportedMetric.revenue, .operatingIncome].compactMap {
            store.figures(forCompany: Self.apple, metric: $0).first?.fact
        }
        guard case .result(let result) = Calculator.operatingMargin(metric: "operating_margin", facts: margin)
        else { Issue.record("refused"); return }
        #expect(DecimalText.twoPlaces(result.operatingMargin) == "31.97")

        // Apple has one year: a year-over-year comparison refuses with missing_period.
        let one = store.figures(forCompany: Self.apple, metric: .revenue).map(\.fact)
        #expect(Calculator.yearOverYear(metric: "revenue", facts: one)
            == .refusal(Refusal(.missingPeriod, .missingFact)))
    }

    @Test func glossary() throws {
        #expect(store.glossary(language: .ko).map(\.termKey) == ["operating_margin", "revenue"])
        let entry = try #require(store.glossaryEntry(termKey: "operating_margin", language: .en))
        #expect(entry.term == "Operating margin")
        #expect(entry.formal != nil)
    }

    // MARK: - Refusing a file

    @Test func openingLeavesTheFileUnchanged() throws {
        let before = try Data(contentsOf: Support.fixtureURL)
        _ = try BundleStore(contentsOf: Support.fixtureURL)
        #expect(try Data(contentsOf: Support.fixtureURL) == before)
    }

    @Test func rejectsAnUnknownSchemaVersion() throws {
        let url = try Self.editedCopy("UPDATE build_meta SET schema_version = 3")
        #expect(throws: BundleError.unsupportedSchemaVersion(found: 3, supported: 2)) {
            try BundleStore(contentsOf: url)
        }
    }

    @Test func rejectsAFutureSchemaBeforeReadingItsColumns() throws {
        let url = try Self.editedCopy(
            "UPDATE build_meta SET schema_version = 9; ALTER TABLE build_meta DROP COLUMN llm_model")
        #expect(throws: BundleError.unsupportedSchemaVersion(found: 9, supported: 2)) {
            try BundleStore(contentsOf: url)
        }
    }

    @Test func rejectsAMissingBuildMetaRow() throws {
        let url = try Self.editedCopy("DELETE FROM build_meta")
        #expect(throws: BundleError.missingBuildMeta(rows: 0)) {
            try BundleStore(contentsOf: url)
        }
    }

    @Test func rejectsANonCanonicalDecimal() throws {
        let url = try Self.editedCopy(
            "UPDATE figures SET value = '7.490' WHERE metric = 'eps' AND company_id = '\(Self.apple)'")
        #expect(throws: BundleError.invalidValue(table: "figures", column: "value", value: "7.490")) {
            try BundleStore(contentsOf: url)
        }
    }

    @Test func rejectsAnUnknownCategory() throws {
        let url = try Self.editedCopy(
            "UPDATE filings SET category = 'rumour' WHERE id = '\(Self.buyback)'")
        #expect(throws: BundleError.invalidValue(table: "filings", column: "category", value: "rumour")) {
            try BundleStore(contentsOf: url)
        }
    }

    @Test func rejectsAMissingFile() {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("absent-\(UUID()).sqlite")
        #expect(throws: BundleError.self) { try BundleStore(contentsOf: url) }
    }

    /// A temporary copy of the fixture with one statement applied.
    static func editedCopy(_ sql: String) throws -> URL {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("footnotekit-\(UUID())")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let url = directory.appendingPathComponent("footnote.sqlite")
        try FileManager.default.copyItem(at: Support.fixtureURL, to: url)
        var handle: OpaquePointer?
        try #require(sqlite3_open(url.path, &handle) == SQLITE_OK)
        defer { sqlite3_close(handle) }
        try #require(sqlite3_exec(handle, sql, nil, nil, nil) == SQLITE_OK)
        return url
    }
}
