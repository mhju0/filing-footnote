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
                    NavigationLink(value: Route.quarterFigure(page.filing.id, row.metric)) {
                        QuarterFigureRowView(row: row, currency: page.currency)
                    }
                    .listRowBackground(Theme.surface)
                    .accessibilityIdentifier("quarter-\(row.metric.rawValue)")
                }
            } header: {
                SectionTitle(PageCopy.quarterFigures(start: period.start, end: period.end, language))
                    .accessibilityIdentifier("quarter-figures-header")
            } footer: {
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
        .accessibilityLabel(PageCopy.quarterSpoken(row, currency: currency, language))
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
            PhraseLines(phrases: isResult ? [changeLine] : Self.halves(changeLine), alignment: alignment)
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
}

struct QuarterFigureView: View {
    @Environment(\.language) private var language
    @Environment(\.navigate) private var navigate
    let store: BundleStore
    let page: QuarterPage
    let row: QuarterFigureRow

    var body: some View {
        List {
            ScreenHeader(
                context: Titles.name(of: page.company, language: language) + Copy.dot + PageCopy.quarterLabel(row.current, language),
                title: row.metric.name(language))
            headline
            if let prior = row.prior {
                Section {
                    compactRow(row.current)
                    compactRow(prior)
                } header: {
                    SectionTitle(change == nil ? language("분기별 금액", "Quarter figures")
                                 : language("같은 분기 비교", "Compare the same quarter"))
                } footer: {
                    if let basis = PageCopy.basisName(row.current.basis, language) {
                        SectionNote(text: basis + Copy.dot + PageCopy.unitName(row.current.unit, language))
                    }
                }
            }
            SourceSection(source: page.source, linkTitle: sourceTitle)
            Section {
                DisclosureGroup {
                    exactRow(row.current)
                    if let prior = row.prior { exactRow(prior) }
                    if let change { calculation(change) }
                } label: {
                    Text(words: change == nil ? language("정확한 금액", "Exact figures")
                         : language("정확한 금액과 계산식", "Exact figures and calculation"))
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(minHeight: Theme.minTarget, alignment: .leading)
                }
                .tint(Theme.pine)
                .listRowBackground(Theme.surface)
                .accessibilityIdentifier("quarter-calculation-details")
                if let entry = store.glossaryEntry(termKey: Glossary.key(for: row.metric), language: language) {
                    DisclosureGroup {
                        Text(words: entry.plain)
                            .fixedSize(horizontal: false, vertical: true)
                    } label: {
                        Text(words: language("용어 뜻", "What it means"))
                            .fixedSize(horizontal: false, vertical: true)
                            .frame(minHeight: Theme.minTarget, alignment: .leading)
                    }
                    .tint(Theme.pine)
                    .listRowBackground(Theme.surface)
                }
            }
            if let route = Routes.figure(store, companyID: page.company.id, metric: row.metric) {
                Section {
                    LinkRow(title: language("연간 수치 보기", "See annual figures")) { navigate(route) }
                }
            }
        }
        .groupedScreen()
        .screenTitle(row.metric.name(language))
        .languageToolbar()
        .accessibilityIdentifier("quarter-figure-page")
    }

    private var headline: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(words: PageCopy.shortened(row.current, currency: page.currency, language))
                .font(.largeTitle.bold())
                .monospacedDigit()
                .foregroundStyle(Theme.ink)
                .fixedSize(horizontal: false, vertical: true)
            switch row.comparison {
            case .result(let change):
                if let prior = row.prior {
                    let rate = Formatting.percentChange(change.percentChange, language: language)
                    PhraseLines(phrases: [rate, language("작년 같은 분기 대비", "vs. \(PageCopy.quarterLabel(prior, language))")])
                        .font(.subheadline.weight(.semibold))
                        .monospacedDigit()
                        .foregroundStyle(Theme.ink)
                }
            case .refusal(let refusal):
                Text(words: PageCopy.refusal(refusal, language))
                    .font(.subheadline)
                    .foregroundStyle(Theme.ink)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.vertical, 10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .listRowBackground(Theme.tint)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(PageCopy.quarterSpoken(row, currency: page.currency, language))
        .accessibilityIdentifier("quarter-figure-change")
    }

    private var change: QuarterChange? {
        guard case .result(let change) = row.comparison else { return nil }
        return change
    }

    private var sourceTitle: String {
        let site = page.company.regulator.rawValue
        return language("\(site)에서 분기 보고서 원문 보기", "Open the quarterly report on \(site)")
    }

    private func compactRow(_ figure: QuarterFigure) -> some View {
        let period = PageCopy.quarterLabel(figure, language)
        return FactRow(
            label: period,
            value: PageCopy.shortened(figure, currency: page.currency, language),
            spoken: period + ", " + exactValue(figure))
    }

    private func exactRow(_ figure: QuarterFigure) -> some View {
        FactRow(
            label: PageCopy.quarterLabel(figure, language),
            value: exactValue(figure),
            details: [Formatting.period(figure.periodStart, figure.periodEnd, language: language)])
    }

    private func exactValue(_ figure: QuarterFigure) -> String {
        PageCopy.exact(figure.value, unit: figure.unit, currency: figure.currency ?? page.currency, language)
    }

    private func calculation(_ change: QuarterChange) -> some View {
        FactRow(
            label: PageCopy.formula(language),
            value: Formatting.percent(change.percentChange),
            details: [language("(이번 분기 − 작년 같은 분기) ÷ 작년 같은 분기 × 100",
                               "(This quarter − same quarter last year) ÷ same quarter last year × 100"),
                      language("소수 셋째 자리에서 반올림했어요.", "Rounded to two decimal places.")])
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
