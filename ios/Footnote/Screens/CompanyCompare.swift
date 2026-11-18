import FootnoteKit
import SwiftUI

/// The company picker (board 7A): one list by market, the current company left out, and a
/// company whose fiscal year ends in another month marked with its month.
struct PeerPicker: View {
    @Environment(\.language) private var language
    @Environment(\.dismiss) private var dismiss
    let store: BundleStore
    let company: Company
    let pick: (Company) -> Void

    var body: some View {
        NavigationStack {
            List {
                Section {
                    TintNote(text: PageCopy.pickerNote(language))
                }
                ForEach(Regulator.allCases, id: \.self) { regulator in
                    let peers = store.companies.filter { $0.regulator == regulator && $0.id != company.id }
                    if !peers.isEmpty {
                        Section {
                            ForEach(peers) { peer in row(peer) }
                        } header: {
                            Text(words: PageCopy.pickerSection(
                                regulator, notesYearEnds: peers.contains(where: differs), language))
                        }
                    }
                }
            }
            .groupedScreen()
            .navigationTitle(PageCopy.pickerTitle(language))
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(PageCopy.cancel(language)) { dismiss() }
                        .frame(minWidth: Theme.minTarget, minHeight: Theme.minTarget)
                        .accessibilityIdentifier("picker-cancel")
                }
            }
        }
        #if os(macOS)
        .frame(minWidth: 400, minHeight: 560)
        #endif
        .accessibilityIdentifier("peer-picker")
    }

    /// Both year-end months are known and differ; an unknown month is not shown.
    private func differs(_ peer: Company) -> Bool {
        guard let theirs = peer.fiscalYearEndMonth, let ours = company.fiscalYearEndMonth else { return false }
        return theirs != ours
    }

    private func row(_ peer: Company) -> some View {
        Button { pick(peer) } label: {
            HStack(alignment: .firstTextBaseline, spacing: 12) {
                Text(words: Titles.name(of: peer, language: language))
                    .font(.body)
                    .foregroundStyle(Theme.ink)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
                if differs(peer), let month = peer.fiscalYearEndMonth {
                    Text(words: PageCopy.yearEnds(month, language))
                        .font(.footnote)
                        .foregroundStyle(Theme.muted)
                        .fixedSize()
                }
            }
            .frame(minHeight: Theme.minTarget)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .listRowBackground(Theme.surface)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isButton)
        .accessibilityIdentifier("peer-\(peer.id)")
    }
}

/// Compare with another company (board 7): growth rates or operating margins side by side,
/// each computed inside its own company's figures, with the caveat on standards and
/// year-ends. Amounts are refused (board 8). Nothing is ranked: both rates, the distance
/// between them, and bars in one grey.
struct CompanyCompareView: View {
    @Environment(\.language) private var language
    @Environment(\.navigate) private var navigate
    @Environment(\.dismiss) private var dismiss
    @Environment(\.dynamicTypeSize) private var typeSize
    let store: BundleStore
    let route: CompanyCompareRoute
    @State private var measure: CrossCompanyMeasure?

    init(store: BundleStore, route: CompanyCompareRoute) {
        self.store = store
        self.route = route
        _measure = State(initialValue: route.measure.flatMap(CrossCompanyMeasure.init(rawValue:)))
    }

    /// The measure as asked; none chosen is refused as ambiguous.
    private var requested: String? { measure?.rawValue }

    var body: some View {
        if let page = CompanyComparePage(
            store: store, companyID: route.companyID, peerID: route.peerID, metric: route.metric,
            measure: requested, fiscalYear: route.fiscalYear)
        {
            ScrollViewReader { proxy in
                List {
                    ScreenHeader(context: PageCopy.companiesContext(page.companies, language),
                                 title: PageCopy.compareCompany(language))
                    measurePicker
                    if case .result(let result) = page.outcome {
                        rates(page, result)
                    } else if let explanation = page.explanation {
                        RefusalSections(explanation: explanation) { perform($0, page) }
                    }
                    PageEndMarker()
                }
                .launchScroll(proxy)
            }
            .groupedScreen()
            .screenTitle(PageCopy.compareCompany(language))
            .languageToolbar()
            .accessibilityIdentifier("company-compare-page")
        }
    }

