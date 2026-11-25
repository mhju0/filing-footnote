import FootnoteKit
import SwiftUI

/// One figure (board 5A, DESIGN.md Figure): the exact value of the report's year with its
/// change, the meaning from the glossary, every year in the bundle, the source, then the two
/// compare actions.
struct FigureView: View {
    @Environment(\.language) private var language
    @Environment(\.navigate) private var navigate
    let store: BundleStore
    let page: FigurePage
    @State private var picking: Bool

    init(store: BundleStore, page: FigurePage) {
        self.store = store
        self.page = page
        _picking = State(initialValue: LaunchRoute.current?.opensPicker(page.company.id) == true)
    }

    var body: some View {
        ScrollViewReader { proxy in
            List {
                header
                if let entry = page.meaning(language) {
                    meaning(entry)
                }
                years
                actions
                PageEndMarker()
            }
            .launchScroll(proxy)
        }
        .groupedScreen()
        .screenTitle(page.metric.name(language))
        .languageToolbar()
        .sheet(isPresented: $picking) {
            PeerPicker(store: store, company: page.company) { peer in
                picking = false
                navigate(.companyCompare(CompanyCompareRoute(
                    companyID: page.company.id, peerID: peer.id, metric: page.metric.rawValue,
                    measure: CrossCompanyMeasure.growthRate.rawValue, fiscalYear: page.fiscalYear)))
            }
        }
        .accessibilityIdentifier("figure-page")
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(words: PageCopy.figureContext(page.company, basis: page.basis, fiscalYear: page.fiscalYear, language))
                .font(.subheadline)
                .foregroundStyle(Theme.muted)
                .fixedSize(horizontal: false, vertical: true)
            Text(words: page.metric.name(language))
                .font(.title2.bold())
                .foregroundStyle(Theme.ink)
                .fixedSize(horizontal: false, vertical: true)
            if let current = page.current {
                // The rounded amount on one line, the exact one under it (2026-11-26 review,
                // issue 11; owner pick, design direction 9 B).
                let headline = PageCopy.headline(current, language)
                let exact = PageCopy.exact(current, language)
                FlowLayout(spacing: 8, lineSpacing: 4) {
                    BigValue(text: headline)
                    if current.isRestated { TagView(text: PageCopy.restatedTag(language), kind: .corrected) }
                }
                if exact != headline {
                    UnbrokenNumbers(text: PageCopy.exactAmount(exact, language))
                        .font(.subheadline)
                        .monospacedDigit()
                        .foregroundStyle(Theme.muted)
                        .accessibilityIdentifier("figure-exact")
                }
            } else {
                Text(words: PageCopy.noFigure(language))
                    .font(.title3)
                    .foregroundStyle(Theme.muted)
            }
            switch page.change {
            case .result(let change):
                PhraseLines(phrases: PageCopy.changeFromLastYearPhrases(change.percentChange, language))
                    .font(.body)
                    .monospacedDigit()
                    .foregroundStyle(Theme.ink)
                if let note = PageCopy.fiscalYearsNote(change, language) {
                    SectionNote(text: note)
                }
            case .refusal(let refusal):
                Text(words: PageCopy.refusal(refusal, language))
                    .font(.subheadline)
                    .foregroundStyle(Theme.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .headerRow()
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(spokenHeader)
        .accessibilityAddTraits(.isHeader)
    }

    private var spokenHeader: String {
        var parts = [PageCopy.figureContext(page.company, basis: page.basis, fiscalYear: page.fiscalYear, language)
            .spokenSeparators, page.metric.name(language)]
        if let current = page.current {
            parts.append(PageCopy.exact(current, language))
            if current.isRestated { parts.append(PageCopy.restatedTag(language)) }
        } else {
            parts.append(PageCopy.noFigure(language))
        }
        switch page.change {
        case .result(let change):
            parts.append(Formatting.percentChangeSpoken(change.percentChange, language: language))
            if let note = PageCopy.fiscalYearsNote(change, language) { parts.append(note) }
        case .refusal(let refusal):
            parts.append(PageCopy.refusal(refusal, language))
        }
        return parts.joined(separator: ", ")
    }

    private func meaning(_ entry: GlossaryEntry) -> some View {
        Section {
            VStack(alignment: .leading, spacing: 6) {
                Text(words: entry.plain)
                    .font(.body)
                    .foregroundStyle(Theme.ink)
                    .fixedSize(horizontal: false, vertical: true)
                if let formal = entry.formal {
                    Text(words: PageCopy.formalTerm(formal, language))
                        .font(.subheadline)
                        .foregroundStyle(Theme.muted)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(.vertical, 4)
            .listRowBackground(Theme.surface)
            .accessibilityElement(children: .combine)
            LinkRow(title: PageCopy.moreInGlossary(language)) { navigate(.glossary(entry.termKey)) }
                .accessibilityIdentifier("more-in-glossary")
        } header: {
            SectionTitle(PageCopy.meaning(language))
        }
    }

    private var years: some View {
        Section {
            ForEach(page.years) { figure in
                FactRow(
                    label: PageCopy.fiscalYear(figure.fiscalYear, language),
                    value: PageCopy.exact(figure, language),
                    details: FiscalPeriod.isCalendarYear(figure) ? []
                        : [Formatting.period(figure.periodStart, figure.periodEnd, language: language)],
                    tag: figure.isRestated ? PageCopy.restatedTag(language) : nil)
            }
        } header: {
            SectionTitle(PageCopy.earlierYears(language))
        } footer: {
            VStack(alignment: .leading, spacing: 6) {
                if page.hasRestated { SectionNote(text: PageCopy.restatedNote(language)) }
                if let source = page.current.flatMap(page.source(of:)) {
                    SectionNote(text: PageCopy.source(source, language))
                }
            }
        }
    }

    private var actions: some View {
        Section {
            VStack(spacing: 10) {
                ActionButton(title: PageCopy.compareLastYear(language), primary: true) {
                    navigate(.yearCompare(page.company.id, page.metric.rawValue, page.fiscalYear))
                }
                .accessibilityIdentifier("compare-last-year")
                ActionButton(title: PageCopy.compareCompany(language), primary: false) {
                    picking = true
                }
                .accessibilityIdentifier("compare-company")
            }
            .buttonRow()
        }
    }
}

/// Compare with last year (board 6): the rate, its direction in words and the exact
/// difference, both years' exact values, the checks, then the calculation. A refusal shows
/// why and what is possible instead.
struct YearCompareView: View {
    @Environment(\.language) private var language
    @Environment(\.navigate) private var navigate
    @Environment(\.dismiss) private var dismiss
    let store: BundleStore
    let page: YearComparePage

    var body: some View {
        List {
            ScreenHeader(
                context: PageCopy.compareContext(
                    page.company, metric: page.reportedMetric?.name(language), basis: page.basis, language),
                title: PageCopy.compareLastYear(language))
            if let calculation = page.calculation {
                result(calculation)
            } else if let explanation = page.explanation {
                RefusalSections(explanation: explanation, perform: perform)
            }
        }
        .groupedScreen()
        .screenTitle(PageCopy.compareLastYear(language))
        .languageToolbar()
        .accessibilityIdentifier("year-compare-page")
    }

    @ViewBuilder private func result(_ calculation: YearCalculation) -> some View {
        let change = calculation.result
        RateHeadline(change: change)
        Section {
            ForEach([calculation.prior, calculation.current]) { figure in
                FactRow(
                    label: PageCopy.fiscalYear(figure.fiscalYear, language), value: PageCopy.exact(figure, language),
                    tag: figure.isRestated ? PageCopy.restatedTag(language) : nil)
            }
        } footer: {
            if calculation.prior.isRestated || calculation.current.isRestated {
                SectionNote(text: PageCopy.restatedNote(language))
            }
        }
        Section {
            Button {
                navigate(.yearCalculation(page.company.id, calculation.metric.rawValue, page.fiscalYear))
            } label: {
                HStack(spacing: 10) {
                    Image(systemName: "checkmark.circle")
                        .foregroundStyle(Theme.pine)
                        .accessibilityHidden(true)
                    Text(words: PageCopy.checksPassed(language))
                        .font(.body)
                        .foregroundStyle(Theme.ink)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    Chevron()
                }
                .frame(minHeight: Theme.minTarget)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .listRowBackground(Theme.surface)
            .accessibilityIdentifier("checks-passed")
        }
        Section {
            ActionButton(title: PageCopy.seeCalculation(language), primary: true) {
                navigate(.yearCalculation(page.company.id, calculation.metric.rawValue, page.fiscalYear))
            }
            .buttonRow()
            .accessibilityIdentifier("see-calculation")
        }
    }

    private func perform(_ action: RefusalAction) {
        switch action {
        case .chooseFigure:
            dismiss()
        case .showYears(let companyID) where companyID == page.company.id:
            dismiss()
        case .showYears(let companyID):
            if let route = Routes.figure(store, companyID: companyID, metric: page.reportedMetric) { navigate(route) }
        case .coveredFigures(let companyID):
            navigate(Routes.coveredFigures(store, companyID: companyID))
        case .compare:
            break
        }
    }
}

/// The rate, its direction in words, and the exact difference (board 6).
private struct RateHeadline: View {
    @Environment(\.language) private var language
    let change: YearOverYear

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            BigValue(text: Formatting.percentWithGlyph(change.percentChange))
            Text(words: PageCopy.direction(change.percentChange, language))
                .font(.title3.weight(.semibold))
                .foregroundStyle(Theme.ink)
                .fixedSize(horizontal: false, vertical: true)
            UnbrokenNumbers(text: PageCopy.signedExact(change.delta, unit: change.unit, currency: change.currency, language))
                .font(.subheadline)
                .monospacedDigit()
                .foregroundStyle(Theme.muted)
            if let note = PageCopy.fiscalYearsNote(change, language) {
                SectionNote(text: note)
            }
        }
        .headerRow()
        .accessibilityElement(children: .ignore)
        .accessibilityLabel([
            Formatting.percentChangeSpoken(change.percentChange, language: language),
            PageCopy.difference(language) + " "
                + PageCopy.signedExact(change.delta, unit: change.unit, currency: change.currency, language),
        ].joined(separator: ", ") + (PageCopy.fiscalYearsNote(change, language).map { ", " + $0 } ?? ""))
        .accessibilityIdentifier("year-change")
    }
}

/// The calculation (board 6b): the formula with every operand in full digits, the rounding
/// rule, the inputs with their filings and periods, and the checks passed. A cross-company
/// calculation shows one block per company, then the difference of the rates.
struct CalculationView: View {
    @Environment(\.language) private var language
    let context: String
    let calculations: [CompanyCalculation]
    var difference: Decimal?

    var body: some View {
        ScrollViewReader { proxy in
            list.launchScroll(proxy)
        }
        .groupedScreen()
        .screenTitle(PageCopy.calculation(language))
        .languageToolbar()
        .accessibilityIdentifier("calculation-page")
    }

    private var list: some View {
        List {
            ScreenHeader(context: context, title: PageCopy.calculation(language))
            ForEach(Array(calculations.enumerated()), id: \.offset) { _, calculation in
                let named = calculations.count > 1 ? Titles.name(of: calculation.company, language: language) : nil
                switch calculation {
                case .growth(let growth): GrowthCalculation(calculation: growth, companyName: named)
                case .margin(let margin): MarginCalculationSections(calculation: margin, companyName: named)
                }
            }
            if let difference, calculations.count == 2 {
                Section {
                    FactRow(
                        label: PageCopy.difference(language),
                        value: Self.differenceText(difference, calculations, language),
                        spoken: PageCopy.rateDifferenceSpoken(difference, language))
                }
            }
            PageEndMarker()
        }
    }

    /// `|−14.33 − 15.67| = 30.00%포인트` / `… = 30.00 percentage points`.
    nonisolated static func differenceText(
        _ difference: Decimal, _ calculations: [CompanyCalculation], _ language: Language
    ) -> String {
        let rates = calculations.map { calculation -> String in
            switch calculation {
            case .growth(let growth): Formatting.percent(growth.result.percentChange).replacingOccurrences(of: "%", with: "")
            case .margin(let margin): Formatting.percent(margin.result.operatingMargin).replacingOccurrences(of: "%", with: "")
            }
        }
        let digits = DecimalText.twoPlaces(DecimalText.roundHalfUp(difference, scale: 2))
        return "|\(rates[0]) \(Formatting.minus) \(rates[1])| = \(digits)" + PageCopy.percentagePoints(language)
    }
}

private struct GrowthCalculation: View {
    @Environment(\.language) private var language
    let calculation: YearCalculation
    let companyName: String?

    var body: some View {
        let change = calculation.result
        Section {
            Equation(
                formula: PageCopy.growthFormula(language), equation: PageCopy.growthEquation(change),
                result: PageCopy.signedPercent(change.percentChange), unit: PageCopy.unitAndRounding(change.unit, language),
                spokenResult: Formatting.percentChangeSpoken(change.percentChange, language: language))
        } header: {
            SectionTitle(companyName.map { $0 + Copy.dot + PageCopy.formula(language) } ?? PageCopy.formula(language))
        }
        Section {
            ForEach([
                (calculation.prior, calculation.priorSource), (calculation.current, calculation.currentSource),
            ], id: \.0.id) { figure, source in
                InputRow(figure: figure, source: source)
            }
            FactRow(
                label: PageCopy.difference(language),
                value: PageCopy.signedExact(change.delta, unit: change.unit, currency: change.currency, language))
        } header: {
            SectionTitle(PageCopy.inputs(language))
        } footer: {
            if let source = calculation.currentSource, calculation.priorSource == source {
                SectionNote(text: PageCopy.bothFrom(source, language))
            }
        }
        Section {
            ForEach(Array(calculation.checks.enumerated()), id: \.offset) { _, check in
                CheckRow(label: PageCopy.checkLabel(check, language), value: PageCopy.checkValue(check, language))
            }
        } header: {
            SectionTitle(PageCopy.checks(language))
        }
    }
}

private struct MarginCalculationSections: View {
    @Environment(\.language) private var language
    let calculation: MarginCalculation
    let companyName: String?

    var body: some View {
        let margin = calculation.result
        Section {
            Equation(
                formula: PageCopy.marginFormulaWritten(language), equation: PageCopy.marginEquation(margin),
                result: Formatting.percent(margin.operatingMargin),
                unit: PageCopy.unitAndRounding(calculation.revenue.unit, language),
                spokenResult: DerivedMetric.operatingMargin.name(language) + " " + Formatting.percent(margin.operatingMargin))
        } header: {
            SectionTitle(companyName.map { $0 + Copy.dot + PageCopy.formula(language) } ?? PageCopy.formula(language))
        }
        Section {
            InputRow(figure: calculation.revenue, source: calculation.source)
            InputRow(figure: calculation.operatingIncome, source: calculation.source)
        } header: {
            SectionTitle(PageCopy.inputs(language))
        }
        Section {
            CheckRow(label: PageCopy.checkLabel(.sameCompany(calculation.company), language),
                     value: Titles.name(of: calculation.company, language: language))
            CheckRow(label: PageCopy.checkLabel(.sameCurrency(margin.currency), language),
                     value: PageCopy.checkValue(.sameCurrency(margin.currency), language))
            CheckRow(label: PageCopy.checkLabel(.sameBasis(calculation.revenue.basis), language),
                     value: PageCopy.checkValue(.sameBasis(calculation.revenue.basis), language))
            CheckRow(label: PageCopy.samePeriod(language),
                     value: Formatting.period(margin.periodStart, margin.periodEnd, language: language))
            CheckRow(label: PageCopy.revenueAboveZero(language), value: PageCopy.exact(calculation.revenue, language))
        } header: {
            SectionTitle(PageCopy.checks(language))
        }
    }
}

/// The formula, the equation in full digits, the result, the unit and rounding rule.
private struct Equation: View {
    let formula: String
    let equation: String
    let result: String
    let unit: String
    let spokenResult: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(words: formula)
                .font(.subheadline)
                .foregroundStyle(Theme.muted)
                .fixedSize(horizontal: false, vertical: true)
            UnbrokenNumbers(text: equation)
                .font(.body)
                .monospacedDigit()
                .foregroundStyle(Theme.ink)
            Text(words: "= " + result)
                .font(.title2.bold())
                .monospacedDigit()
                .foregroundStyle(Theme.ink)
            Text(words: unit)
                .font(.footnote)
                .foregroundStyle(Theme.muted)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.vertical, 6)
        .frame(maxWidth: .infinity, alignment: .leading)
        .listRowBackground(Theme.surface)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel([formula, equation, spokenResult, unit].joined(separator: ", "))
        .accessibilityIdentifier("equation")
    }
}

/// One input: its year, exact value, period and filing.
private struct InputRow: View {
    @Environment(\.language) private var language
    let figure: Figure
    let source: Filing?

