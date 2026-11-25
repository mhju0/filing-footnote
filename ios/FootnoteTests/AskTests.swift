import FootnoteKit
import Testing
@testable import Footnote

@Suite("Ask about this company")
struct AskTests {
    @Test(arguments: QuestionIntent.allCases)
    func selectionRoundTrips(_ intent: QuestionIntent) {
        #expect(AskSelection.intent(AskSelection.id(intent)) == intent)
    }

    /// Filing ids never read as a question, so the detail column shows the filing.
    @Test(arguments: [nil, "", "dart:20261116000111", "sec:0000320193-26-000020", "ask:", "ask:forecast"])
    func otherSelectionsAreNoQuestion(_ id: String?) {
        #expect(AskSelection.intent(id) == nil)
    }

    @Test func launchOpensTheAnswerOverTheCompanyPage() throws {
        let route = try #require(LaunchRoute(argument: "ask=dart:00126380|profit_or_loss"))
        #expect(route.askIntent == .profitOrLoss)
        #expect(route.companiesPath == [.company("dart:00126380"), .answer("dart:00126380", .profitOrLoss)])
        #expect(route.sidebarItem == .company("dart:00126380"))
        #expect(route.filingID == "ask:profit_or_loss")
    }

    @Test func launchWithAnUnknownQuestionOpensTheCompanyPage() throws {
        let route = try #require(LaunchRoute(argument: "ask=dart:00126380|forecast"))
        #expect(route.askIntent == nil)
        #expect(route.companiesPath == [.company("dart:00126380")])
        #expect(route.filingID == nil)
    }
}
