import FootnoteKit
import SwiftUI

/// The split view's detail selection for the summary card: `summary:year` and
/// `summary:quarter` beside filing ids, for the company the sidebar shows. The card's rows
/// cannot use the reports' own filing ids: the periodic reports below list the same ones.
enum SummarySelection: String {
    case year
    case quarter

    private static let prefix = "summary:"

    var id: String { Self.prefix + rawValue }

    init?(_ id: String?) {
        guard let id, id.hasPrefix(Self.prefix) else { return nil }
        self.init(rawValue: String(id.dropFirst(Self.prefix.count)))
    }

    /// The screen the row opens: the annual revenue figure, or the quarter report.
    func route(_ summary: CompanySummary, companyID: String) -> Route? {
        switch self {
        case .year:
            guard let figures = summary.yearFigures, case .year(let fiscalYear) = figures.span else { return nil }
            return .figure(companyID, ReportedMetric.revenue.rawValue, fiscalYear)
        case .quarter:
            return summary.quarterFigures.map { .filing($0.filing.id) }
        }
    }
}

/// The company page's first card (owner pick 2026-11-26, design direction 1 B; D100): the
/// newest annual revenue against the year before, then the newest quarter's three figures
/// against the same quarter a year earlier, each with the filing it comes from. A missing
/// report or figure is said in words, never shown as zero.
struct CompanySummaryCard: View {
    @Environment(\.language) private var language
    @Environment(\.filingSelection) private var selection
    let summary: CompanySummary
    let companyID: String

    var body: some View {
        Section {
            year
            quarter
        } header: {
            SectionTitle(language("최근 실적", "Latest results"))
                .accessibilityAddTraits(.isHeader)
        }
    }

    @ViewBuilder private var year: some View {
        switch summary.year {
        case .figures(let figures):
            if let row = figures.rows.first, row.current != nil, case .year(let fiscalYear) = figures.span {
                link(.year) { YearHero(figures: figures, row: row, fiscalYear: fiscalYear) }
                    .accessibilityIdentifier("summary-year")
            } else if let statement = figures.statement {
                statementRow(statement)
            }
        case .statement(let sentence):
            statementRow(sentence)
        default:
            EmptyView()
        }
    }

    @ViewBuilder private var quarter: some View {
        switch summary.quarter {
        case .figures(let figures):
            link(.quarter) { QuarterLines(figures: figures) }
                .accessibilityIdentifier("summary-quarter")
        case .statement(let sentence):
            statementRow(sentence)
        default:
            EmptyView()
        }
    }

    @ViewBuilder private func link<Label: View>(_ part: SummarySelection, @ViewBuilder label: () -> Label) -> some View {
        if let route = part.route(summary, companyID: companyID) {
            SelectableRow(value: part.id, selection: selection, route: route, identifier: "summary-\(part.rawValue)") {
                label()
            }
        }
    }

    private func statementRow(_ sentence: AnswerSentence) -> some View {
        Text(words: sentence.text(language))
            .font(.body)
            .foregroundStyle(Theme.muted)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.vertical, 6)
            .frame(maxWidth: .infinity, minHeight: Theme.minTarget, alignment: .leading)
            .listRowBackground(Theme.surface)
    }
}

/// The hero: the year's revenue rounded, the exact amount under it, the change from the
/// year before with its glyph, and the report it comes from.
private struct YearHero: View {
    @Environment(\.language) private var language
    let figures: AnswerFigures
    let row: AnswerFigureRow
    let fiscalYear: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(words: context)
                .font(.subheadline)
                .foregroundStyle(Theme.muted)
                .fixedSize(horizontal: false, vertical: true)
            if let current = row.current {
                let headline = AskCopy.shortened(current, language)
                let exact = AskCopy.exact(current, language)
                BigValue(text: headline)
                if exact != headline {
                    UnbrokenNumbers(text: PageCopy.exactAmount(exact, language))
                        .font(.subheadline)
                        .monospacedDigit()
                        .foregroundStyle(Theme.muted)
                }
            }
            switch row.change {
            case .result(let percent)?:
                PhraseLines(phrases: PageCopy.changeFromLastYearPhrases(percent, language))
                    .font(.body.weight(.semibold))
                    .monospacedDigit()
                    .foregroundStyle(Theme.ink)
            case .refusal(let refusal)?:
                Text(words: PageCopy.refusal(refusal, language))
                    .font(.subheadline)
                    .foregroundStyle(Theme.muted)
                    .fixedSize(horizontal: false, vertical: true)
            case nil:
                EmptyView()
            }
            SummarySource(filing: figures.filing)
        }
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(spoken)
    }

    private var context: String {
        var parts = [row.metric.name(language), PageCopy.fiscalYear(fiscalYear, language)]
        if let basis = PageCopy.basisName(figures.basis, language) { parts.append(basis) }
        return parts.joined(separator: Copy.dot)
    }

    private var spoken: String {
        [context.spokenSeparators, AskCopy.spoken(row, language), SummarySource.spoken(figures.filing, language)]
            .joined(separator: ", ")
    }
}