    var body: some View {
        var details = [Formatting.period(figure.periodStart, figure.periodEnd, language: language)]
        if let source { details.append(PageCopy.inputSource(source, language)) }
        return FactRow(
            label: PageCopy.fiscalYear(figure.fiscalYear, language) + " " + figure.metric.name(language),
            value: PageCopy.exact(figure, language), details: details,
            tag: figure.isRestated ? PageCopy.restatedTag(language) : nil)
    }
}

/// A check the comparison passed: a check mark, what was checked, and the value.
private struct CheckRow: View {
    let label: String
    let value: String

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Image(systemName: "checkmark")
                .font(.body.weight(.semibold))
                .foregroundStyle(Theme.pine)
                .accessibilityHidden(true)
            FlowLayout(spacing: 12, lineSpacing: 2) {
                Text(words: label)
                    .font(.body)
                    .foregroundStyle(Theme.ink)
                Text(words: value)
                    .font(.body)
                    .monospacedDigit()
                    .foregroundStyle(Theme.muted)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.vertical, 4)
        .frame(minHeight: Theme.minTarget)
        .listRowBackground(Theme.surface)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(label + ", " + value)
    }
}

// MARK: - Shared parts

/// The context line and title at the top of a compare screen.
struct ScreenHeader: View {
    let context: String
    let title: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(words: context)
                .font(.subheadline)
                .foregroundStyle(Theme.muted)
                .fixedSize(horizontal: false, vertical: true)
            Text(words: title)
                .font(.title.bold())
                .foregroundStyle(Theme.ink)
                .fixedSize(horizontal: false, vertical: true)
        }
        .headerRow()
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isHeader)
    }
}

