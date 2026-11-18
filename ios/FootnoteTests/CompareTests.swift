import Foundation
import FootnoteKit
import Testing
@testable import Footnote

private final class CompareBundle {}

private let fixture = Bundle(for: CompareBundle.self).url(forResource: "footnote", withExtension: "sqlite")!
private let samsung = "dart:00126380"
private let apple = "sec:0000320193"

@Suite("Compare launch routes")
struct CompareLaunchRouteTests {
    @Test func figureAndCompareRoutesStackOverTheCompany() throws {
        let year = try #require(LaunchRoute(argument: "yearcalc=\(samsung)|revenue|2025"))
        #expect(year.companiesPath == [
            .company(samsung), .figure(samsung, "revenue", 2025),
            .yearCompare(samsung, "revenue", 2025), .yearCalculation(samsung, "revenue", 2025),
        ])
        #expect(year.detailPath.count == 3)
        let compare = try #require(LaunchRoute(argument: "compare=\(samsung)|\(apple)|ebitda|none|2025"))
        // No figure screen for a metric the app does not cover; no measure chosen.
        #expect(compare.detailPath == [.companyCompare(CompanyCompareRoute(
            companyID: samsung, peerID: apple, metric: "ebitda", measure: nil, fiscalYear: 2025))])
        let picker = try #require(LaunchRoute(argument: "picker=\(samsung)|revenue|2025"))
        #expect(picker.opensPicker(samsung))
        #expect(!picker.opensPicker(apple))
        #expect(picker.figureFilingID(try BundleStore(contentsOf: fixture)) == "dart:20260310000123")
    }
}

@Suite("Compare copy")
struct CompareCopyTests {
    private let store = try! BundleStore(contentsOf: fixture)

    /// An explanation for each of the six reasons, through the screens' models.
    private func explanations() throws -> [RefusalExplanation] {
        let pages = [
            CompanyComparePage(store: store, companyID: samsung, peerID: apple,
                               metric: "revenue", measure: nil, fiscalYear: 2025),
            CompanyComparePage(store: store, companyID: samsung, peerID: apple,
                               metric: "operating_margin", measure: "growth_rate", fiscalYear: 2025),
            CompanyComparePage(store: store, companyID: samsung, peerID: apple,
                               metric: "revenue", measure: "growth_rate", fiscalYear: 2025),
            CompanyComparePage(store: store, companyID: samsung, peerID: apple,
                               metric: "revenue", measure: "absolute_amount", fiscalYear: 2025),
        ].compactMap { $0?.explanation }
        let separate = try BundleStore(contentsOf: FilingPageTests.edited(
            "UPDATE figures SET basis = 'separate' WHERE company_id = '\(samsung)'"))
        let negative = try BundleStore(contentsOf: FilingPageTests.edited(
            "UPDATE figures SET value = '-2131' WHERE company_id = '\(samsung)' AND metric = 'eps' AND fiscal_year = 2024"))
        let years = [
            YearComparePage(store: separate, companyID: samsung, metric: "revenue", fiscalYear: 2025),
            YearComparePage(store: negative, companyID: samsung, metric: "eps", fiscalYear: 2025),
            YearComparePage(store: store, companyID: apple, metric: "revenue", fiscalYear: 2025),
            YearComparePage(store: store, companyID: samsung, metric: nil, fiscalYear: 2025),
        ].compactMap { $0?.explanation }
        return pages + years
    }

    @Test func everyReasonHasItsCopyAndNoRanking() throws {
        let all = try explanations()
        #expect(Set(all.map(\.refusal.reason)) == Set(RefusalReason.allCases))
        let ranking = ["better", "worse", "outperform", "underperform", "beat", "lag", "나아", "나빠", "앞서", "뒤처"]
        for explanation in all {
            #expect(!explanation.actions.isEmpty)
            for language in Language.allCases {
                var strings = [
                    PageCopy.refusal(explanation.refusal, language), PageCopy.refusalReason(explanation, language),
                    PageCopy.refusalCode(explanation.refusal.reason, language),
                ]
                strings += explanation.actions.map {
                    PageCopy.actionLabel(
                        $0, reason: explanation.refusal.reason, detail: explanation.refusal.detail,
                        metric: explanation.metric, language)
                }
                if let body = PageCopy.refusalBody(explanation.refusal, language) { strings.append(body) }
                for string in strings {
                    #expect(!string.isEmpty)
                    #expect(!string.contains("\u{2014}"), "\(string)")
                    #expect(!ranking.contains { string.lowercased().contains($0) }, "\(string)")
                }
            }
        }
    }

