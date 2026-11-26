import FootnoteKit
import SwiftUI

/// Where a row leads: pushed on a `NavigationStack`, or selected into the split view's
/// detail column.
enum Route: Hashable {
    case company(String)
    case filing(String)
    case quarterFigure(String, ReportedMetric)
    /// A company id, a reported metric (`revenue`) and the fiscal year of the report it was
    /// opened from: the figure screen.
    case figure(String, String, Int)
    /// The same company, metric and year: compare with last year (board 6) and its
    /// calculation (board 6b).
    case yearCompare(String, String, Int)
    case yearCalculation(String, String, Int)
    /// A company, the company picked, the metric, the measure (`growth_rate`; nil when none
    /// was chosen) and the year: compare with another company (board 7).
    case companyCompare(CompanyCompareRoute)
    case companyCalculation(CompanyCompareRoute)
    /// The glossary, scrolled to and marking one entry (`metric_revenue`) when given.
    case glossary(String?)
    /// A company and a question asked about it (D99).
    case answer(String, QuestionIntent)
}

struct CompanyCompareRoute: Hashable {
    let companyID: String
    let peerID: String
    let metric: String?
    let measure: String?
    let fiscalYear: Int
}

/// Pushes a route on the stack the view is in; the picker sheet uses it after it closes.
struct NavigateAction {
    let push: @MainActor (Route) -> Void

    @MainActor func callAsFunction(_ route: Route) { push(route) }
}

extension EnvironmentValues {
    @Entry var navigate = NavigateAction { _ in }
}

extension EnvironmentValues {
    /// Set in the split view: rows then select a filing for the detail column instead of
    /// pushing it.
    @Entry var filingSelection: Binding<String?>? = nil
    /// Set in the split view's glossary: rows then select a term for the detail column.
    @Entry var glossarySelection: Binding<String?>? = nil
}

/// A row that opens a filing: a `NavigationLink` on iPhone, a selection on iPad and Mac.
struct FilingRowLink<Label: View>: View {
    @Environment(\.filingSelection) private var selection
    let filingID: String
    @ViewBuilder let label: Label

    var body: some View {
        SelectableRow(value: filingID, selection: selection, route: .filing(filingID)) { label }
    }
}

/// A row that selects `value` into the split view's detail column, or pushes `route` when
/// there is no split view. iPad rows are buttons; Mac rows are tagged so the enclosing
/// `SelectionList` moves the selection with the arrow keys.
struct SelectableRow<Label: View>: View {
    let value: String
    let selection: Binding<String?>?
    let route: Route
    /// Set inside the selection tag, so it never wraps the tagged row.
    var identifier: String?
    @ViewBuilder let label: Label