/// A value at the size of board 5A's figure (34 pt bold). Korean wraps between words; an
/// English value is one run of digits, so it shrinks to fit instead.
struct BigValue: View {
    @Environment(\.language) private var language
    let text: String

    var body: some View {
        Text(words: text)
            .font(.largeTitle.bold())
            .monospacedDigit()
            .foregroundStyle(Theme.ink)
            .lineLimit(language == .en ? 1 : nil)
            .minimumScaleFactor(language == .en ? 0.5 : 1)
            .fixedSize(horizontal: false, vertical: true)
            .numberTransition(text)
    }
}

/// A full-width action: Pine for the main one, Surface with a Line border for the other.
/// Rounded rectangles, not pills (DESIGN.md).
struct ActionButton: View {
    let title: String
    let primary: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(words: title)
                .font(.body.weight(.semibold))
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .foregroundStyle(primary ? Theme.onPine : Theme.pine)
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
                .frame(maxWidth: .infinity, minHeight: 50)
                .background(primary ? Theme.pine : Theme.surface, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                .overlay {
                    if !primary {
                        RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Theme.line)
                    }
                }
                .contentShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        }
        .buttonStyle(.plain)
    }
}

/// A row that opens another screen, with its chevron.
struct LinkRow: View {
    let title: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Text(words: title)
                    .font(.body)
                    .foregroundStyle(Theme.pine)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Chevron()
            }
            .frame(minHeight: Theme.minTarget)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .listRowBackground(Theme.surface)
    }
}