    @ViewBuilder private var measurePicker: some View {
        let picker = Picker(selection: $measure) {
            ForEach(CrossCompanyMeasure.allCases, id: \.self) { measure in
                Text(PageCopy.measureName(measure, language)).tag(Optional(measure))
            }
        } label: {
            Text(words: PageCopy.compareBy(language))
        }
        .accessibilityIdentifier("measure-picker")
        if typeSize.isAccessibilitySize {
            Section {
                picker.pickerStyle(.inline).labelsHidden()
            } header: {
                Text(words: PageCopy.compareBy(language))
            }
            .listRowBackground(Theme.surface)
        } else {
            Section {
                picker.pickerStyle(.segmented).labelsHidden()
                    .frame(minHeight: Theme.minTarget)
                    .buttonRow()
            }
        }
    }

    @ViewBuilder private func rates(_ page: CompanyComparePage, _ result: CrossCompany) -> some View {
        let largest = result.companies.map { abs($0.rate) }.max() ?? 0
        let drawsBars = largest > 0 && result.companies.allSatisfy { $0.rate >= 0 }
        Section {
            ForEach(Array(zip(page.companies, page.inputs).enumerated()), id: \.offset) { index, pair in
                RateRow(
                    company: pair.0, rate: result.companies[index], measure: page.chosenMeasure ?? .growthRate,
                    fiscalYear: pair.1.fiscalYear, basis: pair.1.basis,
                    share: drawsBars ? Self.share(result.companies[index].rate, of: largest) : nil)
            }
            if let difference = page.difference {
                FactRow(label: PageCopy.difference(language),
                        value: PageCopy.rateDifference(difference, language),
                        spoken: PageCopy.rateDifferenceSpoken(difference, language))
                    .accessibilityIdentifier("rate-difference")
            }
        } header: {
            Text(words: PageCopy.ratesHeading(page.chosenMeasure, metric: page.reportedMetric, language))
        }
        Section {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Image(systemName: "info.circle")
                    .foregroundStyle(Theme.pine)
                    .accessibilityHidden(true)
                Text(words: PageCopy.caveat(page.caveat, language))
                    .font(.subheadline)
                    .foregroundStyle(Theme.ink)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(.vertical, 6)
            .frame(maxWidth: .infinity, alignment: .leading)
            .listRowBackground(Theme.tint)
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("caveat")
        }
        Section {
            ActionButton(title: PageCopy.seeCalculation(language), primary: true) {
                navigate(.companyCalculation(CompanyCompareRoute(
                    companyID: route.companyID, peerID: route.peerID, metric: route.metric,
                    measure: page.chosenMeasure?.rawValue, fiscalYear: route.fiscalYear)))
            }
            .buttonRow()
            .accessibilityIdentifier("see-calculation")
        }
    }

    /// A bar's share of the longest bar, exact until the view's own geometry.
    private static func share(_ rate: Decimal, of largest: Decimal) -> Double {
        NSDecimalNumber(decimal: rate / largest).doubleValue
    }

    private func perform(_ action: RefusalAction, _ page: CompanyComparePage) {
        switch action {
        case .compare(let other): measure = other
        case .chooseFigure: dismiss()
        case .showYears(let companyID):
            if let route = Routes.figure(store, companyID: companyID, metric: page.reportedMetric) { navigate(route) }
        case .coveredFigures(let companyID):
            navigate(Routes.coveredFigures(store, companyID: companyID))
        }
    }
}

