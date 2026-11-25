import Foundation
import Testing
@testable import FootnoteKit

@Suite("News feed")
struct NewsFeedTests {
    let store: BundleStore

    init() throws { store = try BundleStore(contentsOf: Support.fixtureURL) }

    /// The feed is exactly the filings the company pages list, newest first, by day.
    @Test func feedIsTheCompanyPagesFilingsByDay() throws {
        let feed = NewsFeed(store: store)
        let listed = try store.companies.flatMap { try #require(CompanyPage(store: store, companyID: $0.id)).filings }
        #expect(Set(feed.filings) == Set(listed))
        #expect(feed.filings.count == 15)
        #expect(!feed.isCapped)
        #expect(feed.days.map(\.id) == [
            "2026-11-02", "2026-10-29", "2026-09-01", "2026-08-21", "2026-02-24", "2026-01-02", "2025-12-05",
        ])
        #expect(feed.days[1].filings.count == 7)
        #expect(feed.days.allSatisfy { day in day.filings.allSatisfy { $0.filedOn == day.date } })
        let dates = feed.filings.map(\.filedOn)
        #expect(dates == dates.sorted(by: >))
        #expect(feed.filings.allSatisfy { $0.kind == .event })
        // The store builds the same feed once, when it is opened.
        #expect(store.newsFeed.filings == feed.filings)
    }

    /// A filing outside the company page's 12-month window is not in the feed either.
    @Test func feedLeavesOutWhatTheCompanyPageLeavesOut() throws {
        let edited = try Support.editedFixture(
            "UPDATE filings SET filed_on = '2025-11-17' WHERE id = 'sec:0001140361-25-044561'")
        let feed = NewsFeed(store: edited)
        #expect(!feed.filings.contains { $0.id == "sec:0001140361-25-044561" })
        #expect(feed.filings.count == 14)
    }

    @Test func feedIsCappedAtThirty() throws {
        // Two more copies of Samsung, ten listed filings each: thirty-five listed in all.
        let sql = ["a", "b"].map { suffix in
            """
            INSERT INTO companies SELECT id || '-\(suffix)', regulator, ticker, name_ko, name_en, market, currency,
              fiscal_year_end, sort_order + 10 FROM companies WHERE id = 'dart:00126380';
            INSERT INTO filings SELECT id || '-\(suffix)', company_id || '-\(suffix)', kind, category, form,
              sec_items, title_original, filed_on, period_label, source_url, is_corrected, source_text_sha256
              FROM filings WHERE company_id = 'dart:00126380' AND kind = 'event';
            """
        }.joined(separator: "\n")
        let feed = NewsFeed(store: try Support.editedFixture(sql))
        #expect(feed.filings.count == NewsFeed.maxFilings)
        #expect(feed.isCapped)
        // The newest thirty: the cut falls inside August 21.
        #expect(feed.filings.last?.filedOn == Support.date("2026-08-21"))
        // A type can match eligible filings beyond the all-filings cap.
        #expect(!feed.filings.contains { $0.category == .meeting })
        #expect(feed.availableCategories.contains(.meeting))
        let leadership = feed.filtered(to: .leadership)
        #expect(leadership.days.map(\.id) == ["2026-09-01", "2026-01-02", "2025-12-05"])
        #expect(leadership.filings.allSatisfy { $0.category == .leadership })
        #expect(!leadership.isCapped)
        #expect(feed.filtered(to: .annual).isEmpty)
    }

    @Test func emptyWhenNoFilingIsInTheWindow() throws {
        let edited = try Support.editedFixture("UPDATE build_meta SET data_as_of = '2030-01-01'")
        let feed = NewsFeed(store: edited)
        #expect(feed.isEmpty)
        #expect(!feed.isCapped)
    }

    /// 새 공시 is the owner's rule: filed on the data date or the six days before it.
    @Test func newTagFollowsTheSevenDayRule() throws {
        let edited = try Support.editedFixture("UPDATE build_meta SET data_as_of = '2026-11-08'")
        let feed = NewsFeed(store: edited)
        let new = feed.filings.filter { Freshness.isNew($0.filedOn, dataAsOf: feed.dataAsOf) }
        #expect(new.map(\.filedOn) == [Support.date("2026-11-02")])
        let later = NewsFeed(store: try Support.editedFixture("UPDATE build_meta SET data_as_of = '2026-11-09'"))
        #expect(later.filings.allSatisfy { !Freshness.isNew($0.filedOn, dataAsOf: later.dataAsOf) })
    }
}