enum FiscalPeriod {
    /// January 1 to December 31: the year label says it all.
    static func isCalendarYear(_ figure: Figure) -> Bool {
        figure.periodStart.month == 1 && figure.periodStart.day == 1
            && figure.periodEnd.month == 12 && figure.periodEnd.day == 31
    }
}

/// Routes the refusal actions open.
enum Routes {
    /// A company's figure screen for its newest year of the metric.
    static func figure(_ store: BundleStore, companyID: String, metric: ReportedMetric?) -> Route? {
        guard let metric, let year = store.figures(forCompany: companyID, metric: metric).map(\.fiscalYear).max()
        else { return nil }
        return .figure(companyID, metric.rawValue, year)
    }

    /// The covered figures: the annual page of the company's newest figures.
    static func coveredFigures(_ store: BundleStore, companyID: String) -> Route {
        let newest = store.figures.filter { $0.companyID == companyID }.max { $0.fiscalYear < $1.fiscalYear }
        return newest.map { .filing($0.filingID) } ?? .company(companyID)
    }
}

extension View {
    /// The board's header block: no row background, aligned with the section text.
    func headerRow() -> some View {
        self
            .padding(.vertical, 4)
            .frame(maxWidth: .infinity, alignment: .leading)
            .listRowBackground(Color.clear)
            .listRowInsets(EdgeInsets(top: 4, leading: 4, bottom: 4, trailing: 4))
    }

    /// A row of full-width buttons with no row background, and no separator under it
    /// (2026-11-26 review, issue 14).
    func buttonRow() -> some View {
        self
            .listRowBackground(Color.clear)
            .listRowInsets(EdgeInsets(top: 4, leading: 0, bottom: 4, trailing: 0))
            .listRowSeparator(.hidden)
    }

    /// The screen's own title stays in its content on iPhone and iPad (board 5A); the Mac
    /// window shows it in the title bar.
    func screenTitle(_ title: String) -> some View {
        #if os(iOS)
        self.navigationTitle("").navigationBarTitleDisplayMode(.inline)
        #else
        self.navigationTitle(title)
        #endif
    }
}

/// An invisible last row of a list, for `-FootnoteScroll bottom` (debug screenshots).
struct PageEndMarker: View {
    var body: some View {
        Section {
            Color.clear
                .frame(height: 1)
                .listRowBackground(Color.clear)
                .listRowInsets(EdgeInsets())
                .listRowSeparator(.hidden)
                .accessibilityHidden(true)
                .id(PageScroll.end)
        }
    }
}
