import FootnoteKit
import SwiftUI

/// An annual report at a glance (board 4): the one line, 무슨 사업, 무엇이 바뀌었나, 회사가
/// 꼽은 위험, then 핵심 숫자 for the report's year and the year before, then the original.
struct AnnualReportView: View {
    @Environment(\.language) private var language
    let page: AnnualPage

    var body: some View {
        ScrollViewReader { proxy in
            list.launchScroll(proxy)
        }
        .groupedScreen()
        .pageTitle(page.company)
        .languageToolbar()
        .accessibilityIdentifier("annual-page")
    }

    private var list: some View {
        List {
            PageHeader(filing: page.filing, dataAsOf: page.dataAsOf)
            summary
            if let year = page.fiscalYear, !page.rows.isEmpty {
                Section {
                    ForEach(page.rows) { row in
                        NavigationLink(value: Route.figure(page.company.id, row.metric.rawValue)) {
                            AnnualFigureRowView(row: row, fiscalYear: year)
                        }
                        .listRowBackground(Theme.surface)
                        .accessibilityIdentifier("figure-\(row.metric.rawValue)")
                    }
                    if let margin = page.margin {
                        MarginRowView(margin: margin)
                    }
                } header: {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(words: PageCopy.keyFigures(language))
                        Text(words: PageCopy.figuresBasis(
                            fiscalYear: year, basis: page.basis, currency: page.currency, language))
                            .font(.footnote)
                            .textCase(nil)
                    }
                } footer: {
                    if let note = PageCopy.notStated(page.notStated, language) {
                        SectionNote(text: note)
                    }
                }
                .id(PageScroll.numbers)
            }
            SourceSection(source: page.source)
        }
    }

    @ViewBuilder private var summary: some View {
        if page.summaryInReview(language) {
            Section {
                InReviewRow()
            } header: {
                Text(words: PageCopy.sentences(language))
            }
        } else {
            let oneLine = page.lines(.oneLine, language)
            if !oneLine.isEmpty {
                Section {
                    TintNote(text: oneLine.joined(separator: " "), emphasized: true)
                } footer: {
                    SectionNote(text: PageCopy.howWritten(language))
                }
            }
            ForEach(AnnualPage.sections, id: \.self) { section in
                let lines = page.lines(section, language)
                if !lines.isEmpty {
                    Section {
                        SentenceRows(lines: lines)
                    } header: {
                        Text(words: PageCopy.annualSections(section, language))
                    }
                }
            }
        }
    }
}

/// One metric: this year's value, last year's value, and the change or why there is none.
private struct AnnualFigureRowView: View {
    @Environment(\.language) private var language
    let row: AnnualFigureRow
    let fiscalYear: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(words: row.metric.name(language))
                .font(.body.weight(.semibold))
                .foregroundStyle(Theme.ink)
                .fixedSize(horizontal: false, vertical: true)
            yearLine(fiscalYear, row.current, emphasized: true)
            yearLine(fiscalYear - 1, row.prior, emphasized: false)
            if let change = changeLine {
                Text(words: change)
                    .font(.subheadline)
                    .monospacedDigit()
                    .foregroundStyle(Theme.ink)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if row.isRestated {
                Text(words: PageCopy.restatedNote(language))
                    .font(.footnote)
                    .foregroundStyle(Theme.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.vertical, 4)
        .frame(minHeight: Theme.minTarget)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(spoken)
    }

    private func yearLine(_ year: Int, _ figure: Figure?, emphasized: Bool) -> some View {
        FlowLayout(spacing: 8, lineSpacing: 2) {
            Text(words: PageCopy.fiscalYear(year, language))
                .font(.subheadline)
                .monospacedDigit()
                .foregroundStyle(Theme.muted)
                .fixedSize()
            Text(words: figure.map(value) ?? PageCopy.noFigure(language))
                .font(emphasized && figure != nil ? .body.weight(.semibold) : .body)
                .monospacedDigit()
                .foregroundStyle(figure == nil ? Theme.muted : Theme.ink)
                .fixedSize(horizontal: false, vertical: true)
            if figure?.isRestated == true {
                TagView(text: PageCopy.restatedTag(language), kind: .corrected)
            }
        }
    }

    private func value(_ figure: Figure) -> String {
        Formatting.stated(figure.value, unit: figure.unit, fallbackCurrency: figure.currency ?? "KRW", language: language)
            ?? Formatting.number(figure.value)
    }

    /// The change in sign and word, the refusal's approved title, or nothing when a year has
    /// no figure (the missing year already says so).
    private var changeLine: String? {
        switch row.comparison {
        case .result(let change)?: Formatting.percentChange(change.percentChange, language: language)
        case .refusal(let refusal)?: PageCopy.refusal(refusal, language)
        case nil: nil
        }
    }

    private var spoken: String {
        var parts = [row.metric.name(language)]
        for (year, figure) in [(fiscalYear, row.current), (fiscalYear - 1, row.prior)] {
            var part = PageCopy.fiscalYear(year, language) + " " + (figure.map(value) ?? PageCopy.noFigure(language))
            if figure?.isRestated == true { part += ", " + PageCopy.restatedTag(language) }
            parts.append(part)
        }
        switch row.comparison {
        case .result(let change)?:
            parts.append(Formatting.percentChangeSpoken(change.percentChange, language: language))
        case .refusal(let refusal)?:
            parts.append(PageCopy.refusal(refusal, language))
        case nil: break
        }
        if row.isRestated { parts.append(PageCopy.restatedNote(language)) }
        return parts.joined(separator: ", ")
    }
}

/// Operating margin, worked out from revenue and operating income for each year. A rate has
/// no direction word.
private struct MarginRowView: View {
    @Environment(\.language) private var language
    let margin: AnnualMarginRow

