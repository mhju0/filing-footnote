import FootnoteKit
import SwiftUI

/// The split view's detail selection for an answer: `ask:<intent>` beside filing ids, for
/// the company the sidebar shows.
enum AskSelection {
    private static let prefix = "ask:"

    static func id(_ intent: QuestionIntent) -> String { prefix + intent.rawValue }

    static func intent(_ id: String?) -> QuestionIntent? {
        guard let id, id.hasPrefix(prefix) else { return nil }
        return QuestionIntent(rawValue: String(id.dropFirst(prefix.count)))
    }
}

/// The company page's question section (D95): one button per question, wrapping like words.
/// A button opens the answer: pushed on iPhone, in the detail column on iPad and Mac, where
/// the question being answered stays filled.
struct AskSection: View {
    @Environment(\.language) private var language
    @Environment(\.navigate) private var navigate
    @Environment(\.filingSelection) private var selection
    let companyID: String

    var body: some View {
        Section {
            FlowLayout(spacing: 8, lineSpacing: 8) {
                ForEach(QuestionIntent.allCases) { intent in
                    QuestionButton(
                        title: intent.question(language),
                        isSelected: AskSelection.intent(selection?.wrappedValue) == intent
                    ) {
                        if let selection {
                            selection.wrappedValue = AskSelection.id(intent)
                        } else {
                            navigate(.answer(companyID, intent))
                        }
                    }
                    .accessibilityIdentifier("ask-\(intent.rawValue)")
                }
            }
            .padding(.vertical, 4)
            .frame(maxWidth: .infinity, alignment: .leading)
            .listRowBackground(Color.clear)
            .listRowInsets(EdgeInsets(top: 4, leading: 0, bottom: 4, trailing: 0))
        } header: {
            SectionTitle(AskCopy.sectionTitle(language))
                .accessibilityAddTraits(.isHeader)
        } footer: {
            SectionNote(text: AskCopy.sectionNote(language))
        }
    }
}

/// A question as a rounded-rectangle button (DESIGN.md: no pills): Surface with a Line
/// border and Pine text; Pine filled while its answer is in the detail column.
private struct QuestionButton: View {
    @Environment(\.language) private var language
    let title: String
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(words: title)
                .font(.body.weight(.medium))
                .multilineTextAlignment(.leading)
                .fixedSize(horizontal: false, vertical: true)
                .foregroundStyle(isSelected ? Theme.onPine : Theme.pine)
                .padding(.horizontal, 12)
                .padding(.vertical, 10)
                .frame(minWidth: Theme.minTarget, minHeight: Theme.minTarget)
                .background(isSelected ? Theme.pine : Theme.surface, in: shape)
                .overlay { shape.strokeBorder(isSelected ? Theme.pine : Theme.line) }
                .contentShape(shape)
        }
        .buttonStyle(.plain)
        .accessibilityHint(AskCopy.chipHint(language))
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }

    private var shape: RoundedRectangle { RoundedRectangle(cornerRadius: 10, style: .continuous) }
}

/// An answer (D95): the question as the title, then the fixed sentences, quoted summary
/// lines and exact figures the answerer chose, each block with the filing it comes from.
struct AnswerView: View {
    @Environment(\.language) private var language
    @Environment(\.navigate) private var navigate
    let store: BundleStore
    let answer: Answer

    var body: some View {
        ScrollViewReader { proxy in
            List {
                ScreenHeader(
                    context: Titles.name(of: answer.company, language: language),
                    title: answer.intent.question(language))
                ForEach(Array(groups.enumerated()), id: \.offset) { _, group in
                    switch group {
                    case .statements(let sentences): statements(sentences)
                    case .part(let part): partSection(part)
                    }
                }
                if !answer.related.isEmpty {
                    Section {
                        ForEach(answer.related) { intent in
                            LinkRow(title: intent.question(language)) { navigate(.answer(answer.company.id, intent)) }
                                .accessibilityIdentifier("related-\(intent.rawValue)")
                        }
                    } header: {
                        SectionTitle(AskCopy.related(language))
                    }
                }
                Section {
                    SectionNote(text: AnswerSentence.howAnswered.text(language))
                        .headerRow()
                        .listRowSeparator(.hidden)
                }
                PageEndMarker()
            }
            .launchScroll(proxy)
        }
        .groupedScreen()
        .screenTitle(answer.intent.question(language))
        .languageToolbar()
        .accessibilityIdentifier("answer-page")
    }

    /// Consecutive statements share one card; every other part is its own section.
    private enum Group {
        case statements([AnswerSentence])
        case part(AnswerPart)
    }

