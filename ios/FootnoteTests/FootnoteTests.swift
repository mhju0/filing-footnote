import Foundation
import SQLite3
import FootnoteKit
import Testing
@testable import Footnote

private final class TestBundle {}

private let fixtureURL = Bundle(for: TestBundle.self).url(forResource: "footnote", withExtension: "sqlite")!

@Suite("App bundle")
struct AppBundleTests {
    /// The copy phase put a data file in the app, and it opens.
    @Test func bundledDataFileOpens() throws {
        guard case .ready(let store, _) = Library.load(
            url: try #require(Bundle.main.url(forResource: "footnote", withExtension: "sqlite")),
            labels: .bundled, requireRelease: false)
        else {
            Issue.record("the bundled data file did not open")
            return
        }
        #expect(!store.companies.isEmpty)
    }

    /// A release build refuses a development bundle and shows the error screen instead.
    @Test func releaseGateRefusesADevelopmentBundle() {
        guard case .failed(let error) = Library.load(url: fixtureURL, labels: .bundled, requireRelease: true)
        else {
            Issue.record("a development bundle passed the release gate")
            return
        }
        #expect(error == .developmentBundle)
    }

    @Test func debugAcceptsADevelopmentBundle() {
        guard case .ready = Library.load(url: fixtureURL, labels: .bundled, requireRelease: false) else {
            Issue.record("a debug build refused the development bundle")
            return
        }
    }

    /// Every fact key in the bundled file has a Korean and an English name from the contract.
    @Test func everyFactHasALabel() throws {
        let labels = FactLabels.bundled
        #expect(!labels.isEmpty)
        for url in [fixtureURL, try #require(Bundle.main.url(forResource: "footnote", withExtension: "sqlite"))] {
            let store = try BundleStore(contentsOf: url)
            for fact in store.facts {
                #expect(labels.label(fact, .ko) != nil, "\(fact.origin)")
                #expect(labels.label(fact, .en) != nil, "\(fact.origin)")
            }
        }
    }

    /// One key, two decisions: the label follows the fact's origin, not its key.
    @Test func labelsFollowTheOrigin() throws {
        let store = try BundleStore(contentsOf: fixtureURL)
        let labels = FactLabels.bundled
        let disposal = try #require(store.facts.first { $0.origin == "opendart:tsstkDpDecsn.dp_dd" })
        let purchase = try #require(store.facts.first { $0.origin == "opendart:tsstkAqDecsn.aq_dd" })
        #expect(disposal.key == purchase.key)
        #expect(labels.label(disposal, .ko) != labels.label(purchase, .ko))
        #expect(labels.label(disposal, .ko) == "처분결정일")
    }
}

@Suite("Copy")
struct CopyTests {
    @Test func noticesRow() {
        #expect(Copy.noticesRow(count: 7, .ko) == "안내 공시 7건")
        #expect(Copy.noticesRow(count: 7, .en) == "7 notices")
        #expect(Copy.noticesRow(count: 1, .en) == "1 notice")
    }

    @Test func endNote() {
        #expect(Copy.endNote(listed: 10, capped: true, .ko) == "최근 1년 공시 가운데 최근 10건이에요.")
        #expect(Copy.endNote(listed: 10, capped: true, .en) == "The 10 newest filings from the last 12 months.")
        #expect(Copy.endNote(listed: 9, capped: false, .ko) == "최근 1년 동안 낸 공시 9건을 모두 보여 줘요.")
        #expect(Copy.endNote(listed: 9, capped: false, .en) == "These are all 9 filings from the last 12 months.")
    }

    @Test func dataDate() throws {
        let date = try #require(CivilDate(iso: "2026-11-18"))
        #expect(Copy.dataDate(date, .ko) == "11월\u{00A0}18일까지 낸\u{00A0}공시")
        #expect(Copy.dataDate(date, .en) == "Filings up to Nov\u{00A0}18")
    }

    @Test func links() {
        #expect(Copy.allFilingsLink(.dart, .ko) == "DART에서 전체 공시 보기")
        #expect(Copy.allFilingsLink(.sec, .en) == "See every filing on SEC")
        #expect(Copy.openOriginal(.dart, .en) == "Open the original on DART")
    }

