import Foundation
import Testing
@testable import FootnoteKit

@Suite("Shared contracts")
struct ContractTests {
    /// The test bundle carries copies (`scripts/sync-contracts.sh`); they must equal the
    /// originals in `contracts/`, so a contract edit cannot pass here on a stale copy.
    @Test(arguments: [
        "comparison-cases.json", "financial-vocabulary.json", "filing-categories.json", "company-questions.json",
    ])
    func copyMatchesTheRepositoryContract(_ name: String) throws {
        let copy = try Data(contentsOf: Support.resource("Contracts", name))
        let original = try Data(contentsOf: Support.repositoryRoot
            .appendingPathComponent("contracts").appendingPathComponent(name))
        #expect(copy == original, "run ios/FootnoteKit/scripts/sync-contracts.sh")
    }

    @Test func financialVocabulary() throws {
        let contract = try Support.contract("financial-vocabulary.json")
        #expect(contract["version"] == .integer(1))
        #expect(contract["reported_metrics"]!.strings == ReportedMetric.allCases.map(\.rawValue))
        #expect(contract["derived_metrics"]!.strings == DerivedMetric.allCases.map(\.rawValue))
        #expect(contract["period_kinds"]!.strings == PeriodKind.allCases.map(\.rawValue))
    }

    @Test func filingCategories() throws {
        let contract = try Support.contract("filing-categories.json")
        #expect(contract["version"] == .integer(2))
        let events = contract["categories"]!.array
        let others = contract["non_event_categories"]!.array
        // Event categories in priority order, then the non-event ones.
        let priorities = events.map { entry -> Int in
            guard case .integer(let value) = entry["priority"]! else { return -1 }
            return value
        }
        #expect(priorities == Array(1...events.count))
        let entries = events + others
        #expect(entries.map { $0["key"]!.string! } == FilingCategory.allCases.map(\.rawValue))
        for entry in entries {
            let category = try #require(FilingCategory(rawValue: entry["key"]!.string!))
            #expect(category.label(.ko) == entry["ko"]!.string!)
            #expect(category.label(.en) == entry["en"]!.string!)
        }
    }

    /// D95: the questions and answer sentences the backend's neutrality guard checks.
    @Test func companyQuestions() throws {
        let contract = try Support.contract("company-questions.json")
        #expect(contract["version"] == .integer(1))
        let intents = contract["intents"]!.array
        #expect(intents.map { $0["key"]!.string! } == QuestionIntent.allCases.map(\.rawValue))
        for entry in intents {
            let intent = try #require(QuestionIntent(rawValue: entry["key"]!.string!))
            #expect(intent.question(.ko) == entry["ko"]!.string!)
            #expect(intent.question(.en) == entry["en"]!.string!)
            #expect(intent.isDeflected == (entry["kind"]!.string! == "deflected"))
        }
        let sentences = contract["sentences"]!.array
        #expect(sentences.map { $0["key"]!.string! } == AnswerSentence.allCases.map(\.rawValue))
        for entry in sentences {
            let sentence = try #require(AnswerSentence(rawValue: entry["key"]!.string!))
            #expect(sentence.text(.ko) == entry["ko"]!.string!)
            #expect(sentence.text(.en) == entry["en"]!.string!)
        }
    }

    @Test func noticeCategories() throws {
        let contract = try Support.contract("filing-categories.json")
        let entries = contract["notice_categories"]!.array
        #expect(entries.map { $0["key"]!.string! } == NoticeCategory.allCases.map(\.rawValue))
        for entry in entries {
            let category = try #require(NoticeCategory(rawValue: entry["key"]!.string!))
            #expect(category.label(.ko) == entry["ko"]!.string!)
            #expect(category.label(.en) == entry["en"]!.string!)
        }
    }

    /// Figures stay `Decimal` from the bundle to the screen: no source file under `Sources/`
    /// names a binary floating-point type, reads one from SQLite, or builds a `Decimal` from a
    /// floating-point literal.
    @Test func sourcesUseNoBinaryFloatingPoint() throws {
        let files = Self.swiftFiles(under: Support.packageSources.deletingLastPathComponent())
        #expect(files.count >= 7)
        let banned = try Self.floatPattern()
        for file in files {
            let text = try String(contentsOf: file, encoding: .utf8)
            for (number, line) in text.split(separator: "\n", omittingEmptySubsequences: false)
                .enumerated() where line.contains(banned) {
                Issue.record("\(file.path):\(number + 1): \(line)")
            }
        }
    }

    @Test(arguments: ["let x: Double = 1", "let y = Decimal(0.5)", "let z: Decimal = 1.25",
                      "Decimal(floatLiteral: 1)", "sqlite3_column_double(s, 0)"])
    func floatBanCatches(_ line: String) throws {
        let banned = try Self.floatPattern()
        #expect(line.contains(banned))
    }

    /// Floating-point types, SQLite's double reader, and a `Decimal` built from a literal
    /// such as `Decimal(0.5)` or `: Decimal = 1.25`.
    static func floatPattern() throws -> Regex<AnyRegexOutput> {
        try Regex(
            #"\b(Double|Float|Float16|Float32|Float64|Float80|CGFloat|TimeInterval)\b"#
                + #"|column_double|doubleValue|floatValue|floatLiteral"#
                + #"|Decimal\(\s*-?[0-9]+\.[0-9]|Decimal\s*=\s*-?[0-9]+\.[0-9]"#)
    }

    /// Every `.swift` file under `root`, subfolders included.
    static func swiftFiles(under root: URL) -> [URL] {
        let enumerator = FileManager.default.enumerator(at: root, includingPropertiesForKeys: nil)
        return (enumerator?.allObjects as? [URL] ?? []).filter { $0.pathExtension == "swift" }
    }
}
