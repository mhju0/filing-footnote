import Foundation
import Testing
@testable import FootnoteKit

@Suite("Display titles")
struct TitlesTests {
    let store: BundleStore

    init() throws { store = try BundleStore(contentsOf: Support.fixtureURL) }

    func title(_ id: String, _ language: Language) -> String {
        Titles.title(for: store.filing(id: id)!, language: language)
    }

    @Test func dartNamesLoseFilingMarkers() {
        #expect(Titles.parseDart("주요사항보고서(자기주식처분결정)") == .init(base: "자기주식처분결정"))
        #expect(Titles.parseDart("[기재정정]장래사업ㆍ경영계획(공정공시)") == .init(base: "장래사업ㆍ경영계획"))
        #expect(Titles.parseDart("기업가치제고계획(자율공시) (2025년 재공시)")
            == .init(base: "기업가치제고계획", detail: "2025년 재공시"))
        #expect(Titles.parseDart("중대재해발생(종속회사의주요경영사항)")
            == .init(base: "중대재해발생", subsidiary: true))
        #expect(Titles.parseDart("풍문또는보도에대한해명(미확정)") == .init(base: "풍문또는보도에대한해명(미확정)"))
    }

    @Test func dartEvents() {
        #expect(title("dart:20261029000539", .ko) == "자사주 처분 결정")
        #expect(title("dart:20261029000539", .en) == "Treasury share disposal")
        #expect(title("dart:20261029800099", .ko) == "잠정 실적 (연결)")
        #expect(title("dart:20261029800101", .en) == "Dividend decision")
        #expect(title("dart:20261029800102", .ko) == "사업·경영 계획")
    }

    @Test func everyFixtureDartTitleIsKnown() {
        for filing in store.filings where filing.kind == .event && filing.id.hasPrefix("dart:") {
            #expect(Titles.dartNames[Titles.parseDart(filing.titleOriginal).base] != nil,
                    "\(filing.titleOriginal)")
        }
    }

    @Test func secEventsUseTheItemThatMatchesTheCategory() {
        #expect(title("sec:0000320193-26-000024", .en) == "Results of operations (8-K)")
        #expect(title("sec:0000320193-26-000024", .ko) == "실적 발표 (8-K)")
        #expect(title("sec:0001140361-26-006577", .en) == "Shareholder vote results (8-K)")
        #expect(title("sec:0001140361-26-035325", .en) == "Officer or director change (8-K/A)")
    }

    @Test func annualReports() {
        #expect(title("dart:20260310000123", .ko) == "2025년 사업보고서")
        #expect(title("dart:20260310000123", .en) == "Annual report, FY2025")
        #expect(title("sec:0000320193-25-000079", .ko) == "2025 회계연도 연차보고서 (10-K)")
        #expect(title("sec:0000320193-25-000079", .en) == "Annual report, FY2025 (10-K)")
    }

    @Test func noticesAndNames() throws {
        let notice = try #require(store.notices.first { $0.category == .irEvent })
        #expect(Titles.title(for: notice, language: .ko) == "IR 행사 안내")
        let samsung = try #require(store.company(id: BundleStoreTests.samsung))
        #expect(Titles.name(of: samsung, language: .en) == "Samsung Electronics")
        #expect(Titles.name(of: samsung, language: .ko) == "삼성전자")
    }

    @Test func titlesHaveNoEmDash() {
        for filing in store.filings {
            for language in Language.allCases {
                #expect(!Titles.title(for: filing, language: language).contains("\u{2014}"))
            }
        }
    }
}

@Suite("Company page")
struct CompanyPageTests {
    let store: BundleStore

    init() throws { store = try BundleStore(contentsOf: Support.fixtureURL) }

    @Test func samsungPage() throws {
        let page = try #require(CompanyPage(store: store, companyID: BundleStoreTests.samsung))
        #expect(page.periodicReports.map(\.filing.id) == ["dart:20260310000123"])
        let report = page.periodicReports[0]
        #expect(report.revenue?.fiscalYear == 2025)
        #expect(report.change?.percentChange == Support.decimal("16.2"))
        #expect(page.filings.count == 10)
        #expect(page.isCapped)
        #expect(page.months.map(\.id) == ["2026-10", "2026-8"])
        #expect(page.filings == Array(store.eventFilings(forCompany: BundleStoreTests.samsung).prefix(10)))
        // Notices from the oldest listed filing (Aug 21) to the data date.
        #expect(page.noticesSince == Support.date("2026-08-21"))
        #expect(page.notices.map(\.filedOn) == [Support.date("2026-11-13"), Support.date("2026-10-08")])
        #expect(page.noticeCounts.map(\.count) == [2])
    }

