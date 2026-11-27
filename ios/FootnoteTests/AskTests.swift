import FootnoteKit
import Testing
#if os(iOS)
import UIKit
#endif
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

    @Test func wrappedTextKeepsItsLastWordsTogether() {
        #expect(AskCopy.keepingTail("The company reported higher revenue for its latest quarter.")
            == "The company reported higher revenue for its\u{00A0}latest\u{00A0}quarter.")
        #expect(AskCopy.keepingTail("회사는 최근 분기 매출이 늘었다고 보고했어요.")
            == "회사는 최근 분기 매출이\u{00A0}늘었다고\u{00A0}보고했어요.")
        // A long last word stays alone rather than making an unbreakable run.
        #expect(AskCopy.keepingTail("Tap to see consolidated-statement-figures")
            == "Tap to see consolidated-statement-figures")
        #expect(AskCopy.keepingTail("매출은 어때요?") == "매출은 어때요?")
        // VoiceOver reads plain spaces.
        #expect(AskCopy.keepingTail("최근 흐름은 어때요?").spokenSeparators == "최근 흐름은 어때요?")
    }

    @Test func aLongQuestionSplitsIntoTwoPhrases() {
        #expect(AskCopy.halves("이 주식 사도 될까요?") == ["이 주식", "사도 될까요?"])
        #expect(AskCopy.halves("What's next quarter's revenue?") == ["What's next", "quarter's revenue?"])
        #expect(AskCopy.halves("매출은 어때요?") == ["매출은", "어때요?"])
        #expect(AskCopy.halves("What are the fundamentals?") == ["What are the", "fundamentals?"])
        #expect(AskCopy.halves("Does it make or lose money?") == ["Does it make", "or lose money?"])
        #expect(AskCopy.halves("Revenue") == ["Revenue"])
        #expect(AskCopy.balanced("이 주식 사도 될까요?") == "이\u{00A0}주식 사도\u{00A0}될까요?")
    }

    @Test func launchWithAnUnknownQuestionOpensTheCompanyPage() throws {
        let route = try #require(LaunchRoute(argument: "ask=dart:00126380|forecast"))
        #expect(route.askIntent == nil)
        #expect(route.companiesPath == [.company("dart:00126380")])
        #expect(route.filingID == nil)
    }

    // D108: typed questions.

    @Test @MainActor func debugArgumentsChooseTheStubOrHideTheField() async throws {
        let stub = try #require(QuestionRouting.make(arguments: ["Footnote", "-FootnoteTypedQuestions", "stub"]))
        #expect(await TypedQuestion.route("매출 알려 줘", with: stub) == .intent(.revenue))
        #expect(await TypedQuestion.route("Should I buy?", with: stub) == .intent(.shouldBuy))
        #expect(await TypedQuestion.route("오늘 날씨", with: stub) == QuestionRoute.none)
        #expect(QuestionRouting.make(arguments: ["Footnote", "-FootnoteTypedQuestions", "off"]) == nil)
    }

    #if os(iOS)
    /// iPhone keeps its company page as it was: no field, whatever the model can do.
    @Test @MainActor func iPhoneHasNoTypedQuestions() {
        guard UIDevice.current.userInterfaceIdiom == .phone else { return }
        #expect(QuestionRouting.make(arguments: ["Footnote"]) == nil)
    }
    #endif

    @Test(arguments: [Language.ko, .en])
    func typedCopyHasNoDigitsOrDashes(_ language: Language) {
        let texts = [AskCopy.typedPlaceholder(language), AskCopy.typedFieldLabel(language),
                     AskCopy.typedSubmit(language), AskCopy.typedWorking(language),
                     AskCopy.typedNone(language), AskCopy.typedNote(language)]
        for text in texts {
            #expect(!text.contains { $0.isNumber }, "\(text)")
            #expect(!text.contains("\u{2014}"), "\(text)")
            #expect(!text.isEmpty)
        }
    }
}
