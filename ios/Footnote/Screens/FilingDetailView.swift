import FootnoteKit
import SwiftUI

/// The filing page for this slice: tag and status, title, date, the summary or the
/// "summary in review" state, the numbers the filing states, and the original. The full
/// filing page (board 12A) replaces it in the next slice; the order stays fixed: sentences,
/// numbers, original.
struct FilingDetailView: View {
    static let maxFacts = 6

    @Environment(\.language) private var language
    let store: BundleStore
    let labels: FactLabels
    let filing: Filing

    private var company: Company? { store.company(id: filing.companyID) }

    var body: some View {
        List {
            header
            Section(language("공시 내용", "What the filing says")) {
                if summaryLines.isEmpty {
                    inReview
                } else {
                    ForEach(Array(summaryLines.enumerated()), id: \.offset) { _, line in
                        Text(words: line)
                            .font(.body)
                            .foregroundStyle(Theme.ink)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .listRowBackground(Theme.surface)
                }
            }
            if !factRows.isEmpty {
                Section(language("공시의 숫자", "Numbers in the filing")) {
                    ForEach(factRows) { row in
                        FactRow(label: row.label, value: row.value)
                    }
                }
            }
            Section {
                ExternalLinkRow(
                    title: Copy.openOriginal(company?.regulator ?? .dart, language),
                    url: URL(string: filing.sourceURL),
                    showsNetworkNote: true)
                    .listRowBackground(Theme.surface)
            }
        }
        .groupedScreen()
        .navigationTitle(company.map { Titles.name(of: $0, language: language) } ?? "")
        #if os(iOS)
        .navigationBarTitleDisplayMode(.inline)
        #endif
        .languageToolbar()
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            FilingMeta(filing: filing, dataAsOf: store.meta.dataAsOf)
            Text(words: Titles.title(for: filing, language: language))
                .font(.title2.bold())
                .foregroundStyle(Theme.ink)
                .fixedSize(horizontal: false, vertical: true)
            Text(words: Copy.filedOn(filing.filedOn, language))
                .font(.subheadline)
                .monospacedDigit()
                .foregroundStyle(Theme.muted)
        }
        .padding(.vertical, 4)
        .listRowBackground(Color.clear)
        .listRowInsets(EdgeInsets(top: 0, leading: 4, bottom: 0, trailing: 4))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(
            FilingRow.spoken(filing, dataAsOf: store.meta.dataAsOf, companyName: nil, language))
        .accessibilityAddTraits(.isHeader)
    }

    /// Board 19, summary_in_review.
    private var inReview: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(words: language("요약을 확인하고 있어요", "Summary in review"))
                .font(.body.weight(.semibold))
                .foregroundStyle(Theme.ink)
            Text(words: language(
                "확인을 마친 요약만 보여 줘요. 공시의 숫자와 원문은 지금 볼 수 있어요.",
                "Only checked summaries are shown. The filing’s numbers and the original are available now."))
                .font(.subheadline)
                .foregroundStyle(Theme.muted)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.vertical, 4)
        .listRowBackground(Theme.surface)
        .accessibilityElement(children: .combine)
    }

    /// Approved lines only (the bundle holds nothing else): the three event lines, or an
    /// annual report's one line.
    private var summaryLines: [String] {
        let section: SummarySection = filing.kind == .annual ? .oneLine : .summary
        return store.summary(forFiling: filing.id, language: language, section: section)?.lines ?? []
    }

    /// Numbers and dates the filing states, at most six rows. Text fields (a stated purpose,
    /// the SEC item list) belong to the sentences of the full filing page. A period that
    /// starts and ends on the same day is one row.
    private var factRows: [FactLine] {
        let facts = store.facts(forFiling: filing.id).filter { $0.value.kind != .text }
        return Self.foldSingleDays(facts).prefix(Self.maxFacts).map { fact, singleDay in
            FactLine(id: fact.position, label: singleDay ? singleDayLabel(fact) : label(fact), value: value(fact))
        }
    }

    /// Drops the `_end` fact of each `_start`/`_end` pair that names the same day, and marks
    /// its start as a single day.
    nonisolated static func foldSingleDays(_ facts: [FilingFact]) -> [(fact: FilingFact, singleDay: Bool)] {
        var ends: Set<Int> = []
        var starts: Set<Int> = []
        for fact in facts where fact.key.hasSuffix("_start") {
            guard case .date(let start) = fact.value,
                  let end = facts.first(where: { $0.key == String(fact.key.dropLast(6)) + "_end" }),
                  case .date(let endDate) = end.value, endDate == start
            else { continue }
            starts.insert(fact.position)
            ends.insert(end.position)
        }
        return facts.filter { !ends.contains($0.position) }.map { ($0, starts.contains($0.position)) }
    }

    /// Single-day names for the periods filings most often state as one day.
    private static let singleDay: [String: (ko: String, en: String)] = [
        "dispose_period_start": ("처분 예정일", "Disposal date"),
        "acquire_period_start": ("취득 예정일", "Acquisition date"),
    ]

    private func singleDayLabel(_ start: FilingFact) -> String {
        if let names = Self.singleDay[start.key] { return language(names.ko, names.en) }
        let base = label(start)
        return language(
            base.replacingOccurrences(of: " 시작일", with: "") + " (하루)",
            base.replacingOccurrences(of: " start", with: "") + " (one day)")
    }

    private func label(_ fact: FilingFact) -> String {
        labels.label(fact, language) ?? fact.key
    }

    private func value(_ fact: FilingFact) -> String {
        switch fact.value {
        case .amount(let amount):
            let currency = fact.unit ?? company?.currency ?? "KRW"
            return Formatting.amount(amount, currency: currency, language: language)
        case .shares(let shares):
            return Formatting.number(shares) + language("주", " shares")
        case .ratio(let ratio):
            return Formatting.percent(ratio)
        case .date(let date):
            return Formatting.fullDate(date, language: language)
        case .text(let text):
            return text
        }
    }
}

struct FactLine: Identifiable {
    let id: Int
    let label: String
    let value: String
}

struct FactRow: View {
    let label: String
    let value: String

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                labelText
                Spacer(minLength: 12)
                valueText.multilineTextAlignment(.trailing)
            }
            VStack(alignment: .leading, spacing: 2) {
                labelText
                valueText
            }
        }
        .frame(minHeight: Theme.minTarget)
        .listRowBackground(Theme.surface)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(label), \(value)")
    }

    private var labelText: some View {
        Text(words: label)
            .font(.body)
            .foregroundStyle(Theme.ink)
            .fixedSize(horizontal: false, vertical: true)
    }

    private var valueText: some View {
        Text(words: value)
            .font(.body.weight(.semibold))
            .monospacedDigit()
            .foregroundStyle(Theme.ink)
            .fixedSize()
    }
}
