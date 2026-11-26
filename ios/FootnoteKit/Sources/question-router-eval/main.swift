import Foundation
import FootnoteKit

// Runs the on-device typed-question router (D108) on the labelled set in
// contracts/typed-questions.json and prints accuracy per label, per language and per kind,
// and a confusion matrix. Needs a Mac where Apple Intelligence is on.
//
//   swift run --package-path ios/FootnoteKit question-router-eval [set.json] [--json report.json]

struct LabelledSet: Decodable {
    struct Question: Decodable {
        let id: String
        let lang: String
        let text: String
        let label: String
        let kind: String
    }

    let labels: [String]
    let kinds: [String]
    let questions: [Question]
}

struct Outcome: Encodable {
    let id: String
    let lang: String
    let kind: String
    let text: String
    let label: String
    let predicted: String
    let error: String?
    let milliseconds: Int
}

func repositoryRoot() -> URL {
    // Sources/question-router-eval/main.swift -> the repository root, four levels up from FootnoteKit.
    URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
}

/// A share in tenths of a percent, without floating point (FootnoteKit's sources use none).
func percent(_ hits: Int, _ total: Int) -> String {
    guard total > 0 else { return "-" }
    let tenths = (hits * 1000 + total / 2) / total
    return "\(tenths / 10).\(tenths % 10)%"
}

func milliseconds(_ duration: Duration) -> Int {
    Int(duration.components.seconds) * 1000 + Int(duration.components.attoseconds / 1_000_000_000_000_000)
}

func pad(_ text: String, _ width: Int) -> String {
    text.count >= width ? text : text + String(repeating: " ", count: width - text.count)
}

func line(_ name: String, _ rows: [Outcome]) -> String {
    let hits = rows.filter { $0.predicted == $0.label }.count
    return "\(pad(name, 22)) \(pad("\(hits)/\(rows.count)", 7)) \(percent(hits, rows.count))"
}

@MainActor func run() async throws -> Int32 {
    var arguments = Array(CommandLine.arguments.dropFirst())
    var reportPath: String?
    if let index = arguments.firstIndex(of: "--json"), index + 1 < arguments.count {
        reportPath = arguments[index + 1]
        arguments.removeSubrange(index...(index + 1))
    }
    let setURL = arguments.first.map { URL(fileURLWithPath: $0) }
        ?? repositoryRoot().appendingPathComponent("contracts/typed-questions.json")
    let set = try JSONDecoder().decode(LabelledSet.self, from: Data(contentsOf: setURL))

    guard #available(macOS 26.0, *) else {
        print("The on-device model needs macOS 26 or later.")
        return 2
    }
    guard OnDeviceQuestionRouter.isAvailable else {
        print("The on-device model is not available here (Apple Intelligence off, model not ready, or Mac not eligible).")
        return 2
    }
    let router = OnDeviceQuestionRouter()
    var outcomes: [Outcome] = []
    for question in set.questions {
        let clock = ContinuousClock()
        let start = clock.now
        var predicted = "none"
        var failure: String?
        do {
            predicted = try await router.route(TypedQuestion.cleaned(question.text) ?? "").key
        } catch {
            // The app shows the "none" line for any router error.
            failure = String(describing: error)
        }
        let outcome = Outcome(
            id: question.id, lang: question.lang, kind: question.kind, text: question.text,
            label: question.label, predicted: predicted, error: failure,
            milliseconds: milliseconds(clock.now - start))
        outcomes.append(outcome)
        let mark = outcome.predicted == outcome.label ? "ok " : "MISS"
        print("\(mark) \(question.id) \(pad(question.label, 20)) -> \(pad(predicted, 20)) \(question.text)"
            + (failure.map { "  [error: \($0)]" } ?? ""))
    }

    print("\nAccuracy")
    print(line("all", outcomes))
    for lang in ["ko", "en"] { print(line("lang \(lang)", outcomes.filter { $0.lang == lang })) }
    for kind in set.kinds { print(line("kind \(kind)", outcomes.filter { $0.kind == kind })) }
    print("\nPer label (recall)")
    for label in set.labels { print(line(label, outcomes.filter { $0.label == label })) }

    print("\nConfusion matrix (rows: label, columns: predicted)")
    let short = ["should_buy": "buy", "fundamentals": "fund", "recent_trend": "trend",
                 "profit_or_loss": "p/l", "revenue": "rev", "next_quarter_revenue": "nextq", "none": "none"]
    print(pad("", 22) + set.labels.map { pad(short[$0] ?? $0, 6) }.joined())
    for label in set.labels {
        let row = outcomes.filter { $0.label == label }
        print(pad(label, 22) + set.labels.map { predicted in
            pad("\(row.filter { $0.predicted == predicted }.count)", 6)
        }.joined())
    }

    // The safety check: an advice question must reach the no-advice answer.
    let advice = outcomes.filter { $0.label == "should_buy" }
    let leaked = advice.filter { $0.predicted != "should_buy" }
    print("\nAdvice questions not routed to should_buy: \(leaked.count) of \(advice.count)")
    for outcome in leaked { print("  \(outcome.id) -> \(outcome.predicted): \(outcome.text)") }
    let errors = outcomes.filter { $0.error != nil }.count
    let times = outcomes.map(\.milliseconds).sorted()
    print("Router errors: \(errors). Milliseconds per question: median \(times[times.count / 2]), max \(times.last ?? 0).")

    if let reportPath {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        try encoder.encode(outcomes).write(to: URL(fileURLWithPath: reportPath))
        print("Wrote \(reportPath)")
    }
    return 0
}

exit(try await run())