    private var groups: [Group] {
        var groups: [Group] = []
        for part in answer.parts {
            if case .statement(let sentence) = part {
                if case .statements(let previous)? = groups.last {
                    groups[groups.count - 1] = .statements(previous + [sentence])
                } else {
                    groups.append(.statements([sentence]))
                }
            } else {
                groups.append(.part(part))
            }
        }
        return groups
    }

    private func statements(_ sentences: [AnswerSentence]) -> some View {
        Section {
            SentenceRows(lines: sentences.map { $0.text(language) })
                .accessibilityElement(children: .combine)
                .accessibilityIdentifier("answer-statements")
        }
    }

    @ViewBuilder private func partSection(_ part: AnswerPart) -> some View {
        switch part {
        case .statement(let sentence):
            statements([sentence])
        case .summary(let summary):
            let lines = summary.lines(language)
            if lines.isEmpty {
                statements([.businessMissing])
            } else {
                Section {
                    SentenceRows(lines: lines)
                        .accessibilityElement(children: .combine)
                    SourceRow(filing: summary.filing)
                } header: {
                    SectionTitle(AskCopy.business(language))
                }
            }
        case .figures(let figures):
            FiguresSection(figures: figures)
        case .filing(let sentence, let filing):
            Section {
                SentenceRows(lines: [sentence.text(language)])
                NavigationLink(value: Route.filing(filing.id)) {
                    FilingRow(filing: filing, dataAsOf: answer.dataAsOf)
                }
                .listRowBackground(Theme.surface)
                .accessibilityIdentifier("answer-outlook")
            } header: {
                SectionTitle(AskCopy.outlook(language))
            }
        }
    }
}

/// One report's figures: the sentence that reads them, each figure against the same period
/// a year earlier, then the report itself.
private struct FiguresSection: View {
    @Environment(\.language) private var language
    let figures: AnswerFigures

    var body: some View {
        Section {
            if let statement = figures.statement {
                SentenceRows(lines: [statement.text(language)])
            }
            ForEach(figures.rows) { row in
                if let current = row.current {
                    FactRow(
                        label: row.metric.name(language),
                        value: AskCopy.shortened(current, language),
                        details: AskCopy.change(row, language).map { [$0] } ?? [],
                        spoken: AskCopy.spoken(row, language),
                        exact: AskCopy.exactLines(row, language))
                        .accessibilityIdentifier("answer-\(spanKey)-\(row.metric.rawValue)")
                } else {
                    FactRow(label: row.metric.name(language), value: AskCopy.notInReport(language))
                        .accessibilityIdentifier("answer-\(spanKey)-\(row.metric.rawValue)")
                }
            }
            SourceRow(filing: figures.filing)
        } header: {
            SectionTitle(heading)
        } footer: {
            SectionNote(text: AskCopy.figuresNote(prior: figures.priorPeriod, language))
        }
    }

    private var spanKey: String {
        if case .quarter = figures.span { return "quarter" }
        return "year"
    }

    private var heading: String {
        switch figures.span {
        case .quarter: AskCopy.quarterHeading(figures.period, language)
        case .year(let fiscalYear): AskCopy.yearHeading(fiscalYear, basis: figures.basis, language)
        }
    }
}

/// The filing a block cites: its title and filed date, opening the filing's page.
private struct SourceRow: View {
    @Environment(\.language) private var language
    let filing: Filing

    var body: some View {
        NavigationLink(value: Route.filing(filing.id)) {
            VStack(alignment: .leading, spacing: 2) {
                Text(words: AskCopy.source(language) + Copy.dot + Titles.title(for: filing, language: language))
                    .font(.subheadline)
                    .foregroundStyle(Theme.pine)
                    .fixedSize(horizontal: false, vertical: true)
                Text(words: Copy.filedOn(filing.filedOn, language))
                    .font(.footnote)
                    .monospacedDigit()
                    .foregroundStyle(Theme.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(minHeight: Theme.minTarget, alignment: .leading)
        }
        .listRowBackground(Theme.surface)
        .accessibilityElement(children: .combine)
        .accessibilityHint(language("공시를 열어요", "Opens the filing"))
        .accessibilityIdentifier("answer-source-\(filing.id)")
    }
}

/// Resolves an answer route; nothing for a company the bundle does not hold.
struct AnswerDestination: View {
    let store: BundleStore
    let companyID: String
    let intent: QuestionIntent

    var body: some View {
        if let answer = CompanyAnswerer.answer(intent, store: store, companyID: companyID) {
            AnswerView(store: store, answer: answer)
        }
    }
}
