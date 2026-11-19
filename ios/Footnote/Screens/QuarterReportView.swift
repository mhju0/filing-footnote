import FootnoteKit
import SwiftUI

/// The quarter report (board 15, DESIGN.md Quarter report): three figures, each against the
/// same quarter a year earlier, then the related preliminary results and investor event, then
/// the original. Never the change from the quarter before, never a chart.
struct QuarterReportView: View {
    @Environment(\.language) private var language
    let store: BundleStore
    let page: QuarterPage

    var body: some View {
        ScrollViewReader { proxy in
            List {
                PageHeader(filing: page.filing, dataAsOf: page.dataAsOf)
                figures
                related
                SourceSection(source: page.source)
                GlossaryLinkSection(store: store, category: page.filing.category)
                PageEndMarker()
            }
            .launchScroll(proxy)
        }
        .groupedScreen()
        .pageTitle(page.company)
        .languageToolbar()
        .accessibilityIdentifier("quarter-page")
    }

    @ViewBuilder private var figures: some View {
        if let period = page.period {
            Section {
                ForEach(page.rows) { row in
                    if let route = Routes.figure(store, companyID: page.company.id, metric: row.metric) {
                        NavigationLink(value: route) {
                            QuarterFigureRowView(row: row, currency: page.currency)
                        }
                        .listRowBackground(Theme.surface)
                        .accessibilityIdentifier("quarter-\(row.metric.rawValue)")
                    } else {
                        QuarterFigureRowView(row: row, currency: page.currency)
                            .listRowBackground(Theme.surface)
                            .accessibilityIdentifier("quarter-\(row.metric.rawValue)")
                    }
                }
            } header: {
                SectionTitle(PageCopy.quarterFigures(start: period.start, end: period.end, language))            } footer: {
                SectionNote(text: PageCopy.quarterNote(prior: page.priorPeriod, language))
            }
            .id(PageScroll.numbers)
        }
    }

    @ViewBuilder private var related: some View {
        if page.preliminary != nil || page.investorEvent != nil {
            Section {
                if let filing = page.preliminary {
                    FilingRowLink(filingID: filing.id) {
                        RelatedRow(
                            title: Titles.title(for: filing, language: language),
                            detail: PageCopy.preliminaryDetail(filing.filedOn, report: page.filing.filedOn, language))
                    }
                    .listRowBackground(Theme.surface)
                }
                if let notice = page.investorEvent {
                    RelatedLinkRow(
                        title: Titles.title(for: notice, language: language),
                        detail: PageCopy.investorEventDetail(notice.filedOn, page.company.regulator, language),
                        url: URL(string: notice.sourceURL))
                }
            } header: {
                SectionTitle(PageCopy.related(language))
            }
        }
    }
}

/// One figure as board 15 lays it out: the name on the left; the quarter's value shortened
/// and, under it, the change from the same quarter a year earlier in sign and word, or why
/// there is none, on the right. At accessibility sizes the three lines stack. VoiceOver reads
/// the exact value.
private struct QuarterFigureRowView: View {
    @Environment(\.language) private var language
    @Environment(\.dynamicTypeSize) private var typeSize
    let row: QuarterFigureRow
    let currency: String

    var body: some View {
        Group {
            if typeSize.isAccessibilitySize {
                VStack(alignment: .leading, spacing: 4) {
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
        .padding(.vertical, 4)
        .frame(maxWidth: .infinity, minHeight: Theme.minTarget, alignment: .leading)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(spoken)
    }

    private var name: some View {
        Text(words: row.metric.name(language))
            .font(.body)
            .foregroundStyle(Theme.muted)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func value(alignment: HorizontalAlignment) -> some View {
        let text: TextAlignment = alignment == .trailing ? .trailing : .leading
        return VStack(alignment: alignment, spacing: 2) {
            Text(words: PageCopy.shortened(row.current, currency: currency, language))
                .font(.body.weight(.semibold))
                .monospacedDigit()
                .foregroundStyle(Theme.ink)
                .multilineTextAlignment(text)
                .fixedSize(horizontal: false, vertical: true)
            PhraseLines(phrases: Self.halves(changeLine), alignment: alignment)
                .font(.footnote)
                .monospacedDigit()
                .foregroundStyle(isResult ? Theme.ink : Theme.muted)
                .multilineTextAlignment(text)
        }
    }

    /// The line in two phrases of about equal length, split at a space, so when it wraps no
    /// word sits alone on the second line (`작년 숫자가 0 이하라` / `증가율을 계산하지 않아요`).
    static func halves(_ line: String) -> [String] {
        let words = line.split(separator: " ").map(String.init)
        guard words.count > 1 else { return [line] }
        let total = line.count
        let cut = (1..<words.count).min { a, b in
            abs(2 * words[..<a].joined(separator: " ").count - total)
                < abs(2 * words[..<b].joined(separator: " ").count - total)
        } ?? 1
        return [words[..<cut].joined(separator: " "), words[cut...].joined(separator: " ")]
    }

    private var isResult: Bool {
        if case .result = row.comparison { return true }
        return false
    }

    private var changeLine: String {
        switch row.comparison {
        case .result(let change): Formatting.percentChange(change.percentChange, language: language)
        case .refusal(let refusal): PageCopy.refusal(refusal, language)
        }
    }

    private func exact(_ figure: QuarterFigure) -> String {
        PageCopy.exact(figure.value, unit: figure.unit, currency: figure.currency ?? currency, language)
    }

    private var spoken: String {
        var parts = [row.metric.name(language), exact(row.current)]
        switch row.comparison {
        case .result(let change):
            parts.append(Formatting.percentChangeSpoken(change.percentChange, language: language))
        case .refusal(let refusal):
            parts.append(PageCopy.refusal(refusal, language))
        }
        return parts.joined(separator: ", ")
    }
}

/// A related filing's title with one muted line under it.
private struct RelatedRow: View {
    let title: String
    let detail: String

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(words: title)
                .font(.body)
                .foregroundStyle(Theme.ink)
                .fixedSize(horizontal: false, vertical: true)
            Text(words: detail)
                .font(.footnote)
                .monospacedDigit()
                .foregroundStyle(Theme.muted)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.vertical, 4)
        .frame(maxWidth: .infinity, minHeight: Theme.minTarget, alignment: .leading)
        .accessibilityElement(children: .combine)
    }
}

/// A related document that opens outside the app, marked as such.
private struct RelatedLinkRow: View {
    @Environment(\.openURL) private var openURL
    let title: String
    let detail: String
    let url: URL?

    var body: some View {
        if let url {
            Button {
                openURL(url)
            } label: {
                HStack(spacing: 12) {
                    RelatedRow(title: title, detail: detail)
                    Image(systemName: "arrow.up.right.square")
                        .foregroundStyle(Theme.pine)
                        .accessibilityHidden(true)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .listRowBackground(Theme.surface)
            .accessibilityElement(children: .combine)
            .accessibilityAddTraits(.isLink)
            .accessibilityIdentifier("investor-event")
        }
    }
}
