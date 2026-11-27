import Foundation
import Testing
@testable import FootnoteKit

/// A router that records what it was asked and answers with a fixed route or an error.
private final class RecordingRouter: QuestionRouter, @unchecked Sendable {
    struct Failure: Error {}

    let result: Result<QuestionRoute, Failure>
    private let lock = NSLock()
    private var asked: [String] = []

    init(_ result: Result<QuestionRoute, Failure>) { self.result = result }

    var questions: [String] { lock.withLock { asked } }

    func route(_ text: String) async throws -> QuestionRoute {
        lock.withLock { asked.append(text) }
        return try result.get()
    }
}

@Suite("Typed questions (D108)")
struct TypedQuestionsTests {
    @Test func everyRouteRoundTripsThroughItsKey() {
        #expect(QuestionRoute.allCases.count == QuestionIntent.allCases.count + 1)
        for route in QuestionRoute.allCases {
            #expect(QuestionRoute(key: route.key) == route)
        }
        #expect(QuestionRoute(key: "forecast") == nil)
    }

    @Test func textIsTrimmedAndCapped() {
        #expect(TypedQuestion.cleaned("  매출은 어때요?\n") == "매출은 어때요?")
        #expect(TypedQuestion.cleaned(" \n\t ") == nil)
        #expect(TypedQuestion.cleaned("") == nil)
        let long = String(repeating: "가", count: TypedQuestion.maximumLength + 50)
        #expect(TypedQuestion.cleaned(long)?.count == TypedQuestion.maximumLength)
    }

    @Test func theRouterSeesCleanedTextAndItsChoiceIsKept() async {
        let router = RecordingRouter(.success(.intent(.revenue)))
        #expect(await TypedQuestion.route("  How is revenue doing? ", with: router) == .intent(.revenue))
        #expect(router.questions == ["How is revenue doing?"])
    }

    @Test func emptyTextIsNoneWithoutAskingTheRouter() async {
        let router = RecordingRouter(.success(.intent(.revenue)))
        #expect(await TypedQuestion.route("   ", with: router) == QuestionRoute.none)
        #expect(router.questions.isEmpty)
    }

    /// A refusal, a guardrail or an unsupported language shows the "can't answer" line.
    @Test func aRouterErrorIsNone() async {
        let router = RecordingRouter(.failure(.init()))
        #expect(await TypedQuestion.route("Should I buy?", with: router) == QuestionRoute.none)
    }

    #if canImport(FoundationModels)
    /// The model's choices name each route once, and advice and price predictions go to the
    /// no-advice answer.
    @Test func theModelsChoicesCoverEveryRouteOnce() throws {
        guard #available(macOS 26.0, iOS 26.0, *) else { return }
        let routes = OnDeviceQuestionRouter.Choice.allCases.map(\.route)
        #expect(Set(routes) == Set(QuestionRoute.allCases))
        #expect(routes.count == QuestionRoute.allCases.count)
        #expect(OnDeviceQuestionRouter.Choice.adviceOrPricePrediction.route == .intent(.shouldBuy))
    }
    #endif

    /// `contracts/typed-questions.json`, the eval's labelled set.
    @Test func theLabelledSetIsBalancedAndValid() throws {
        struct LabelledSet: Decodable {
            struct Question: Decodable { let id, lang, text, label, kind: String }
            let labels: [String]
            let kinds: [String]
            let questions: [Question]
        }
        let url = Support.repositoryRoot.appendingPathComponent("contracts/typed-questions.json")
        let set = try JSONDecoder().decode(LabelledSet.self, from: Data(contentsOf: url))
        #expect(set.labels == QuestionRoute.allCases.map(\.key))
        #expect(set.questions.count >= 60)
        #expect(Set(set.questions.map(\.id)).count == set.questions.count)
        #expect(Set(set.questions.map(\.text)).count == set.questions.count)
        let korean = set.questions.filter { $0.lang == "ko" }.count
        let english = set.questions.filter { $0.lang == "en" }.count
        #expect(korean + english == set.questions.count)
        #expect(abs(korean - english) <= set.questions.count / 10)
        for question in set.questions {
            #expect(QuestionRoute(key: question.label) != nil, "\(question.id)")
            #expect(set.kinds.contains(question.kind), "\(question.id)")
            #expect(TypedQuestion.cleaned(question.text) == question.text, "\(question.id)")
            if question.kind == "advice" { #expect(question.label == "should_buy", "\(question.id)") }
        }
        // Every label in both languages, and every kind.
        for label in set.labels {
            for lang in ["ko", "en"] {
                #expect(set.questions.contains { $0.label == label && $0.lang == lang }, "\(label) \(lang)")
            }
        }
        #expect(Set(set.questions.map(\.kind)) == Set(set.kinds))
    }
}