    var body: some View {
        FactRow(
            label: DerivedMetric.operatingMargin.name(language),
            value: line(margin.fiscalYear, margin.current),
            details: [line(margin.fiscalYear - 1, margin.prior), PageCopy.marginFormula(language)],
            layout: .split)
    }

    private func line(_ year: Int, _ comparison: Comparison<OperatingMargin>?) -> String {
        let value: String = switch comparison {
        case .result(let margin)?: Formatting.percent(margin.operatingMargin)
        case .refusal(let refusal)?: PageCopy.refusal(refusal, language)
        case nil: PageCopy.noFigure(language)
        }
        return PageCopy.fiscalYear(year, language) + " " + value
    }
}

/// One figure (DESIGN.md, Figure): its meaning from the glossary, every year in the bundle
/// as a list, then the latest change with its inputs and formula. The tap target of each annual row (I8 builds the
/// full screen with its meaning and the compare action).
struct FigureView: View {
    @Environment(\.language) private var language
    let store: BundleStore
    let history: FigureHistory

    var body: some View {
        List {
            if let entry = store.glossaryEntry(termKey: "metric_\(history.metric.rawValue)", language: language) {
                Section {
                    Text(words: entry.plain)
                        .font(.body)
                        .foregroundStyle(Theme.ink)
                        .fixedSize(horizontal: false, vertical: true)
                        .listRowBackground(Theme.surface)
                } header: {
                    Text(words: PageCopy.meaning(language))
                }
            }
            Section {
                ForEach(history.years, id: \.self) { figure in
                    FactRow(
                        label: PageCopy.fiscalYear(figure.fiscalYear, language), value: value(figure),
                        tag: figure.isRestated ? PageCopy.restatedTag(language) : nil)
                }
            } header: {
                Text(words: PageCopy.earlierYears(language))
            } footer: {
                if history.years.contains(where: \.isRestated) {
                    SectionNote(text: PageCopy.restatedNote(language))
                }
            }
            Section {
                calculation
            } header: {
                Text(words: PageCopy.calculation(language))
            }
        }
        .groupedScreen()
        .navigationTitle(history.metric.name(language))
        #if os(iOS)
        .navigationBarTitleDisplayMode(.inline)
        #endif
        .languageToolbar()
        .accessibilityIdentifier("figure-page")
    }

    @ViewBuilder private var calculation: some View {
        switch history.latestChange {
        case .result(let change)?:
            FactRow(label: PageCopy.fiscalYear(history.years[0].fiscalYear, language),
                    value: amount(change.currentValue, history.years[0]))
            FactRow(label: PageCopy.fiscalYear(history.years[1].fiscalYear, language),
                    value: amount(change.priorValue, history.years[1]))
            FactRow(
                label: PageCopy.growthFormula(language),
                value: Formatting.percentChange(change.percentChange, language: language),
                spoken: PageCopy.growthFormula(language) + ", "
                    + Formatting.percentChangeSpoken(change.percentChange, language: language))
        case .refusal(let refusal)?:
            VStack(alignment: .leading, spacing: 4) {
                Text(words: PageCopy.refusal(refusal, language))
                    .font(.body.weight(.semibold))
                    .foregroundStyle(Theme.ink)
                    .fixedSize(horizontal: false, vertical: true)
                if let body = PageCopy.refusalBody(refusal, language) {
                    Text(words: body)
                        .font(.subheadline)
                        .foregroundStyle(Theme.muted)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(.vertical, 4)
            .listRowBackground(Theme.surface)
            .accessibilityElement(children: .combine)
        case nil:
            Text(words: PageCopy.oneYearOnly(language))
                .font(.body)
                .foregroundStyle(Theme.muted)
                .listRowBackground(Theme.surface)
        }
    }

    private func value(_ figure: Figure) -> String {
        amount(figure.value, figure)
    }

    private func amount(_ value: Decimal, _ figure: Figure) -> String {
        Formatting.stated(value, unit: figure.unit, fallbackCurrency: figure.currency ?? history.company.currency,
                          language: language) ?? Formatting.number(value)
    }
}