    @Test func appleHasOneYearSoNoChange() throws {
        let page = try #require(CompanyPage(store: store, companyID: BundleStoreTests.apple))
        #expect(page.periodicReports.first?.revenue?.fiscalYear == 2025)
        #expect(page.periodicReports.first?.change == nil)
        #expect(page.filings.count == 5)
        #expect(!page.isCapped)
        #expect(page.months.first?.year == 2026)
        #expect(page.months.last?.year == 2025)
        #expect(page.notices.isEmpty)
        // Not capped: notices count from the first day of the 12-month window.
        #expect(page.noticesSince == Support.date("2025-11-18"))
        let start = CompanyPage.windowStart(endingOn: store.meta.dataAsOf)
        #expect(page.filings.allSatisfy { $0.filedOn >= start && $0.filedOn <= store.meta.dataAsOf })
    }

    /// Apple's 52-week years end on September 28 and September 27: the change is worked out
    /// and says the ends differ (D82). Samsung's calendar years carry no such flag.
    @Test func fiscalWeekYearsGetAChangeWithAFlag() throws {
        let store = try Support.editedFixture("""
            INSERT INTO figures VALUES ('apple-revenue-2024', '\(BundleStoreTests.apple)',
              'sec:0000320193-25-000079', 'revenue', 2024, '2023-10-01', '2024-09-28',
              '391035000000', 'USD', 'USD', 'consolidated', 0,
              'RevenueFromContractWithCustomerExcludingAssessedTax')
            """)
        let page = try #require(CompanyPage(store: store, companyID: BundleStoreTests.apple))
        let change = try #require(page.periodicReports.first?.change)
        #expect(change.periodEndsDiffer)
        #expect(DecimalText.twoPlaces(change.percentChange) == "6.43")
        let samsung = try #require(CompanyPage(store: store, companyID: BundleStoreTests.samsung))
        #expect(samsung.periodicReports.first?.change?.periodEndsDiffer == false)
    }

    @Test(arguments: [
        ("2026-11-17", "2025-11-18"), ("2028-02-29", "2027-03-01"), ("2026-12-31", "2026-01-01"),
        ("2026-03-01", "2025-03-02"),
    ])
    func windowStart(_ end: String, _ start: String) {
        #expect(CompanyPage.windowStart(endingOn: Support.date(end)) == Support.date(start))
    }

    /// Fewer than ten filings: every notice in the 12-month window, not only those since the
    /// oldest listed filing.
    @Test func uncappedPageCountsNoticesFromTheWindowStart() throws {
        let store = try Support.editedFixture(
            "DELETE FROM filings WHERE company_id = 'dart:00126380' AND kind = 'event' AND filed_on < '2026-10-01'")
        let page = try #require(CompanyPage(store: store, companyID: BundleStoreTests.samsung))
        #expect(!page.isCapped)
        #expect(page.noticesSince == Support.date("2025-11-18"))
        #expect(page.notices.count == 9)
    }

    /// No event filings at all: the notices row still has its notices.
    @Test func noticesWithoutEventFilings() throws {
        let store = try Support.editedFixture(
            "DELETE FROM filings WHERE company_id = 'dart:00126380' AND kind = 'event'")
        let page = try #require(CompanyPage(store: store, companyID: BundleStoreTests.samsung))
        #expect(page.filings.isEmpty)
        #expect(page.notices.count == 9)
    }

    /// Filings outside the 12 months ending on the data date are not listed.
    @Test func filingsOutsideTheWindowAreLeftOut() throws {
        let store = try Support.editedFixture(
            "UPDATE filings SET filed_on = '2025-11-17' WHERE id = 'dart:20261029000539'")
        let page = try #require(CompanyPage(store: store, companyID: BundleStoreTests.samsung))
        #expect(!page.filings.contains { $0.id == "dart:20261029000539" })
    }

    /// The restated tag follows the figure: here the prior year's revenue is restated.
    @Test func restatedPriorYear() throws {
        let store = try Support.editedFixture(
            "UPDATE figures SET is_restated = 1 WHERE company_id = 'dart:00126380' AND metric = 'revenue' AND fiscal_year = 2024")
        let page = try #require(CompanyPage(store: store, companyID: BundleStoreTests.samsung))
        let report = try #require(page.periodicReports.first)
        #expect(report.restated.map(\.fiscalYear) == [2024])
        let plain = try #require(CompanyPage(store: self.store, companyID: BundleStoreTests.samsung))
        #expect(plain.periodicReports.first?.restated.isEmpty == true)
    }