    var body: some View {
        if let selection {
            let isSelected = selection.wrappedValue == value
            #if os(macOS)
            // The selection tag goes last, so no wrapper can hide it from the list; the id
            // lets a list scroll to the row.
            label
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
                .listRowBackground(isSelected ? Theme.tint : Theme.surface)
                .accessibilityAddTraits(isSelected ? .isSelected : [])
                .accessibilityIdentifier(identifier ?? value)
                .id(value)
                .tag(value)
            #else
            Button {
                selection.wrappedValue = value
            } label: {
                HStack(spacing: 12) {
                    label.frame(maxWidth: .infinity, alignment: .leading)
                    Chevron()
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .listRowBackground(isSelected ? Theme.tint : Theme.surface)
            .accessibilityAddTraits(isSelected ? .isSelected : [])
            .accessibilityIdentifier(identifier ?? value)
            .id(value)
            #endif
        } else {
            NavigationLink(value: route) { label }
                .listRowBackground(Theme.surface)
                .accessibilityIdentifier(identifier ?? value)
        }
    }
}

/// A list whose tagged rows the Mac selects with the arrow keys; Return (or a double click)
/// selects the focused row too. iPhone and iPad get a plain list: their rows are buttons.
struct SelectionList<Content: View>: View {
    let selection: Binding<String?>?
    @ViewBuilder let content: Content

    var body: some View {
        #if os(macOS)
        if let selection {
            List(selection: selection) { content }
                .contextMenu(forSelectionType: String.self) { _ in
                    EmptyView()
                } primaryAction: { values in
                    if let value = values.first { selection.wrappedValue = value }
                }
        } else {
            List { content }
        }
        #else
        List { content }
        #endif
    }
}

/// The tags and date above a filing's title.
struct FilingMeta: View {
    @Environment(\.language) private var language
    let filing: Filing
    let dataAsOf: CivilDate
    var showsCategory = true
    /// False under a day heading that already supplies the date.
    var showsDate = true

    var body: some View {
        FlowLayout(spacing: 6, lineSpacing: 4) {
            if showsCategory {
                TagView(text: filing.category.label(language), kind: .category, symbol: filing.category.symbol)
            }
            if filing.isCorrected {
                TagView(text: language("정정됨", "Corrected"), kind: .corrected)
            }
            if Freshness.isNew(filing, dataAsOf: dataAsOf) {
                TagView(text: language("새 공시", "New"), kind: .new)
            }
            if showsDate {
                Text(words: Copy.unbroken(Formatting.monthDay(filing.filedOn, language: language)))
                    .font(.footnote)
                    .monospacedDigit()
                    .foregroundStyle(Theme.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

/// An event filing in a list: tag, date, title, and under it, when given, the first line of
/// the filing's approved summary (D106; DESIGN.md, Screens).
struct FilingRow: View {
    @Environment(\.language) private var language
    let filing: Filing
    let dataAsOf: CivilDate
    var companyName: String?
    var showsDate = true
    /// Only ever an approved summary line; nil shows no second line.
    var secondLine: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if let companyName {
                Text(words: companyName)
                    .font(.headline)
                    .foregroundStyle(Theme.ink)
                    .fixedSize(horizontal: false, vertical: true)
            }
            FilingMeta(filing: filing, dataAsOf: dataAsOf, showsDate: showsDate)
            Text(words: Titles.title(for: filing, language: language))
                .font(.body)
                .foregroundStyle(Theme.ink)
                .multilineTextAlignment(.leading)
                .fixedSize(horizontal: false, vertical: true)
            if let secondLine {
                Text(words: secondLine)
                    .font(.subheadline)
                    .foregroundStyle(Theme.muted)
                    .multilineTextAlignment(.leading)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.vertical, 6)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(
            [Self.spoken(filing, dataAsOf: dataAsOf, companyName: companyName, language), secondLine]
                .compactMap { $0 }.joined(separator: ", "))
    }

    static func spoken(_ filing: Filing, dataAsOf: CivilDate, companyName: String?, _ language: Language) -> String {
        var parts: [String] = []
        if let companyName { parts.append(companyName) }
        parts.append(filing.category.label(language))
        if filing.isCorrected { parts.append(language("정정됨", "Corrected")) }
        if Freshness.isNew(filing, dataAsOf: dataAsOf) { parts.append(language("새 공시", "New")) }
        parts.append(Formatting.fullDate(filing.filedOn, language: language))
        parts.append(Titles.title(for: filing, language: language))
        return parts.joined(separator: ", ")
    }
}

/// The newest quarterly report pinned above the annual reports (board 14), with its revenue
/// against the same quarter a year earlier.
struct QuarterRow: View {
    @Environment(\.language) private var language
    let report: QuarterReport
    let company: Company
    let dataAsOf: CivilDate

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if isNew || report.filing.isCorrected {
                FilingMeta(filing: report.filing, dataAsOf: dataAsOf, showsCategory: false)
            }
            Text(words: Titles.title(for: report.filing, language: language))
                .font(.body)
                .foregroundStyle(Theme.ink)
                .fixedSize(horizontal: false, vertical: true)
            if let line = Copy.quarterRevenueLine(report, currency: company.currency, language) {
                Text(words: line)
                    .font(.footnote)
                    .monospacedDigit()
                    .foregroundStyle(Theme.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.vertical, 6)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(spoken)
    }

    private var isNew: Bool { Freshness.isNew(report.filing, dataAsOf: dataAsOf) }

    private var spoken: String {
        var parts = [Titles.title(for: report.filing, language: language)]
        if isNew { parts.append(language("새 공시", "New")) }
        if report.filing.isCorrected { parts.append(language("정정됨", "Corrected")) }
        if let figure = Copy.quarterRevenueSpoken(report, currency: company.currency, language) {
            parts.append(figure)
        }
        return parts.joined(separator: ", ")
    }
}

/// An annual report pinned above the filings, with its one figure.
struct PeriodicRow: View {
    @Environment(\.language) private var language
    let report: PeriodicReport
    let company: Company
    let dataAsOf: CivilDate

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if isNew || report.filing.isCorrected {
                FilingMeta(filing: report.filing, dataAsOf: dataAsOf, showsCategory: false)
            }
            Text(words: Titles.title(for: report.filing, language: language))
                .font(.body)
                .foregroundStyle(Theme.ink)
                .fixedSize(horizontal: false, vertical: true)
            if let line = Copy.revenueLine(report, currency: company.currency, language) {
                FlowLayout {
                    Text(words: line)
                        .font(.footnote)
                        .monospacedDigit()
                        .foregroundStyle(Theme.muted)
                        .fixedSize(horizontal: false, vertical: true)
                    if !report.restated.isEmpty {
                        TagView(text: language("정정됨", "Restated"), kind: .corrected)
                    }
                }
            }
            if let note = Copy.restatedNote(report, language) {
                Text(words: note)
                    .font(.footnote)
                    .foregroundStyle(Theme.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let note = Copy.fiscalYearEndsNote(report, language) {
                Text(words: note)
                    .font(.footnote)
                    .foregroundStyle(Theme.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.vertical, 6)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(spoken)
    }

    private var isNew: Bool { Freshness.isNew(report.filing, dataAsOf: dataAsOf) }

    private var spoken: String {
        var parts = [Titles.title(for: report.filing, language: language)]
        if isNew { parts.append(language("새 공시", "New")) }
        if report.filing.isCorrected { parts.append(language("정정됨", "Corrected")) }
        if let figure = Copy.revenueSpoken(report, currency: company.currency, language) {
            parts.append(figure)
        }
        if let note = Copy.restatedNote(report, language) {
            parts.append(language("정정됨", "Restated") + ". " + note)
        }
        if let note = Copy.fiscalYearEndsNote(report, language) { parts.append(note) }
        return parts.joined(separator: ", ")
    }
}
