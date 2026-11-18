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
                        NavigationLink(value: Route.figure(page.company.id, row.metric.rawValue, year)) {
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
                    VStack(alignment: .leading, spacing: 6) {
                        if let note = PageCopy.notStated(page.notStated, language) {
                            SectionNote(text: note)
                        }
                        SectionNote(text: PageCopy.amountsShortened(language))
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
            YearValueLines(lines: [
                yearValue(fiscalYear, row.current, emphasized: true),
                yearValue(fiscalYear - 1, row.prior, emphasized: false),
            ])
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

    private func yearValue(_ year: Int, _ figure: Figure?, emphasized: Bool) -> YearValueLines.Line {
        YearValueLines.Line(
            year: PageCopy.fiscalYear(year, language),
            value: figure.map { value($0, precision: .compact) } ?? PageCopy.noFigure(language),
            emphasized: emphasized && figure != nil,
            missing: figure == nil,
            tag: figure?.isRestated == true ? PageCopy.restatedTag(language) : nil)
    }

    /// Shortened on screen; VoiceOver reads the exact value.
    private func value(_ figure: Figure, precision: AmountPrecision = .exact) -> String {
        Formatting.stated(figure.value, unit: figure.unit, fallbackCurrency: figure.currency ?? "KRW",
                          language: language, precision: precision)
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
            var part = PageCopy.fiscalYear(year, language) + " "
                + (figure.map { value($0) } ?? PageCopy.noFigure(language))
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
        VStack(alignment: .leading, spacing: 4) {
            Text(words: DerivedMetric.operatingMargin.name(language))
                .font(.body.weight(.semibold))
                .foregroundStyle(Theme.ink)
                .fixedSize(horizontal: false, vertical: true)
            YearValueLines(lines: [
                line(margin.fiscalYear, margin.current, emphasized: true),
                line(margin.fiscalYear - 1, margin.prior, emphasized: false),
            ])
            Text(words: PageCopy.marginFormula(language))
                .font(.footnote)
                .foregroundStyle(Theme.muted)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.vertical, 4)
        .frame(maxWidth: .infinity, minHeight: Theme.minTarget, alignment: .leading)
        .listRowBackground(Theme.surface)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(
            ([DerivedMetric.operatingMargin.name(language)]
                + [margin.fiscalYear, margin.fiscalYear - 1].map { spokenLine($0) }
                + [PageCopy.marginFormula(language)]).joined(separator: ", "))
    }

    private func text(_ comparison: Comparison<OperatingMargin>?) -> String? {
        switch comparison {
        case .result(let margin)?: Formatting.percent(margin.operatingMargin)
        case .refusal(let refusal)?: PageCopy.refusal(refusal, language)
        case nil: nil
        }
    }

    private func comparison(_ year: Int) -> Comparison<OperatingMargin>? {
        year == margin.fiscalYear ? margin.current : margin.prior
    }

    private func line(_ year: Int, _ value: Comparison<OperatingMargin>?, emphasized: Bool) -> YearValueLines.Line {
        let shown = text(value)
        let isResult = if case .result? = value { true } else { false }
        return YearValueLines.Line(
            year: PageCopy.fiscalYear(year, language),
            value: shown ?? PageCopy.noFigure(language),
            emphasized: emphasized && isResult,
            missing: !isResult,
            tag: nil)
    }

    private func spokenLine(_ year: Int) -> String {
        PageCopy.fiscalYear(year, language) + " " + (text(comparison(year)) ?? PageCopy.noFigure(language))
    }
}

/// A year label and its value per line. The labels form one column so the values line up and
/// a long value wraps inside its own column; at accessibility sizes each value flows under
/// its label.
private struct YearValueLines: View {
    struct Line {
        let year: String
        let value: String
        let emphasized: Bool
        let missing: Bool
        let tag: String?
    }

    @Environment(\.dynamicTypeSize) private var typeSize
    let lines: [Line]

    var body: some View {
        if typeSize.isAccessibilitySize {
            VStack(alignment: .leading, spacing: 4) {
                ForEach(Array(lines.enumerated()), id: \.offset) { _, line in
                    FlowLayout(spacing: 8, lineSpacing: 2) {
                        yearText(line)
                        valueText(line)
                        tagView(line)
                    }
                }
            }
        } else {
            Grid(alignment: .leadingFirstTextBaseline, horizontalSpacing: 8, verticalSpacing: 4) {
                ForEach(Array(lines.enumerated()), id: \.offset) { _, line in
                    GridRow {
                        yearText(line)
                        HStack(alignment: .firstTextBaseline, spacing: 6) {
                            valueText(line)
                            tagView(line)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
        }
    }

    private func yearText(_ line: Line) -> some View {
        Text(words: line.year)
            .font(.subheadline)
            .monospacedDigit()
            .foregroundStyle(Theme.muted)
            .fixedSize()
    }

    private func valueText(_ line: Line) -> some View {
        Text(words: line.value)
            .font(line.emphasized ? .body.weight(.semibold) : .body)
            .monospacedDigit()
            .foregroundStyle(line.missing ? Theme.muted : Theme.ink)
            .fixedSize(horizontal: false, vertical: true)
    }

    @ViewBuilder private func tagView(_ line: Line) -> some View {
        if let tag = line.tag { TagView(text: tag, kind: .corrected) }
    }
}