    /// Consolidated first, then the filing's own figure, whatever order the bundle lists them.
    @Test func prefersConsolidatedRevenue() throws {
        let store = try Support.editedFixture("""
            INSERT INTO figures (id, company_id, filing_id, metric, fiscal_year, period_start, period_end,
                value, unit, currency, basis, is_restated, regulator_tag)
            SELECT id || ':entity', company_id, filing_id, metric, fiscal_year, period_start, period_end,
                '1', unit, currency, 'consolidated_entity_total', is_restated, regulator_tag
            FROM figures WHERE company_id = 'dart:00126380' AND metric = 'revenue' AND fiscal_year = 2025
            """)
        let page = try #require(CompanyPage(store: store, companyID: BundleStoreTests.samsung))
        #expect(page.periodicReports.first?.revenue?.basis == "consolidated")
        #expect(page.periodicReports.first?.change?.percentChange == Support.decimal("16.2"))
    }

    @Test func unknownCompany() {
        #expect(CompanyPage(store: store, companyID: "dart:missing") == nil)
    }

    @Test(arguments: [
        ("2026-11-17", true), ("2026-11-11", true), ("2026-11-10", false), ("2026-11-18", false),
    ])
    func newTag(_ filed: String, _ expected: Bool) {
        #expect(Freshness.isNew(Support.date(filed), dataAsOf: Support.date("2026-11-17")) == expected)
    }

    @Test func links() throws {
        let samsung = try #require(store.company(id: BundleStoreTests.samsung))
        let apple = try #require(store.company(id: BundleStoreTests.apple))
        let dart = try #require(Links.allFilings(of: samsung)?.absoluteString)
        #expect(dart.hasPrefix("https://dart.fss.or.kr/dsab007/main.do?"))
        #expect(dart.contains("textCrpCik=00126380"))
        #expect(Links.allFilings(of: apple)?.absoluteString
            == "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000320193")
    }
}

@Suite("Formatting additions")
struct FormattingAdditionTests {
    @Test func fullDates() {
        #expect(Formatting.fullDate(Support.date("2026-11-20"), language: .ko) == "2026년 11월 20일")
        #expect(Formatting.fullDate(Support.date("2026-11-20"), language: .en) == "Nov 20, 2026")
    }

    @Test func months() {
        #expect(Formatting.month(10, year: 2026, currentYear: 2026, language: .ko) == "10월")
        #expect(Formatting.month(12, year: 2025, currentYear: 2026, language: .ko) == "2025년 12월")
        #expect(Formatting.month(10, year: 2026, currentYear: 2026, language: .en) == "October")
        #expect(Formatting.month(12, year: 2025, currentYear: 2026, language: .en) == "December 2025")
    }

    @Test(arguments: [("917385", "917,385"), ("0.125", "0.125"), ("-1234", "\u{2212}1,234"), ("0", "0")])
    func numbers(_ value: String, _ expected: String) {
        #expect(Formatting.number(Support.decimal(value)) == expected)
    }

    /// The spoken change takes its direction from the same rounded value the line shows.
    @Test(arguments: [
        ("0.003", "0.00% 변동 없어요", "전년과 같아요", "no change from the year before"),
        ("-0.004", "0.00% 변동 없어요", "전년과 같아요", "no change from the year before"),
        ("0.005", "+0.01% 늘었어요", "전년보다 0.01퍼센트 늘었어요", "up 0.01 percent from the year before"),
        ("-3.4512", "\u{2212}3.45% 줄었어요", "전년보다 3.45퍼센트 줄었어요", "down 3.45 percent from the year before"),
    ])
    func spokenChange(_ value: String, _ shown: String, _ ko: String, _ en: String) {
        #expect(Formatting.percentChange(Support.decimal(value), language: .ko) == shown)
        #expect(Formatting.percentChangeSpoken(Support.decimal(value), language: .ko) == ko)
        #expect(Formatting.percentChangeSpoken(Support.decimal(value), language: .en) == en)
    }
}

@Suite("Title parity")
struct TitleParityTests {
    @Test func refilingDetailInBothLanguages() {
        #expect(Titles.dartDetail("2025년 재공시", .ko) == "2025년 재공시")
        #expect(Titles.dartDetail("2025년 재공시", .en) == "2025 refiling")
        #expect(Titles.dartDetail("기술수출 계약 개정 체결", .ko) == "기술수출 계약 개정 체결")
        #expect(Titles.dartDetail("기술수출 계약 개정 체결", .en) == nil)
    }

    /// An unknown report name falls back to its category in both languages.
    @Test func unknownNameUsesTheCategory() throws {
        let store = try Support.editedFixture(
            "UPDATE filings SET title_original = '처음보는보고서(자율공시) (2025년 재공시)' WHERE id = 'dart:20261029000539'")
        let filing = try #require(store.filing(id: "dart:20261029000539"))
        let ko = filing.category.label(.ko)
        let en = filing.category.label(.en)
        #expect(Titles.title(for: filing, language: .ko) == "\(ko) 관련 공시 · 2025년 재공시")
        #expect(Titles.title(for: filing, language: .en) == "\(en) filing · 2025 refiling")
    }
}
