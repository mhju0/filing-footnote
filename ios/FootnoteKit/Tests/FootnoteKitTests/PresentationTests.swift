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
}