    @Test func revenueLineAndSpokenForm() throws {
        let store = try BundleStore(contentsOf: fixtureURL)
        let page = try #require(CompanyPage(store: store, companyID: "dart:00126380"))
        let report = try #require(page.periodicReports.first)
        #expect(Copy.revenueLine(report, currency: "KRW", .ko) == "매출 300조 8,709억원 ·\u{00A0}+16.20% 늘었어요")
        #expect(Copy.revenueLine(report, currency: "KRW", .en) == "Revenue ₩300.87 trillion ·\u{00A0}+16.20%, up")
        #expect(Copy.revenueSpoken(report, currency: "KRW", .en)
            == "Revenue for fiscal 2025, ₩300.87 trillion, up 16.20 percent from the year before")
    }

    /// Apple's 52-week years end a day apart: the row notes it; Samsung's calendar years do not.
    @Test func fiscalYearEndsNote() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("weeks-\(UUID().uuidString).sqlite")
        try FileManager.default.copyItem(at: fixtureURL, to: url)
        var db: OpaquePointer?
        #expect(sqlite3_open(url.path, &db) == SQLITE_OK)
        #expect(sqlite3_exec(db, """
            INSERT INTO figures VALUES ('apple-revenue-2024', 'sec:0000320193',
              'sec:0000320193-25-000079', 'revenue', 2024, '2023-10-01', '2024-09-28',
              '391035000000', 'USD', 'USD', 'consolidated', 0,
              'RevenueFromContractWithCustomerExcludingAssessedTax')
            """, nil, nil, nil) == SQLITE_OK)
        sqlite3_close(db)
        let store = try BundleStore(contentsOf: url)
        let apple = try #require(CompanyPage(store: store, companyID: "sec:0000320193")?.periodicReports.first)
        #expect(Copy.fiscalYearEndsNote(apple, .ko) == "회계연도 마감일이 며칠 달라요.")
        #expect(Copy.fiscalYearEndsNote(apple, .en) == "The fiscal years end a few days apart.")
        let samsung = try #require(CompanyPage(store: store, companyID: "dart:00126380")?.periodicReports.first)
        #expect(Copy.fiscalYearEndsNote(samsung, .ko) == nil)

        // A 53-week prior year (2023-09-24 to 2024-09-28) against a 52-week year.
        #expect(sqlite3_open(url.path, &db) == SQLITE_OK)
        #expect(sqlite3_exec(db, "UPDATE figures SET period_start = '2023-09-24' WHERE id = 'apple-revenue-2024'",
                             nil, nil, nil) == SQLITE_OK)
        sqlite3_close(db)
        let longer = try #require(CompanyPage(store: try BundleStore(contentsOf: url), companyID: "sec:0000320193")?
            .periodicReports.first)
        #expect(Copy.fiscalYearEndsNote(longer, .ko) == "한 해가 다른 해보다 한 주 길어요.")
        #expect(Copy.fiscalYearEndsNote(longer, .en) == "One of the years is a week longer.")
    }

    /// No em dash in any copy (antislop R-02).
    @Test func noEmDash() throws {
        let date = try #require(CivilDate(iso: "2026-11-18"))
        for language in Language.allCases {
            let strings = [
                Copy.dataDate(date, language), Copy.noticesRow(count: 3, language),
                Copy.noticesIntro(count: 3, since: date, dataAsOf: date, language),
                Copy.endNote(listed: 9, capped: false, language), Copy.endNote(listed: 10, capped: true, language),
                Copy.allFilingsLink(.dart, language), Copy.openOriginal(.sec, language),
                Copy.filedOn(date, language), Copy.market(.dart, language),
            ]
            for string in strings { #expect(!string.contains("\u{2014}"), "\(string)") }
        }
    }

    /// The page copy has no em dash either, and every refusal has a title.
    @Test func pageCopyHasNoEmDash() {
        for language in Language.allCases {
            var strings = [
                PageCopy.inReviewBody(language), PageCopy.corrected(language), PageCopy.outlookBanner(language),
                PageCopy.outlookWithoutFigures(language), PageCopy.howWritten(language),
                PageCopy.restatedNote(language), PageCopy.baseNotPositive(language), PageCopy.noFigure(language),
                PageCopy.growthFormula(language), PageCopy.marginFormula(language),
            ]
            for reason in RefusalReason.allCases {
                for detail in [RefusalDetail.periodEndMismatch, .nonpositiveBaseline] {
                    let refusal = Refusal(reason, detail)
                    strings.append(PageCopy.refusal(refusal, language))
                    if let body = PageCopy.refusalBody(refusal, language) { strings.append(body) }
                }
            }
            for string in strings {
                #expect(!string.isEmpty)
                #expect(!string.contains("\u{2014}"), "\(string)")
            }
        }
    }

    @Test func refusalCopy() {
        #expect(PageCopy.refusal(Refusal(.incompatibleComparison, .periodEndMismatch), .ko) == "두 숫자의 조건이 달라요")
        #expect(PageCopy.refusal(Refusal(.incompatibleComparison, .nonpositiveBaseline), .en)
            == "Last year was zero or below, so there is no growth rate")
        #expect(PageCopy.refusalBody(Refusal(.incompatibleComparison, .nonpositiveBaseline), .en) == nil)
    }
}

@Suite("Filing page")
struct FilingPageTests {
    /// A copy of the fixture after one SQL edit (the fixture's summaries are test data).
    static func edited(_ sql: String) throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("edited-\(UUID().uuidString).sqlite")
        try FileManager.default.copyItem(at: fixtureURL, to: url)
        var db: OpaquePointer?
        #expect(sqlite3_open(url.path, &db) == SQLITE_OK)
        defer { sqlite3_close(db) }
        let result = sqlite3_exec(db, sql, nil, nil, nil)
        #expect(result == SQLITE_OK, "\(String(cString: sqlite3_errmsg(db)))")
        return url
    }

    /// Roadmap I7: in a release-flag build, every sentence a page renders is an approved
    /// row, and a bundle holding any other review state does not open at all. A staged row
    /// cannot sit beside an approved one in a bundle that opens (BundleStore refuses it, the
    /// second half), so the first half seeds a filing approved in Korean only: Korean shows
    /// that line, English shows none.
    @Test func releaseBuildRendersApprovedSummariesOnly() throws {
        let seeded = "dart:20261029000539"
        let release = try Self.edited("""
            UPDATE build_meta SET allow_unapproved = 0;
            INSERT INTO filing_summaries VALUES
              ('\(seeded)', 'ko', 'summary', '회사는 자기주식을 사기로 했다고 밝혔어요.', NULL, NULL, 'approved', 'x');
            """)
        guard case .ready(let store, _) = Library.load(url: release, labels: .bundled, requireRelease: true) else {
            Issue.record("a release bundle did not open")
            return
        }
        let page = try #require(FilingPage(store: store, filingID: seeded))
        #expect(page.summaryLines(.ko) == ["회사는 자기주식을 사기로 했다고 밝혔어요."])
        #expect(page.summaryLines(.en).isEmpty)
        var rendered = 0
        for filing in store.filings {
            for language in Language.allCases {
                let lines: [String]
                if let annual = AnnualPage(store: store, filingID: filing.id) {
                    lines = ([.oneLine] + AnnualPage.sections).flatMap { annual.lines($0, language) }
                } else {
                    lines = FilingPage(store: store, filingID: filing.id)?.summaryLines(language) ?? []
                }
                let approved = store.summaries
                    .filter { $0.filingID == filing.id && $0.language == language }
                    .flatMap(\.lines)
                for line in lines { #expect(approved.contains(line)) }
                rendered += lines.count
            }
        }
        #expect(rendered > 0)

        let staged = try Self.edited("""
            UPDATE build_meta SET allow_unapproved = 0;
            PRAGMA ignore_check_constraints = ON;
            INSERT INTO filing_summaries VALUES
              ('dart:20261029000539', 'ko', 'summary', 'unreviewed line', NULL, NULL, 'staged', 'x');
            """)
        guard case .failed(let error) = Library.load(url: staged, labels: .bundled, requireRelease: true) else {
            Issue.record("a bundle with a staged summary opened")
            return
        }
        #expect(error == .invalidValue(table: "filing_summaries", column: "review_state", value: "staged"))
    }

    /// The launch wiring: a release build always calls `requireRelease`; a debug build only
    /// when asked. `Library.isDebugBuild` is the `#if DEBUG` constant fed into this.
    @Test func releaseBuildAlwaysRequiresARelease() {
        #expect(Library.requiresRelease(isDebugBuild: false, arguments: []))
        #expect(Library.requiresRelease(isDebugBuild: false, arguments: ["-FootnoteBundle", "/tmp/x.sqlite"]))
        #expect(!Library.requiresRelease(isDebugBuild: true, arguments: []))
        #expect(Library.requiresRelease(isDebugBuild: true, arguments: ["-FootnoteRequireRelease"]))
    }

    /// A number the plain names do not cover is named from the fact contract.
    @Test func contractNamesUnnamedFacts() {
        #expect(FactLabels.bundled.label(origin: "opendart:tsstkAqDecsn.aq_wtn_div_ostk_rt", .ko) != nil)
    }

    /// A restated prior-year revenue gets a note naming the year and this report.
    @Test func restatedNote() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("restated-\(UUID().uuidString).sqlite")
        try FileManager.default.copyItem(at: fixtureURL, to: url)
        var db: OpaquePointer?
        #expect(sqlite3_open(url.path, &db) == SQLITE_OK)
        #expect(sqlite3_exec(db, """
            UPDATE figures SET is_restated = 1
            WHERE company_id = 'dart:00126380' AND metric = 'revenue' AND fiscal_year = 2024
            """, nil, nil, nil) == SQLITE_OK)
        sqlite3_close(db)
        let store = try BundleStore(contentsOf: url)
        let report = try #require(CompanyPage(store: store, companyID: "dart:00126380")?.periodicReports.first)
        #expect(Copy.restatedNote(report, .ko) == "2024 회계연도 매출은 이 보고서가 정정한 값이에요.")
        #expect(Copy.restatedNote(report, .en) == "FY2024 revenue is as restated in this report.")
        let plain = try #require(CompanyPage(store: try BundleStore(contentsOf: fixtureURL), companyID: "dart:00126380"))
        #expect(Copy.restatedNote(plain.periodicReports[0], .ko) == nil)
    }

    @Test func endNoteWithNoFilings() {
        #expect(Copy.endNote(listed: 0, capped: false, .ko) == "최근 1년 동안 낸 공시가 없어요.")
        #expect(Copy.endNote(listed: 0, capped: false, .en) == "No filings in the last 12 months.")
    }

    /// The notices intro names the year when the span starts in an earlier year.
    @Test func noticesIntroYear() throws {
        let since = try #require(CivilDate(iso: "2025-11-20"))
        let asOf = try #require(CivilDate(iso: "2026-11-19"))
        #expect(Copy.noticesIntro(count: 9, since: since, dataAsOf: asOf, .ko)
            .hasSuffix("2025년\u{00A0}11월\u{00A0}20일부터 낸 9건이에요."))
        #expect(Copy.noticesIntro(count: 9, since: since, dataAsOf: asOf, .en)
            .hasSuffix("9\u{00A0}since\u{00A0}Nov\u{00A0}20,\u{00A0}2025."))
    }
}

@Suite("Korean word wrapping")
struct KeepAllTests {
    @Test func joinsInsideHangulWordsOnly() {
        let joiner = "\u{2060}"
        #expect("11월 19일까지".keepingWords == "1\(joiner)1\(joiner)월 1\(joiner)9\(joiner)일\(joiner)까\(joiner)지")
        #expect("Revenue up 6.29%".keepingWords == "Revenue up 6.29%")
        #expect("2,545억원".keepingWords.replacingOccurrences(of: joiner, with: "") == "2,545억원")
    }
}

@Suite("Launch route")
struct LaunchRouteTests {
    @Test func filingRouteOpensCompanyThenFiling() throws {
        let route = try #require(LaunchRoute(argument: "filing=dart:00164742|dart:20261029000247"))
        #expect(route.companiesPath == [.company("dart:00164742"), .filing("dart:20261029000247")])
        #expect(route.sidebarItem == .company("dart:00164742"))
        #expect(route.filingID == "dart:20261029000247")
    }

    @Test func unknownKindIsIgnored() {
        #expect(LaunchRoute(argument: "settings") == nil)
    }
}
