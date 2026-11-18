import Foundation
import Testing
@testable import FootnoteKit

@Suite("Shared contracts")
struct ContractTests {
    /// The test bundle carries copies (`scripts/sync-contracts.sh`); they must equal the
    /// originals in `contracts/`, so a contract edit cannot pass here on a stale copy.
    @Test(arguments: ["comparison-cases.json", "financial-vocabulary.json", "filing-categories.json"])
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

    /// Figures stay `Decimal` from the bundle to the screen: no source file names a binary
    /// floating-point type or reads one from SQLite.
    @Test func sourcesUseNoBinaryFloatingPoint() throws {
        let files = try FileManager.default
            .contentsOfDirectory(at: Support.packageSources, includingPropertiesForKeys: nil)
            .filter { $0.pathExtension == "swift" }
        #expect(files.count >= 6)
        let banned = try Regex(
            #"\b(Double|Float|Float16|Float32|Float64|Float80|CGFloat|TimeInterval)\b|column_double|doubleValue|floatValue"#)
        for file in files {
            let text = try String(contentsOf: file, encoding: .utf8)
            for (number, line) in text.split(separator: "\n", omittingEmptySubsequences: false)
                .enumerated() where line.contains(banned) {
                Issue.record("\(file.lastPathComponent):\(number + 1): \(line)")
            }
        }
    }
}
