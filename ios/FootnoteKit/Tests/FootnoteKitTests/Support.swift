import Foundation
import SQLite3
import Testing
@testable import FootnoteKit

/// Paths and loaders the tests share.
enum Support {
    /// The repository root, from this file's place in `ios/FootnoteKit/Tests/FootnoteKitTests`.
    static let repositoryRoot: URL = {
        var url = URL(fileURLWithPath: #filePath)
        for _ in 0..<5 { url.deleteLastPathComponent() }
        return url
    }()

    static let packageSources = repositoryRoot
        .appendingPathComponent("ios/FootnoteKit/Sources/FootnoteKit")

    static func resource(_ subdirectory: String, _ name: String) -> URL {
        let base = (name as NSString).deletingPathExtension
        let ext = (name as NSString).pathExtension
        guard let url = Bundle.module.url(
            forResource: base, withExtension: ext, subdirectory: subdirectory)
        else { fatalError("missing test resource \(subdirectory)/\(name)") }
        return url
    }

    static func contract(_ name: String) throws -> JSONValue {
        try JSONDecoder().decode(JSONValue.self, from: Data(contentsOf: resource("Contracts", name)))
    }

    static let fixtureURL = resource("Fixtures", "footnote.sqlite")

    static func decimal(_ text: String) -> Decimal { DecimalText.parsePlain(text)! }

    static func date(_ text: String) -> CivilDate { CivilDate(iso: text)! }

    struct EditFailed: Error { let message: String }

    /// A store over a temporary copy of the fixture after one SQL edit, for cases the fixture
    /// does not hold (a restated figure, a company with few filings).
    static func editedFixture(_ sql: String) throws -> BundleStore {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("footnote-\(UUID().uuidString).sqlite")
        try FileManager.default.copyItem(at: fixtureURL, to: url)
        var db: OpaquePointer?
        guard sqlite3_open(url.path, &db) == SQLITE_OK else { throw EditFailed(message: "open") }
        defer { sqlite3_close(db) }
        guard sqlite3_exec(db, sql, nil, nil, nil) == SQLITE_OK else {
            throw EditFailed(message: String(cString: sqlite3_errmsg(db)))
        }
        return try BundleStore(contentsOf: url)
    }
}

/// JSON without binary floating point: the contracts carry numbers as strings, and the only
/// JSON numbers they hold are integers.
enum JSONValue: Decodable, Equatable, Sendable, CustomStringConvertible {
    case null
    case bool(Bool)
    case integer(Int)
    case string(String)
    case array([JSONValue])
    case object([String: JSONValue])

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Int.self) {
            self = .integer(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else {
            self = .object(try container.decode([String: JSONValue].self))
        }
    }

    subscript(key: String) -> JSONValue? {
        if case .object(let object) = self { return object[key] }
        return nil
    }

    var string: String? {
        if case .string(let value) = self { return value }
        return nil
    }

    var array: [JSONValue] {
        if case .array(let value) = self { return value }
        return []
    }

    var strings: [String] { array.compactMap(\.string) }

    var description: String {
        switch self {
        case .null: "null"
        case .bool(let value): String(value)
        case .integer(let value): String(value)
        case .string(let value): "\"\(value)\""
        case .array(let value): "[" + value.map(\.description).joined(separator: ", ") + "]"
        case .object(let value):
            "{" + value.keys.sorted().map { "\"\($0)\": \(value[$0]!)" }
                .joined(separator: ", ") + "}"
        }
    }
}
