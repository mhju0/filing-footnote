import FootnoteKit
import SwiftUI

/// An event filing's page (board 12A). The order is fixed for every type: header, the
/// outlook banner (outlook only), the sentences, the numbers, the original.
struct FilingPageView: View {
    @Environment(\.language) private var language
    let store: BundleStore
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
                Section {
                    Text(words: PageCopy.outlookWithoutFigures(language))
                        .font(.body)
                        .foregroundStyle(Theme.muted)
                        .fixedSize(horizontal: false, vertical: true)
                        .listRowBackground(Theme.surface)
                } header: {
                    SectionTitle(PageCopy.numbers(language))
                }
            }
            ForEach(Array(page.blocks.enumerated()), id: \.offset) { index, block in
                FactBlockSection(
                    block: block, currency: page.company.currency, labels: labels, isFirst: index == 0)
                    .id(index == 0 ? PageScroll.numbers : "block-\(index)")
            }
            if hasAmounts {
                Section {
                    SectionNote(text: PageCopy.amountsShortened(language))
                        .listRowBackground(Theme.surface)
                }
            }
            SourceSection(source: page.source)
            GlossaryLinkSection(store: store, category: page.filing.category)
            PageEndMarker()
        }
    }

    /// Whether any number on the page is a money amount, the only kind that is shortened.
    private var hasAmounts: Bool {
        let units: [String?] = page.blocks.flatMap { block -> [String?] in
            switch block {
            case .comparison(let block): block.rows.map(\.unit)
            case .outlook(let block): block.items.map(\.unit)
            case .rows(let rows): rows.compactMap {
                if case .stated(_, let unit) = $0.value { unit } else { nil }
            }
            }
        }
        return units.contains {
            if case .money? = StatedUnit($0, fallbackCurrency: page.company.currency) { true } else { false }
        }
    }

    @ViewBuilder private var sentences: some View {
        let lines = page.summaryLines(language)
        Section {
            if lines.isEmpty {
                InReviewRow()
            } else {
                SourcedSentenceRows(lines: page.sourcedSummaryLines(language), filing: page.filing)
            }
        } header: {
            SectionTitle(PageCopy.sentences(language))
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
                ForEach(rows, id: \.self) { row in factRow(row) }
            } header: {
                if isFirst { SectionTitle(PageCopy.numbers(language)) }
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
        .foregroundStyle(Theme.muted)
    }

    /// A value in its stated unit; money in the company page's compact form unless `exact`.
    private func stated(_ value: Decimal, unit: String?, precision: AmountPrecision = .compact) -> String {
        Formatting.stated(value, unit: unit, fallbackCurrency: currency, language: language, precision: precision)
            ?? Formatting.number(value) + (unit.map { " \($0)" } ?? "")
    }

    /// The exact form of a value, when it differs from the shortened one.
    private func exact(_ value: Decimal, unit: String?) -> String? {
        let full = stated(value, unit: unit, precision: .exact)
        return full == stated(value, unit: unit) ? nil : full
    }

    private func comparedRow(_ row: ComparedValue, kind: ComparisonBlock.Kind) -> some View {
        var details: [String] = []
        var spoken = [row.name.text(language), stated(row.current, unit: row.unit, precision: .exact)]
        var exactLines = exact(row.current, unit: row.unit).map { [PageCopy.exactValue($0, language)] } ?? []
        if let base = row.base {
            details.append(PageCopy.baseValue(stated(base, unit: row.unit), kind: kind, language))
            spoken.append(PageCopy.baseValue(stated(base, unit: row.unit, precision: .exact), kind: kind, language))
            if let full = exact(base, unit: row.unit) {
                exactLines.append(PageCopy.baseValue(full, kind: kind, language))
            }
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
            details: details, spoken: spoken.joined(separator: ", "), exact: exactLines)
    }

    private func outlookRow(_ item: OutlookItem, year: String?) -> some View {
        let label = item.name(language, blockYear: year)
        var details: [String] = []
        var spoken = [label, stated(item.value, unit: item.unit, precision: .exact)]
        var exactLines = exact(item.value, unit: item.unit).map { [PageCopy.exactValue($0, language)] } ?? []
        if let before = item.before {
            details.append(PageCopy.beforeCorrection(stated(before, unit: item.unit), language))
            spoken.append(PageCopy.beforeCorrection(stated(before, unit: item.unit, precision: .exact), language))
            if let full = exact(before, unit: item.unit) {
                exactLines.append(PageCopy.beforeCorrection(full, language))
            }
        }
        return FactRow(
            label: label, value: stated(item.value, unit: item.unit), details: details,
            spoken: spoken.joined(separator: ", "), exact: exactLines)
    }

    private func factRow(_ row: FactRowValue) -> some View {
        let label = name(row)
        guard case .stated(let amount, let unit) = row.value, let full = exact(amount, unit: unit) else {
            return FactRow(label: label, value: value(row.value))
        }
        return FactRow(
            label: label, value: value(row.value), spoken: label + ", " + full,
            exact: [PageCopy.exactValue(full, language)])
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