/// One company's rate: its name, the rate (a growth rate with its sign and word), a grey bar
/// when every rate is zero or above, and the period, year-end and standard behind it.
private struct RateRow: View {
    @Environment(\.language) private var language
    let company: Company
    let rate: CompanyRate
    let measure: CrossCompanyMeasure
    let fiscalYear: Int?
    let basis: String?
    /// The bar's length against the longest; nil draws no bar.
    let share: Double?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            FlowLayout(spacing: 8, lineSpacing: 4) {
                Text(words: Titles.name(of: company, language: language))
                    .font(.body.weight(.semibold))
                    .foregroundStyle(Theme.ink)
                if rate.isRestated { TagView(text: PageCopy.restatedTag(language), kind: .corrected) }
            }
            Text(words: rateText)
                .font(.title3.bold())
                .monospacedDigit()
                .foregroundStyle(Theme.ink)
                .fixedSize(horizontal: false, vertical: true)
            if let share {
                GeometryReader { proxy in
                    RoundedRectangle(cornerRadius: 3, style: .continuous)
                        .fill(Theme.muted.opacity(0.45))
                        .frame(width: max(proxy.size.width * share, 2))
                }
                .frame(height: 6)
                .accessibilityHidden(true)
            }
            Text(words: PageCopy.ratePeriod(company, fiscalYear: fiscalYear, basis: basis, language))
                .font(.footnote)
                .monospacedDigit()
                .foregroundStyle(Theme.muted)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.vertical, 6)
        .listRowBackground(Theme.surface)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(spoken)
        .accessibilityIdentifier("rate-\(company.id)")
    }

    private var rateText: String {
        measure == .growthRate
            ? Formatting.percentChange(rate.rate, language: language)
            : Formatting.percent(rate.rate)
    }

    private var spoken: String {
        var parts = [Titles.name(of: company, language: language)]
        if rate.isRestated { parts.append(PageCopy.restatedTag(language)) }
        parts.append(measure == .growthRate
            ? Formatting.percentChangeSpoken(rate.rate, language: language)
            : DerivedMetric.operatingMargin.name(language) + " " + Formatting.percent(rate.rate))
        parts.append(PageCopy.ratePeriod(company, fiscalYear: fiscalYear, basis: basis, language)
            .spokenSeparators)
        return parts.joined(separator: ", ")
    }
}

/// A refusal (boards 8, 10): the title, the reason filled from data, board 10's body and the
/// short reason, then at least one comparison that is possible instead.
struct RefusalSections: View {
    @Environment(\.language) private var language
    let explanation: RefusalExplanation
    let perform: (RefusalAction) -> Void

    var body: some View {
        Section {
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Image(systemName: "info.circle")
                        .font(.title3)
                        .foregroundStyle(Theme.muted)
                        .accessibilityHidden(true)
                    Text(words: PageCopy.refusalTitle(explanation, language))
                        .font(.title3.bold())
                        .foregroundStyle(Theme.ink)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Text(words: PageCopy.refusalReason(explanation, language))
                    .font(.body)
                    .foregroundStyle(Theme.ink)
                    .fixedSize(horizontal: false, vertical: true)
                if let body = PageCopy.refusalBody(explanation.refusal, language) {
                    Text(words: body)
                        .font(.subheadline)
                        .foregroundStyle(Theme.muted)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Text(words: PageCopy.refusalCode(explanation.refusal, language))
                    .font(.footnote)
                    .foregroundStyle(Theme.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(.vertical, 8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .listRowBackground(Theme.surface)
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("refusal-\(explanation.refusal.reason.rawValue)")
        }
        Section {
            ForEach(Array(explanation.actions.enumerated()), id: \.offset) { index, action in
                LinkRow(title: PageCopy.actionLabel(
                    action, reason: explanation.refusal.reason, detail: explanation.refusal.detail,
                    metric: explanation.metric, language)) {
                    perform(action)
                }
                .accessibilityIdentifier("instead-\(index)")
            }
        } header: {
            Text(words: PageCopy.insteadHeading(language))
        }
    }
}
