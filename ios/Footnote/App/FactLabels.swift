import FootnoteKit
import Foundation

/// Korean and English names for each fact, read from `contracts/filing-facts.json`, which
/// the app bundles as a resource. The contract is the one place the backend and the app name
/// a fact. A fact is named by its `origin` (`opendart:tsstkDpDecsn.dp_dd`), because one
/// `fact_key` such as `decision_date` means a different decision in each endpoint. A fact read
/// from a filing's table is `dartdoc:<table>.<key>`, as `app.build.export` names it.
struct FactLabels: Sendable {
    private let labels: [String: (ko: String, en: String)]

    /// SEC facts carry English names only in the contract.
    private static let secKorean = ["items": "항목 번호", "report_date": "사건 발생일"]

    init(contract data: Data) throws {
        let contract = try JSONDecoder().decode(Contract.self, from: data)
        var labels: [String: (ko: String, en: String)] = [:]
        for field in contract.sec.fields {
            labels[field.sourceField] = (Self.secKorean[field.key] ?? field.en, field.en)
        }
        for endpoint in contract.endpoints {
            for field in endpoint.fields {
                let origin = "opendart:\(endpoint.endpoint ?? "").\(field.sourceField)"
                labels[origin] = (field.ko ?? field.en, field.en)
            }
        }
        for document in contract.documents {
            for field in document.fields {
                labels["dartdoc:\(document.table).\(field.key)"] = (field.ko ?? field.en, field.en)
            }
        }
        self.labels = labels
    }

    static let bundled: FactLabels = {
        guard let url = Bundle.main.url(forResource: "filing-facts", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let labels = try? FactLabels(contract: data)
        else { return FactLabels(empty: ()) }
        return labels
    }()

    private init(empty: Void) { labels = [:] }

    var isEmpty: Bool { labels.isEmpty }

    func label(_ fact: FilingFact, _ language: Language) -> String? {
        label(origin: fact.origin, language)
    }

    func label(origin: String, _ language: Language) -> String? {
        labels[origin].map { language == .ko ? $0.ko : $0.en }
    }

    private struct Contract: Decodable {
        let sec: Group
        let endpoints: [Group]
        let documents: [Document]
    }

    private struct Document: Decodable {
        let table: String
        let fields: [Field]
    }

    private struct Group: Decodable {
        let endpoint: String?
        let fields: [Field]
    }

    private struct Field: Decodable {
        let key: String
        let sourceField: String
        let ko: String?
        let en: String

        enum CodingKeys: String, CodingKey {
            case key, ko, en
            case sourceField = "source_field"
        }
    }
}