@Suite("Glossary")
struct GlossaryTests {
    @Test func keysMatchTheContract() throws {
        let url = Support.repositoryRoot.appendingPathComponent("contracts/glossary.json")
        let contract = try JSONDecoder().decode([String: JSONValue].self, from: Data(contentsOf: url))
        guard case .object(let entries)? = contract["entries"] else {
            Issue.record("contracts/glossary.json has no entries object")
            return
        }
        let keys = Set(entries.keys)
        #expect(!keys.isEmpty)
        for category in FilingCategory.allCases {
            #expect(keys.contains(Glossary.key(for: category)), "\(category)")
        }
        for metric in ReportedMetric.allCases {
            #expect(keys.contains(Glossary.key(for: metric)), "\(metric)")
        }
    }

    @Test func sortedLikeADictionaryInEachLanguage() throws {
        let store = try Support.editedFixture("""
            INSERT INTO glossary (term_key, lang, term, plain, formal) VALUES
              ('category_dividend', 'ko', '배당', '배당 설명', NULL),
              ('category_dividend', 'en', 'Dividend', 'About dividends.', NULL);
            """)
        #expect(store.sortedGlossary(language: .ko).map(\.term) == ["매출액", "배당", "영업이익률"])
        #expect(store.sortedGlossary(language: .en).map(\.term) == ["Dividend", "Operating margin", "Revenue"])
        #expect(store.sortedGlossary(language: .ko).count == store.glossary(language: .ko).count)
    }

    @Test func searchMatchesTheTermAndFormalNameAcrossLanguages() throws {
        let store = try Support.editedFixture("""
            INSERT INTO glossary (term_key, lang, term, plain, formal) VALUES
              ('metric_eps', 'ko', '주당순이익', '주당순이익 설명', NULL),
              ('metric_eps', 'en', 'EPS', 'About EPS.', 'Earnings per share');
            """)
        #expect(store.sortedGlossary(language: .ko, matching: "  ｅｐｓ  ").map(\.term) == ["주당순이익"])
        #expect(store.sortedGlossary(language: .ko, matching: "earnings per share").map(\.term) == ["주당순이익"])
        #expect(store.sortedGlossary(language: .en, matching: "수익(매출액)").map(\.term) == ["Revenue"])
        #expect(store.sortedGlossary(language: .en, matching: "not a term").isEmpty)
        #expect(store.sortedGlossary(language: .en, matching: " \n ") == store.sortedGlossary(language: .en))
    }
}

/// 2026-11-26 review, issue 2: 새 공시 marks event filings only, and Companies shows each
/// company's newest filing date and type instead of the tag.
@Suite("Latest filing")
struct LatestFilingTests {
    @Test func newTagSkipsPeriodicReports() throws {
        let store = try Support.editedFixture("UPDATE build_meta SET data_as_of = '2026-11-17'")
        let quarterly = try #require(store.filing(id: "dart:20261116000111"))
        #expect(Freshness.isNew(quarterly.filedOn, dataAsOf: store.meta.dataAsOf))
        #expect(!Freshness.isNew(quarterly, dataAsOf: store.meta.dataAsOf))
        let annual = try #require(store.filing(id: "dart:20260310000123"))
        #expect(!Freshness.isNew(annual, dataAsOf: Support.date("2026-03-10")))
        let earnings = try #require(store.filing(id: "sec:0000320193-26-000024"))
        #expect(Freshness.isNew(earnings, dataAsOf: Support.date("2026-11-08")))
        #expect(!Freshness.isNew(earnings, dataAsOf: Support.date("2026-11-09")))
    }