    @Test func reasonSentencesNameCompaniesYearsAndCurrencies() throws {
        let all = try explanations()
        let currency = try #require(all.first { $0.refusal.reason == .incompatibleCurrency })
        #expect(PageCopy.refusalReason(currency, .ko) == "삼성전자는 원, 애플은 달러로 보고해요.")
        #expect(PageCopy.refusalReason(currency, .en) == "Samsung Electronics reports in won and Apple in dollars.")
        let missing = try #require(all.first { $0.refusal.reason == .missingPeriod && $0.context != .lastYear })
        #expect(PageCopy.refusalReason(missing, .ko) == "애플의 2024 회계연도 매출 숫자가 공시에 없어요.")
        #expect(PageCopy.refusalReason(missing, .en) == "The filings on file have no FY2024 revenue for Apple.")
        let baseline = try #require(all.first { $0.refusal.detail == .nonpositiveBaseline })
        #expect(PageCopy.refusalReason(baseline, .ko) == "삼성전자의 2024 회계연도 주당순이익은 \u{2212}2,131원이에요.")
        #expect(PageCopy.refusalBody(baseline.refusal, .ko) == nil)
        #expect(baseline.actions.map {
            PageCopy.actionLabel($0, reason: baseline.refusal.reason, detail: baseline.refusal.detail,
                                 metric: baseline.metric, .ko)
        } == ["연도별 숫자 보기"])
        let ambiguous = try #require(all.first { $0.refusal.detail == .measureNotSpecified })
        #expect(PageCopy.refusalReason(ambiguous, .ko) == "삼성전자와 애플의 무엇을 비교할지 정해지지\u{00A0}않았어요.")
    }

    @Test func koreanParticlesFollowTheSpokenEnd() {
        #expect(Korean.topic("삼성전자") == "삼성전자는")
        #expect(Korean.topic("애플") == "애플은")
        #expect(Korean.topic("삼성SDI") == "삼성SDI는")
        #expect(Korean.topic("NAVER") == "NAVER는")
        #expect(Korean.and("애플") == "애플과 ")
        #expect(Korean.copula("\u{2212}7.49 달러") == "\u{2212}7.49 달러예요")
        #expect(Korean.copula("\u{2212}2,131원") == "\u{2212}2,131원이에요")
    }

    @Test func caveatAndDifference() throws {
        let page = try #require(CompanyComparePage(
            store: store, companyID: samsung, peerID: apple, metric: "revenue",
            measure: "operating_margin", fiscalYear: 2025))
        #expect(PageCopy.caveat(page.caveat, .ko)
            == "두 회사는 회계 기준(K-IFRS, US GAAP)과 결산월(12월, 9월)이 달라요. 같은 이름의 숫자라도 계산 범위가 조금 다를 수 있어요.")
        #expect(PageCopy.caveat(page.caveat, .en) == "The two companies use different accounting standards "
            + "(K-IFRS, US GAAP) and year-ends (December, September). Figures with the same name can cover slightly different items.")
        let difference = try #require(page.difference)
        #expect(PageCopy.rateDifference(difference, .ko) == "21.09%p")
        #expect(CalculationView.differenceText(difference, page.calculations) == "|10.88 \u{2212} 31.97| = 21.09%p")
        for language in Language.allCases {
            #expect(!PageCopy.caveat(page.caveat, language).contains("\u{2014}"))
        }
    }

    @Test func calculationCopy() throws {
        let page = try #require(YearComparePage(store: store, companyID: samsung, metric: "revenue", fiscalYear: 2025))
        let calculation = try #require(page.calculation)
        #expect(PageCopy.growthEquation(calculation.result)
            == "(300,870,903,000,000 \u{2212} 258,935,494,000,000) ÷ 258,935,494,000,000 × 100")
        #expect(PageCopy.signedPercent(calculation.result.percentChange) == "+16.20%")
        #expect(PageCopy.exact(calculation.current, .ko) == "300조 8,709억 300만원")
        #expect(PageCopy.exact(calculation.current, .en) == "₩300,870,903,000,000")
        #expect(PageCopy.periodLengths(366, 365, .ko) == "12개월씩")
        #expect(PageCopy.periodLengths(364, 371, .en) == "52 and 53 weeks")
        #expect(PageCopy.unitAndRounding("KRW", .en) == "Unit: KRW" + Copy.dot + "rounded half up to two decimals")
        #expect(PageCopy.bothFrom(try #require(calculation.currentSource), .en).hasPrefix("Both figures come from the annual report"))
        let strings = calculation.checks.flatMap { [PageCopy.checkLabel($0, .ko), PageCopy.checkValue($0, .en)] }
        for string in strings { #expect(!string.isEmpty && !string.contains("\u{2014}")) }
    }
}
