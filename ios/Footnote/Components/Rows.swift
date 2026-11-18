import FootnoteKit
import SwiftUI

/// Where a row leads: pushed on a `NavigationStack`, or selected into the split view's
/// detail column.
enum Route: Hashable {
    case company(String)
    case filing(String)
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
    case glossary
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
}

/// A row that opens a filing: a `NavigationLink` on iPhone, a selection on iPad and Mac.
struct FilingRowLink<Label: View>: View {
    @Environment(\.filingSelection) private var selection
    let filingID: String
    @ViewBuilder let label: Label

    var body: some View {
        if let selection {
            let isSelected = selection.wrappedValue == filingID
            Button {
                selection.wrappedValue = filingID
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
        } else {
            NavigationLink(value: Route.filing(filingID)) { label }
                .listRowBackground(Theme.surface)
        }
    }
}

/// The tags and date above a filing's title.
struct FilingMeta: View {
    @Environment(\.language) private var language
    let filing: Filing
    let dataAsOf: CivilDate
    var showsCategory = true
    var companyName: String?

    var body: some View {
        FlowLayout(spacing: 6, lineSpacing: 4) {
            if showsCategory {
                TagView(text: filing.category.label(language), kind: .category)
            }
            if filing.isCorrected {
                TagView(text: language("정정됨", "Corrected"), kind: .corrected)
            }
            if Freshness.isNew(filing.filedOn, dataAsOf: dataAsOf) {
                TagView(text: language("새 공시", "New"), kind: .new)
            }
            Text(words: dateLine)
                .font(.footnote)
                .monospacedDigit()
                .foregroundStyle(Theme.muted)
                .fixedSize()
        }
    }

    private var dateLine: String {
        let day = Formatting.monthDay(filing.filedOn, language: language)
        guard let companyName else { return day }
        return "\(companyName) · \(day)"
    }
}

/// An event filing in a list: tag, date, title. No preview line (DESIGN.md, Screens).
struct FilingRow: View {
    @Environment(\.language) private var language
    let filing: Filing
    let dataAsOf: CivilDate
    var companyName: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            FilingMeta(filing: filing, dataAsOf: dataAsOf, companyName: companyName)
            Text(words: Titles.title(for: filing, language: language))
                .font(.body)
                .foregroundStyle(Theme.ink)
                .multilineTextAlignment(.leading)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.vertical, 6)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Self.spoken(filing, dataAsOf: dataAsOf, companyName: companyName, language))
    }

    static func spoken(_ filing: Filing, dataAsOf: CivilDate, companyName: String?, _ language: Language) -> String {
        var parts: [String] = []
        if let companyName { parts.append(companyName) }
        parts.append(filing.category.label(language))
        if filing.isCorrected { parts.append(language("정정됨", "Corrected")) }
        if Freshness.isNew(filing.filedOn, dataAsOf: dataAsOf) { parts.append(language("새 공시", "New")) }
        parts.append(Formatting.fullDate(filing.filedOn, language: language))
        parts.append(Titles.title(for: filing, language: language))
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

    private var isNew: Bool { Freshness.isNew(report.filing.filedOn, dataAsOf: dataAsOf) }

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