    @Test func newestFilingOrNotice() throws {
        let store = try Support.editedFixture("SELECT 1")
        let samsung = try #require(store.latestFiling(companyID: "dart:00126380"))
        #expect(samsung.filedOn == Support.date("2026-11-16"))
        #expect(samsung.kind == .filing(.quarterly, halfYear: false))
        #expect(samsung.label(.ko) == "분기 보고서")
        #expect(samsung.label(.en) == "Quarterly report")
        let apple = try #require(store.latestFiling(companyID: "sec:0000320193"))
        #expect(apple.filedOn == Support.date("2026-11-02"))
        #expect(apple.kind == .filing(.earnings, halfYear: false))
        #expect(store.latestFiling(companyID: "dart:missing") == nil)
    }

    @Test func aFilingWinsOverANoticeOnTheSameDay() throws {
        let sameDay = try Support.editedFixture(
            "UPDATE notices SET filed_on = '2026-11-16' WHERE id = 'dart:20261113801115'")
        #expect(sameDay.latestFiling(companyID: "dart:00126380")?.kind == .filing(.quarterly, halfYear: false))
        let later = try Support.editedFixture(
            "UPDATE notices SET filed_on = '2026-11-17' WHERE id = 'dart:20261113801115'")
        let notice = try #require(later.latestFiling(companyID: "dart:00126380"))
        #expect(notice.kind == .notice(.irEvent))
        #expect(notice.filedOn == Support.date("2026-11-17"))
    }

    @Test func aHalfYearReportIsNamedAsOne() throws {
        let store = try Support.editedFixture(
            "UPDATE filings SET form = '반기보고서' WHERE id = 'dart:20261116000111'")
        let latest = try #require(store.latestFiling(companyID: "dart:00126380"))
        #expect(latest.label(.ko) == "반기보고서")
        #expect(latest.label(.en) == "Half-year report")
    }
}

/// 2026-11-26 review, issue 12: key terms first, then the dictionary, then the refusal reasons.
@Suite("Glossary groups")
struct GlossaryGroupTests {
    private static let rows = """
        INSERT INTO glossary (term_key, lang, term, plain, formal) VALUES
          ('metric_revenue', 'ko', '매출액', '매출 설명', NULL),
          ('metric_revenue', 'en', 'Revenue', 'About revenue.', NULL),
          ('metric_eps', 'ko', '주당순이익(EPS)', '주당순이익 설명', NULL),
          ('metric_eps', 'en', 'EPS', 'About EPS.', NULL),
          ('category_dividend', 'ko', '배당', '배당 설명', NULL),
          ('category_dividend', 'en', 'Dividend', 'About dividends.', NULL),
          ('basis_consolidated', 'ko', '연결 기준', '연결 설명', NULL),
          ('basis_consolidated', 'en', 'Consolidated', 'About consolidated.', NULL),
          ('refusal_missing_period', 'ko', '빠진 기간', '빠진 기간 설명', NULL),
          ('refusal_missing_period', 'en', 'Period missing', 'About a missing period.', NULL);
        """

    @Test func keyTermsFirstRefusalsLast() throws {
        let store = try Support.editedFixture(Self.rows)
        let sections = store.glossarySections(language: .ko)
        #expect(sections.map(\.kind) == [.keyTerms, .initial("ㅁ"), .initial("ㅂ"), .initial("ㅇ"), .refusals])
        #expect(sections[0].entries.map(\.termKey) == ["metric_revenue", "metric_eps"])
        #expect(sections.last?.entries.map(\.termKey) == ["refusal_missing_period"])
        let keys = sections.flatMap(\.entries).map(\.termKey)
        #expect(keys.count == Set(keys).count)
        #expect(keys.count == store.glossary(language: .ko).count)
    }

    @Test func searchKeepsTheGroupsThatMatch() throws {
        let store = try Support.editedFixture(Self.rows)
        #expect(store.glossarySections(language: .en, matching: "eps").map(\.kind) == [.keyTerms])
        #expect(store.glossarySections(language: .en, matching: "period").map(\.kind) == [.refusals])
        #expect(store.glossarySections(language: .en, matching: "not a term").isEmpty)
    }
}