/// The quarter: its heading, the fixed sentence that reads its revenue, then revenue,
/// operating income and net income, each with its change from the same quarter a year
/// earlier, and the report.
private struct QuarterLines: View {
    @Environment(\.language) private var language
    let figures: AnswerFigures

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(words: AskCopy.quarterHeading(figures.period, language))
                .font(.subheadline)
                .foregroundStyle(Theme.muted)
                .fixedSize(horizontal: false, vertical: true)
            if let statement = figures.statement {
                Text(words: statement.text(language))
                    .font(.body)
                    .foregroundStyle(Theme.ink)
                    .fixedSize(horizontal: false, vertical: true)
            }
            VStack(alignment: .leading, spacing: 6) {
                ForEach(figures.rows) { row in
                    SummaryFigureLine(row: row)
                }
            }
            SummarySource(filing: figures.filing)
        }
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(spoken)
    }

    private var spoken: String {
        var parts = [AskCopy.quarterHeading(figures.period, language).spokenSeparators]
        if let statement = figures.statement { parts.append(statement.text(language)) }
        parts += figures.rows.map { AskCopy.spoken($0, language) }
        parts.append(SummarySource.spoken(figures.filing, language))
        return parts.joined(separator: ", ")
    }
}

/// One quarter figure: the name on the left, the rounded amount and its change on the
/// right; stacked at accessibility sizes.
private struct SummaryFigureLine: View {
    @Environment(\.language) private var language
    @Environment(\.dynamicTypeSize) private var typeSize
    let row: AnswerFigureRow

    var body: some View {
        if typeSize.isAccessibilitySize {
            VStack(alignment: .leading, spacing: 2) {
                name
                value(alignment: .leading)
            }
        } else {
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                name
                Spacer(minLength: 0)
                value(alignment: .trailing)
            }
        }
    }

    private var name: some View {
        Text(words: row.metric.name(language))
            .font(.subheadline)
            .foregroundStyle(Theme.muted)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func value(alignment: HorizontalAlignment) -> some View {
        let text: TextAlignment = alignment == .trailing ? .trailing : .leading
        return VStack(alignment: alignment, spacing: 0) {
            if let current = row.current {
                let amount = AskCopy.shortened(current, language)
                Text(words: amount)
                    .font(.subheadline.weight(.semibold))
                    .monospacedDigit()
                    .foregroundStyle(Theme.ink)
                    .numberTransition(amount)
                    .multilineTextAlignment(text)
                    .fixedSize(horizontal: false, vertical: true)
                if let change = AskCopy.change(row, language) {
                    Text(words: change)
                        .font(.footnote)
                        .monospacedDigit()
                        .foregroundStyle(isResult ? Theme.ink : Theme.muted)
                        .multilineTextAlignment(text)
                        .fixedSize(horizontal: false, vertical: true)
                }
            } else {
                Text(words: AskCopy.notInReport(language))
                    .font(.subheadline)
                    .foregroundStyle(Theme.muted)
                    .multilineTextAlignment(text)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var isResult: Bool {
        if case .result? = row.change { return true }
        return false
    }
}

/// The report a card row comes from: `출처 · 2026년 3분기 보고서 · 11월 16일 공시`.
private struct SummarySource: View {
    @Environment(\.language) private var language
    let filing: Filing

    var body: some View {
        Text(words: Self.line(filing, language))
            .font(.footnote)
            .monospacedDigit()
            .foregroundStyle(Theme.muted)
            .fixedSize(horizontal: false, vertical: true)
    }

    static func line(_ filing: Filing, _ language: Language) -> String {
        AskCopy.source(language) + Copy.dot + Titles.title(for: filing, language: language)
            + Copy.dot + Copy.filedOn(filing.filedOn, language)
    }

    static func spoken(_ filing: Filing, _ language: Language) -> String {
        line(filing, language).spokenSeparators
    }
}
