import FootnoteKit
import SwiftUI

/// An event filing's page (board 12A). The order is fixed for every type: header, the
/// outlook banner (outlook only), the sentences, the numbers, the original.
struct FilingPageView: View {
    @Environment(\.language) private var language
    let page: FilingPage
    let labels: FactLabels

    var body: some View {
        ScrollViewReader { proxy in
            list.launchScroll(proxy)
        }
        .groupedScreen()
        .pageTitle(page.company)
        .languageToolbar()
        .accessibilityIdentifier("filing-page")
    }

    private var list: some View {
        List {
            PageHeader(filing: page.filing, dataAsOf: page.dataAsOf)
            if page.isOutlook {
                Section { TintNote(text: PageCopy.outlookBanner(language)) }
            }
            sentences
            if let status = page.clarificationStatus {
                Section {
                    FactRow(label: PageCopy.status(language), value: PageCopy.statusValue(status, language))
                } footer: {
                    SectionNote(text: PageCopy.statusNote(status, language))
                }
            }
            if page.outlookHasNoFigures {
                Section(PageCopy.numbers(language)) {
                    Text(words: PageCopy.outlookWithoutFigures(language))
                        .font(.body)
                        .foregroundStyle(Theme.muted)
                        .fixedSize(horizontal: false, vertical: true)
                        .listRowBackground(Theme.surface)
                }
            }
            ForEach(Array(page.blocks.enumerated()), id: \.offset) { index, block in
                FactBlockSection(
                    block: block, currency: page.company.currency, labels: labels, isFirst: index == 0)
                    .id(index == 0 ? PageScroll.numbers : "block-\(index)")
            }
            SourceSection(source: page.source)
        }
    }

    @ViewBuilder private var sentences: some View {
        let lines = page.summaryLines(language)
        Section {
            if lines.isEmpty {
                InReviewRow()
            } else {
                SentenceRows(lines: lines)
            }
        } header: {
            Text(words: PageCopy.sentences(language))
        } footer: {
            if !lines.isEmpty { SectionNote(text: PageCopy.howWritten(language)) }
        }
    }
}

/// One group of the numbers section. The first group carries the section's name.
private struct FactBlockSection: View {
    @Environment(\.language) private var language
    let block: FactBlock
    let currency: String
    let labels: FactLabels
    let isFirst: Bool

    var body: some View {
        switch block {
        case .comparison(let block):
            Section {
                ForEach(block.rows, id: \.self) { row in comparedRow(row, kind: block.kind) }
            } header: {
                header(PageCopy.comparisonHeading(block, language))
            } footer: {
                SectionNote(text: PageCopy.comparisonNote(block, language))
            }
        case .outlook(let block):
            Section {
                ForEach(block.items, id: \.self) { item in outlookRow(item, year: block.year) }
            } header: {
                header(PageCopy.outlookHeading(
                    year: block.year, salesTargets: block.items.allSatisfy(\.isSalesTarget), language))
            }
        case .rows(let rows):
            Section {
                ForEach(rows, id: \.self) { row in
                    FactRow(label: name(row), value: value(row.value))
                }
            } header: {
                if isFirst { Text(words: PageCopy.numbers(language)) }
            }
        }
    }

    /// The section name above the first group, then the group's own heading.
    private func header(_ text: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            if isFirst { Text(words: PageCopy.numbers(language)) }
            Text(words: text)
                .font(.footnote.weight(isFirst ? .regular : .semibold))
                .textCase(nil)
        }
    }

    private func stated(_ value: Decimal, unit: String?) -> String {
        Formatting.stated(value, unit: unit, fallbackCurrency: currency, language: language)
            ?? Formatting.number(value) + (unit.map { " \($0)" } ?? "")
    }

    private func comparedRow(_ row: ComparedValue, kind: ComparisonBlock.Kind) -> some View {
        var details: [String] = []
        var spoken = [row.name.text(language), stated(row.current, unit: row.unit)]
        if let base = row.base {
            let line = PageCopy.baseValue(stated(base, unit: row.unit), kind: kind, language)
            details.append(line)
            spoken.append(line)
        }
        if let change = row.change {
            details.append(Formatting.percentChange(change, language: language))
            spoken.append(Formatting.percentChangeSpoken(change, language: language))
        } else if row.baseNotPositive {
            details.append(PageCopy.baseNotPositive(language))
            spoken.append(PageCopy.baseNotPositive(language))
        }
        return FactRow(
            label: row.name.text(language), value: stated(row.current, unit: row.unit),
            details: details, spoken: spoken.joined(separator: ", "), layout: .split)
    }

    private func outlookRow(_ item: OutlookItem, year: String?) -> some View {
        let details = item.before.map {
            [PageCopy.beforeCorrection(stated($0, unit: item.unit), language)]
        } ?? []
        return FactRow(
            label: item.name(language, blockYear: year), value: stated(item.value, unit: item.unit),
            details: details, layout: .split)
    }

    /// The plain name, else the contract's name for the fact.
    private func name(_ row: FactRowValue) -> String {
        row.name?.text(language) ?? labels.label(origin: row.origin, language) ?? row.origin
    }

    private func value(_ value: FactRowValue.Value) -> String {
        switch value {
        case .stated(let amount, let unit): stated(amount, unit: unit)
        case .date(let date): Formatting.fullDate(date, language: language)
        case .dateRange(let start, let end):
            Formatting.fullDate(start, language: language) + "–" + Formatting.fullDate(end, language: language)
        case .text(let text): text
        }
    }
}

extension View {
    /// The navigation title of a page under a company. iPhone shows the company in the back
    /// button (board 12A), so the bar title stays empty; the Mac names the company.
    func pageTitle(_ company: Company) -> some View {
        modifier(PageTitle(company: company))
    }
}

private struct PageTitle: ViewModifier {
    @Environment(\.language) private var language
    let company: Company

    func body(content: Content) -> some View {
        #if os(iOS)
        content
            .navigationTitle("")
            .navigationBarTitleDisplayMode(.inline)
        #else
        content.navigationTitle(Titles.name(of: company, language: language))
        #endif
    }
}
