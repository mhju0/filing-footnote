import FootnoteKit
import Foundation

/// Copy for the filing page (board 12A), the annual page (board 4) and the figure screen.
/// Approved wording is marked with its board. `Draft:` marks wording no board covers; the
/// pull request lists each one for the owner.
enum PageCopy {
    // MARK: - Sections

    static func sentences(_ language: Language) -> String { language("공시 내용", "What the filing says") }
    static func numbers(_ language: Language) -> String { language("공시의 숫자", "Numbers in the filing") }
    static func original(_ language: Language) -> String { language("원문", "The original") }

    // MARK: - States (board 19)

    static func inReviewTitle(_ language: Language) -> String {
        language("요약을 확인하고 있어요", "Summary in review")
    }

    static func inReviewBody(_ language: Language) -> String {
        language(
            "확인을 마친 요약만 보여 줘요. 공시의 숫자와 원문은 지금 볼 수 있어요.",
            "Only checked summaries are shown. The filing’s numbers and the original are available now.")
    }

    static func corrected(_ language: Language) -> String {
        language("회사가 처음 낸 공시를 고쳐 다시 냈어요.", "The company corrected and refiled this filing.")
    }

    static func outlookWithoutFigures(_ language: Language) -> String {
        language("이 공시에는 숫자로 된 목표가 없어요.", "This filing gives no numeric target.")
    }

    /// Board 9: a base of zero or below has no growth rate.
    static func baseNotPositive(_ language: Language) -> String {
        language("작년 숫자가 0 이하라 증가율을 계산하지 않아요", "Last year was zero or below, so there is no growth rate")
    }

    /// Draft: how the sentences were written. The bundle does not say whether a sentence came
    /// from a template or a model, so the note covers both.
    static func howWritten(_ language: Language) -> String {
        language(
            "공시를 바탕으로 쓰고, 게시 전에 확인한 문장이에요.",
            "Written from the filing and checked before publishing.")
    }

    /// Lead decision (D83): pages show money amounts in the company page's compact form, and
    /// the exact value on tap. One sentence per line, so neither wraps a lone word.
    static func amountsShortened(_ language: Language) -> String {
        language(
            "금액은 줄여서 보여 줘요.\n숫자를 누르면 정확한 값을 볼 수 있어요.",
            "Amounts are shortened.\nTap a figure to see the exact value.")
    }

    // MARK: - Outlook (board 16)

    /// Board 16; the English says "outlook" for "forecast" (D78 names it the company outlook).
    static func outlookBanner(_ language: Language) -> String {
        language(
            "회사가 내놓은 전망이에요. 실제 결과가 아니고, 앱은 이 숫자를 비교에 쓰지 않아요.",
            "This is the company’s own outlook, not a result. The app never uses these numbers in comparisons.")
    }

    /// Draft: the heading of one outlook column.
    static func outlookHeading(year: String?, salesTargets: Bool, _ language: Language) -> String {
        let year = year ?? ""
        if salesTargets {
            return year.isEmpty
                ? language("판매 목표 (대수)", "Sales target (units)")
                : language("\(year)년 판매 목표 (대수)", "\(year) sales target (units)")
        }
        return year.isEmpty ? language("회사 전망", "Company outlook") : language("\(year)년 전망", "\(year) outlook")
    }

    /// The exact value under a shortened amount, shown on a tap.
    static func exactValue(_ value: String, _ language: Language) -> String {
        language("정확한 값 \(value)", "Exact: \(value)")
    }

    /// Draft: the value a corrected outlook item had before this filing.
    static func beforeCorrection(_ value: String, _ language: Language) -> String {
        language("정정 전 \(value)", "Before the correction: \(value)")
    }

    // MARK: - Compared figures

    /// Draft: what a results, change or unit-sales block compares with.
    static func comparisonHeading(_ block: ComparisonBlock, _ language: Language) -> String {
        var parts: [String] = []
        if let period = block.period {
            parts.append(Formatting.period(period.start, period.end, language: language))
        }
        switch block.basis {
        case .consolidated: parts.append(language("연결", "Consolidated"))
        case .separate: parts.append(language("별도", "Separate"))
        case nil: break
        }
        if parts.isEmpty {
            return block.kind == .units ? language("판매 실적", "Units sold") : numbers(language)
        }
        return parts.joined(separator: Copy.dot)
    }

    /// Draft: the note under a compared block, naming the base period.
    static func comparisonNote(_ block: ComparisonBlock, _ language: Language) -> String {
        switch block.kind {
        case .results:
            guard let base = block.basePeriod else {
                return language("작년 같은 기간과 비교했어요.", "Compared with the same period a year earlier.")
            }
            let span = Formatting.period(base.start, base.end, language: language)
            return language("작년 같은 기간(\(span))과 비교했어요.", "Compared with \(span).")
        case .change:
            guard let base = block.basePeriod else {
                return language("직전 사업연도와 비교했어요.", "Compared with the previous fiscal year.")
            }
            let span = Formatting.period(base.start, base.end, language: language)
            return language("직전 사업연도(\(span))와 비교했어요.", "Compared with the previous fiscal year, \(span).")
        case .units:
            guard let span = yearEarlier(block.period, language) else {
                return language("작년 같은 기간과 비교했어요. 누적은 작년 누적과 비교했어요.",
                                "Compared with the same period a year earlier; year to date with last year’s.")
            }
            return language("작년 같은 기간(\(span))과 비교했어요. 누적은 작년 누적과 비교했어요.",
                            "Compared with \(span); year to date with last year’s.")
        }
    }

    /// The same months one year earlier, written as a period; nil without a period.
    private static func yearEarlier(_ period: DatePeriod?, _ language: Language) -> String? {
        guard let period,
              let start = CivilDate(year: period.start.year - 1, month: period.start.month, day: period.start.day),
              let end = CivilDate(year: period.end.year - 1, month: period.end.month, day: period.end.day)
                ?? CivilDate(year: period.end.year - 1, month: period.end.month, day: period.end.day - 1)
        else { return nil }
        return Formatting.period(start, end, language: language)
    }

    /// Draft: the base value beside a compared figure.
    static func baseValue(_ value: String, kind: ComparisonBlock.Kind, _ language: Language) -> String {
        switch kind {
        case .results, .units: language("작년 \(value)", "A year earlier: \(value)")
        case .change: language("직전 연도 \(value)", "Previous year: \(value)")
        }
    }

    // MARK: - Clarification (board 17)

    static func status(_ language: Language) -> String { language("상태", "Status") }

    static func statusValue(_ status: ClarificationStatus, _ language: Language) -> String {
        switch status {
        case .undecided: language("미확정", "Not decided")
        }
    }

    static func statusNote(_ status: ClarificationStatus, _ language: Language) -> String {
        switch status {
        case .undecided: language("회사가 아직 정하지 않았다는 뜻이에요.", "The company has not decided yet.")
        }
    }

    // MARK: - Source details

    static func form(_ language: Language) -> String { language("서식", "Form") }
    static func filed(_ language: Language) -> String { language("공시일", "Filed") }

    static func receiptNumber(_ regulator: Regulator, _ language: Language) -> String {
        regulator == .dart ? language("접수번호", "Receipt number") : language("접수번호", "Accession number")
    }

    // MARK: - Annual page (board 4)

    static func annualSections(_ section: SummarySection, _ language: Language) -> String {
        switch section {
        case .business: language("무슨 사업", "What the business is")
        case .changes: language("무엇이 바뀌었나", "What changed")
        case .risks: language("회사가 꼽은 위험", "Risks the company names")
        case .oneLine, .summary: ""
        }
    }

    static func keyFigures(_ language: Language) -> String { language("핵심 숫자", "Key figures") }

    /// `2025 회계연도 · 연결 기준 · 원` / `FY2025 · Consolidated · Korean won`.
    static func figuresBasis(fiscalYear: Int, basis: String?, currency: String, _ language: Language) -> String {
        var parts = [Self.fiscalYear(fiscalYear, language)]
        if basis == "consolidated" { parts.append(language("연결 기준", "Consolidated")) }
        if basis == "separate" { parts.append(language("별도 기준", "Separate")) }
        parts.append(currencyName(currency, language))
        return parts.joined(separator: Copy.dot)
    }

    static func currencyName(_ currency: String, _ language: Language) -> String {
        switch currency {
        case "KRW": language("원", "Korean won")
        case "USD": language("달러", "US dollars")
        default: currency
        }
    }

    /// `2025 회계연도` / `FY2025`.
    static func fiscalYear(_ year: Int, _ language: Language) -> String {
        language("\(year) 회계연도", "FY\(year)")
    }

    /// The approved restated note (board 19, G1): beside a 정정됨 / Restated tag. A no-break
    /// space keeps the last word from wrapping alone.
    static func restatedNote(_ language: Language) -> String {
        language(
            "회사가 나중에 고쳐 다시 낸 숫자예요. 처음 공시한 숫자와\u{00A0}달라요.",
            "The company later corrected this figure. It differs from the first\u{00A0}filing.")
    }

    static func restatedTag(_ language: Language) -> String { language("정정됨", "Restated") }

    /// Draft: a year with no figure in the bundle.
    static func noFigure(_ language: Language) -> String {
        language("이 해의 숫자가 없어요", "No figure for this year")
    }

    /// Draft: the reported metrics that have no figure for either year.
    static func notStated(_ metrics: [ReportedMetric], _ language: Language) -> String? {
        guard !metrics.isEmpty else { return nil }
        let names = metrics.map { $0.name(language) }.joined(separator: language(", ", ", "))
        return language("이 두 해의 숫자가 없는 항목: \(names)", "No figure for either year: \(names)")
    }

    /// The formula line under the operating margin (board 4 derives it).
    static func marginFormula(_ language: Language) -> String {
        language("영업이익 ÷ 매출", "Operating income ÷ revenue")
    }

    // MARK: - Figure screen (board 5A)

    static func meaning(_ language: Language) -> String { language("이 숫자의 뜻", "What it means") }
    static func moreInGlossary(_ language: Language) -> String { language("용어 풀이 더 보기", "More in the glossary") }
    static func earlierYears(_ language: Language) -> String { language("연도별", "By year") }
    static func calculation(_ language: Language) -> String { language("계산", "Calculation") }
    static func compareLastYear(_ language: Language) -> String { language("작년과 비교", "Compare with last year") }
    static func compareCompany(_ language: Language) -> String {
        language("다른 회사와 비교", "Compare with another company")
    }

    /// Draft: the formal term under the plain meaning.
    static func formalTerm(_ term: String, _ language: Language) -> String {
        language("공식 용어: \(term)", "Formal term: \(term)")
    }

    /// `삼성전자 · 연결 기준 · 2025 회계연도` (board 5A).
    static func figureContext(_ company: Company, basis: String?, fiscalYear: Int, _ language: Language) -> String {
        var parts = [Titles.name(of: company, language: language)]
        if let basis = basisName(basis, language) { parts.append(basis) }
        parts.append(Self.fiscalYear(fiscalYear, language))
        return parts.joined(separator: Copy.dot)
    }

    /// `연결 기준` / `Consolidated`; nil for a basis the app has no word for.
    static func basisName(_ basis: String?, _ language: Language) -> String? {
        switch basis {
        case "consolidated", "consolidated_entity_total": language("연결 기준", "Consolidated")
        case "separate": language("별도 기준", "Separate")
        default: nil
        }
    }

    /// The direction line under the figure (board 5A): `+16.20% 늘었어요 · 작년보다`,
    /// `+16.20%, up from last year`.
    static func changeFromLastYear(_ percent: Decimal, _ language: Language) -> String {
        let change = Formatting.percentChange(percent, language: language)
        return language(change + Copy.dot + "작년보다", change + " from last year")
    }

    /// `출처: 사업보고서 (2025.12) · 2026년 3월 10일 공시` (board 5A).
    static func source(_ filing: Filing, _ language: Language) -> String {
        let title = Titles.title(for: filing, language: language)
        return language("출처: ", "Source: ") + title + Copy.dot + Copy.filedOn(filing.filedOn, language)
    }

    /// The note under a change between fiscal years that end on different days (D82). The
    /// week is the clearer fact, so it replaces the note about the ends.
    static func fiscalYearsNote(_ change: YearOverYear, _ language: Language) -> String? {
        if change.periodLengthsDiffer {
            return language("한 해가 다른 해보다 한 주 길어요.", "One of the years is a week longer.")
        }
        guard change.periodEndsDiffer else { return nil }
        return language("회계연도 마감일이 며칠 달라요.", "The fiscal years end a few days apart.")
    }

    // MARK: - Compare with last year (board 6)

    /// `삼성전자 · 매출 · 연결 기준`.
    static func compareContext(_ company: Company, metric: String?, basis: String?, _ language: Language) -> String {
        var parts = [Titles.name(of: company, language: language)]
        if let metric { parts.append(metric) }
        if let basis = basisName(basis, language) { parts.append(basis) }
        return parts.joined(separator: Copy.dot)
    }

    /// The direction word under the rate: `작년보다 늘었어요` / `Up from last year`.
    static func direction(_ percent: Decimal, _ language: Language) -> String {
        let rounded = DecimalText.roundHalfUp(percent, scale: 2)
        if rounded > 0 { return language("작년보다 늘었어요", "Up from last year") }
        if rounded < 0 { return language("작년보다 줄었어요", "Down from last year") }
        return language("작년과 같아요", "Same as last year")
    }

    /// The rate alone with its sign: `+16.20%`, `−19.47%`, `0.00%`.
    static func signedPercent(_ percent: Decimal) -> String {
        let rounded = DecimalText.roundHalfUp(percent, scale: 2)
        return (rounded > 0 ? "+" : "") + Formatting.percent(rounded)
    }

    static func checksPassed(_ language: Language) -> String {
        language("같은 조건인지 6가지를 확인했어요", "Six checks passed")
    }

    static func seeCalculation(_ language: Language) -> String { language("계산 보기", "See the calculation") }

    // MARK: - Calculation (board 6b)

    static func formula(_ language: Language) -> String { language("식", "Formula") }

    /// Draft: the growth formula, written out.
    static func growthFormula(_ language: Language) -> String {
        language("(올해 − 작년) ÷ 작년 × 100", "(this year − last year) ÷ last year × 100")
    }

    /// Draft: the margin formula, written out for the calculation.
    static func marginFormulaWritten(_ language: Language) -> String {
        language("영업이익 ÷ 매출 × 100", "operating income ÷ revenue × 100")
    }

    /// Draft.
    static func inputs(_ language: Language) -> String { language("두 숫자", "The two figures") }
    /// Draft.
    static func difference(_ language: Language) -> String { language("차이", "Difference") }
    static func checks(_ language: Language) -> String { language("확인한 조건", "Checks passed") }

    /// `단위: 원 · 소수 셋째 자리에서 반올림` (board 6b). The English names the half-up
    /// rule (comparison-rules.md, Rounding).
    static func unitAndRounding(_ unit: String, _ language: Language) -> String {
        language("단위: \(unitName(unit, language))" + Copy.dot + "소수 셋째 자리에서 반올림",
                 "Unit: \(unitName(unit, language))" + Copy.dot + "rounded half up to two decimals")
    }

    static func unitName(_ unit: String, _ language: Language) -> String {
        switch unit {
        case "KRW": language("원", "KRW")
        case "USD": language("달러", "USD")
        case "KRW_PER_SHARE": language("주당 원", "KRW per share")
        case "USD_PER_SHARE": language("주당 달러", "USD per share")
        default: unit
        }
    }

    /// Draft: where an input comes from: `사업보고서 (2025.12) · 2026년 3월 10일 공시`.
    static func inputSource(_ filing: Filing, _ language: Language) -> String {
        Titles.title(for: filing, language: language) + Copy.dot + Copy.filedOn(filing.filedOn, language)
    }

    /// `두 숫자 모두 사업보고서 (2025.12)에서 가져왔어요.` (board 6b).
    static func bothFrom(_ filing: Filing, _ language: Language) -> String {
        let title = Titles.title(for: filing, language: language)
        return language("두 숫자 모두 \(title)에서 가져왔어요.", "Both figures come from the \(title.lowercasedFirst).")
    }

    static func checkLabel(_ check: CalculationCheck, _ language: Language) -> String {
        switch check {
        case .sameCompany: language("같은 회사", "Same company")
        case .sameMetric: language("같은 지표", "Same metric")
        case .sameCurrency: language("같은 통화", "Same currency")
        case .sameBasis: language("같은 기준", "Same basis")
        case .consecutiveYears: language("이어지는 두 해, 같은 길이", "Consecutive years, same length")
        case .positiveBaseline: language("작년 숫자가 0보다 커요", "Last year is above zero")
        }
    }

    /// Draft: the margin's own checks.
    static func samePeriod(_ language: Language) -> String { language("같은 기간", "Same period") }
    static func revenueAboveZero(_ language: Language) -> String {
        language("매출이 0보다 커요", "Revenue is above zero")
    }

    static func checkValue(_ check: CalculationCheck, _ language: Language) -> String {
        switch check {
        case .sameCompany(let company): Titles.name(of: company, language: language)
        case .sameMetric(let metric): metric.name(language)
        case .sameCurrency(let currency):
            currency.map { currencyName($0, language) + " (\($0))" } ?? language("통화 없음", "No currency")
        case .sameBasis(let basis): basisName(basis, language) ?? basis
        case .consecutiveYears(let prior, let current): periodLengths(prior, current, language)
        case .positiveBaseline(let figure): exact(figure, language)
        }
    }

    /// `12개월씩` / `12 months each`; `52주, 53주` / `52 and 53 weeks` for 52/53-week years.
    static func periodLengths(_ prior: Int, _ current: Int, _ language: Language) -> String {
        if (365...366).contains(prior) && (365...366).contains(current) {
            return language("12개월씩", "12 months each")
        }
        if prior % 7 == 0 && current % 7 == 0 {
            let (a, b) = (prior / 7, current / 7)
            return a == b ? language("\(a)주씩", "\(a) weeks each") : language("\(a)주, \(b)주", "\(a) and \(b) weeks")
        }
        return prior == current ? language("\(prior)일씩", "\(prior) days each")
            : language("\(prior)일, \(current)일", "\(prior) and \(current) days")
    }

    /// A figure's exact value in its stated unit (D83: the figure screens show every digit).
    static func exact(_ figure: Figure, _ language: Language) -> String {
        exact(figure.value, unit: figure.unit, currency: figure.currency, language)
    }

    static func exact(_ value: Decimal, unit: String, currency: String?, _ language: Language) -> String {
        Formatting.stated(value, unit: unit, fallbackCurrency: currency ?? "KRW", language: language)
            ?? Formatting.number(value)
    }

    /// An exact value with a plus sign when above zero, for a difference.
    static func signedExact(_ value: Decimal, unit: String, currency: String?, _ language: Language) -> String {
        (value > 0 ? "+" : "") + exact(value, unit: unit, currency: currency, language)
    }

    /// The operands in full digits: `(300,870,903,000,000 − 258,935,494,000,000) ÷ …`.
    static func growthEquation(_ change: YearOverYear) -> String {
        let (current, prior) = (Formatting.number(change.currentValue), Formatting.number(change.priorValue))
        return "(\(current) \(Formatting.minus) \(prior)) ÷ \(prior) × 100"
    }

    static func marginEquation(_ margin: OperatingMargin) -> String {
        "\(Formatting.number(margin.operatingIncome)) ÷ \(Formatting.number(margin.revenue)) × 100"
    }

    // MARK: - Company picker (board 7A)

    static func pickerTitle(_ language: Language) -> String { language("비교할 회사", "Compare with") }
    static func cancel(_ language: Language) -> String { language("취소", "Cancel") }

    static func pickerNote(_ language: Language) -> String {
        language("증가율과 영업이익률만 비교해요. 금액은 환율로 바꾸지 않아요.",
                 "Only growth rates and operating margins are compared. Amounts are never converted between currencies.")
    }

    /// `한국`, `미국 · 결산월이 다르면 표시해요`.
    static func pickerSection(_ regulator: Regulator, notesYearEnds: Bool, _ language: Language) -> String {
        let market = Copy.market(regulator, language)
        guard notesYearEnds else { return market }
        return market + Copy.dot + language("결산월이 다르면 표시해요", "Other year-ends noted")
    }

    /// `9월 결산` / `Year ends Sep`.
    static func yearEnds(_ month: Int, _ language: Language) -> String {
        language("\(month)월 결산", "Year ends \(shortMonths[month - 1])")
    }

    private static let shortMonths = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    private static let longMonths = [
        "January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
        "November", "December",
    ]

    // MARK: - Compare with another company (board 7)

    static func measureName(_ measure: CrossCompanyMeasure, _ language: Language) -> String {
        switch measure {
        case .growthRate: language("증가율", "Growth")
        case .operatingMargin: language("영업이익률", "Op. margin")
        case .absoluteAmount: language("금액", "Amount")
        }
    }

    /// Draft: what the rates are, above them: `매출 증가율` / `Revenue growth`.
    static func ratesHeading(_ measure: CrossCompanyMeasure?, metric: ReportedMetric?, _ language: Language) -> String {
        switch measure {
        case .growthRate?:
            let name = metric?.name(language) ?? ""
            return language("\(name) 증가율", "\(name) growth")
        case .operatingMargin?: return DerivedMetric.operatingMargin.name(language)
        case .absoluteAmount?, nil: return compareCompany(language)
        }
    }

    /// `삼성전자 · 애플`.
    static func companiesContext(_ companies: [Company], _ language: Language) -> String {
        companies.map { Titles.name(of: $0, language: language) }.joined(separator: Copy.dot)
    }

    /// `2025 회계연도 · 12월 결산 · K-IFRS 연결` / `FY2025 · year ends Dec · K-IFRS consolidated`.
    static func ratePeriod(_ company: Company, fiscalYear: Int?, basis: String?, _ language: Language) -> String {
        var parts: [String] = []
        if let fiscalYear { parts.append(Self.fiscalYear(fiscalYear, language)) }
        let month = company.fiscalYearEndMonth
        parts.append(language("\(month)월 결산", "year ends \(shortMonths[month - 1])"))
        let consolidated = basis == "consolidated" || basis == "consolidated_entity_total"
        parts.append(company.accountingStandard.label + (consolidated ? language(" 연결", " consolidated") : ""))
        return parts.joined(separator: Copy.dot)
    }

    /// Draft: the label of the measure picker.
    static func compareBy(_ language: Language) -> String { language("비교 방식", "Compare by") }

    /// `21.09%p` / `21.09 pp` beside 차이 / Difference (board 7): how far apart the two
    /// rates are, not which one is higher.
    static func rateDifference(_ value: Decimal, _ language: Language) -> String {
        let digits = DecimalText.twoPlaces(DecimalText.roundHalfUp(value, scale: 2))
        return language("\(digits)%p", "\(digits) pp")
    }

    static func rateDifferenceSpoken(_ value: Decimal, _ language: Language) -> String {
        let digits = DecimalText.twoPlaces(DecimalText.roundHalfUp(value, scale: 2))
        return language("차이 \(digits)퍼센트포인트", "Difference, \(digits) percentage points")
    }

    /// The caveat under every cross-company result. Board 7 approved the wording for two
    /// standards and two year-ends; the other three cases are drafts.
    static func caveat(_ caveat: CrossCompanyCaveat, _ language: Language) -> String {
        let standards = caveat.standards.map(\.label).joined(separator: ", ")
        let monthsKo = caveat.yearEndMonths.map { "\($0)월" }.joined(separator: ", ")
        let monthsEn = caveat.yearEndMonths.map { longMonths[$0 - 1] }.joined(separator: ", ")
        let sameName = language("같은 이름의 숫자라도 계산 범위가 조금 다를 수 있어요.",
                                "Figures with the same name can cover slightly different items.")
        switch (caveat.standardsDiffer, caveat.yearEndsDiffer) {
        case (true, true):
            return language("두 회사는 회계 기준(\(standards))과 결산월(\(monthsKo))이 달라요. ",
                            "The two companies use different accounting standards (\(standards)) and year-ends (\(monthsEn)). ")
                + sameName
        case (true, false):
            return language("두 회사는 회계 기준(\(standards))이 달라요. ",
                            "The two companies use different accounting standards (\(standards)). ") + sameName
        case (false, true):
            return language("두 회사는 결산월(\(monthsKo))이 달라서 회계연도가 덮는 달이 서로 달라요. ",
                            "The two companies have different year-ends (\(monthsEn)), so their fiscal years cover different months. ")
                + sameName
        case (false, false):
            let standard = caveat.standards.first?.label ?? ""
            let month = caveat.yearEndMonths.first ?? 12
            return language("두 회사 모두 \(standard)로 보고하고 \(month)월에 결산해요. 그래도 \(sameName)",
                            "Both companies report under \(standard) with a \(longMonths[month - 1]) year-end. Even so, \(sameName.lowercasedFirst)")
        }
    }

    // MARK: - Refusal screen (boards 8, 9, 10)

    /// The approved title for a refusal (board 10); a base of zero or below uses board 9's line.
    static func refusal(_ refusal: Refusal, _ language: Language) -> String {
        if refusal.detail == .nonpositiveBaseline { return baseNotPositive(language) }
        return switch refusal.reason {
        case .ambiguousRequest: language("무엇을 비교할지 골라 주세요", "Choose what to compare")
        case .unsupportedBasis: language("이 기준의 숫자는 비교하지 않아요", "This basis is not compared")
        case .metricOutOfScope: language("이 지표는 다루지 않아요", "This figure is not covered")
        case .missingPeriod: language("비교할 해의 숫자가 없어요", "A year is missing")
        case .incompatibleCurrency:
            language("통화가 달라 금액은 비교하지 않아요", "Different currencies, so amounts are not compared")
        case .incompatibleComparison: language("두 숫자의 조건이 달라요", "The two figures are not alike")
        }
    }

    /// Board 10's body for each reason; nil under board 9's zero-or-below title, which says it.
    static func refusalBody(_ refusal: Refusal, _ language: Language) -> String? {
        if refusal.detail == .nonpositiveBaseline { return nil }
        return switch refusal.reason {
        case .ambiguousRequest:
            language("비교할 숫자와 방식을 하나씩 정하면 계산해 드려요.",
                     "Pick one figure and one way to compare it, and the app will calculate it.")
        case .unsupportedBasis:
            language("연결 기준 숫자만 비교해요. 별도 기준은 포함하는 회사의 범위가 달라요.",
                     "Only consolidated figures are compared. Separate figures cover a different set of companies.")
        case .metricOutOfScope:
            // No-break spaces keep each two-word name on one line.
            language("매출, 영업이익, 순이익, 지배주주\u{00A0}순이익, EPS, 희석\u{00A0}EPS, 영업이익률을 다뤄요.",
                     "The app covers revenue, operating income, net income, net income attributable to owners, EPS, diluted\u{00A0}EPS and operating margin.")
        case .missingPeriod:
            language("공시에서 그 해의 숫자를 찾지 못했어요. 이어지는 두 해가 있어야 비교해요.",
                     "The filings do not include that year. A comparison needs two consecutive years.")
        case .incompatibleCurrency:
            language("원과 달러를 환율로 바꾸지 않아요. 바꾸면 환율이 결과를 정하게 돼요.",
                     "Won and dollars are never converted. A conversion would let the exchange rate decide the result.")
        case .incompatibleComparison:
            language("기간, 기준, 단위 가운데 하나가 달라요. 작년 숫자가 0 이하이면 증가율도 계산하지 않아요.",
                     "Their period, basis or unit differs. When last year is zero or below, there is no growth rate either.")
        }
    }

    /// Draft except the currency line (board 8): the short reason under the explanation.
    static func refusalCode(_ reason: RefusalReason, _ language: Language) -> String {
        let text = switch reason {
        case .ambiguousRequest: language("비교할 것이 정해지지 않았어요", "nothing chosen to compare")
        case .unsupportedBasis: language("연결 기준이 아니에요", "not consolidated")
        case .metricOutOfScope: language("다루지 않는 지표예요", "figure not covered")
        case .missingPeriod: language("한 해의 숫자가 없어요", "a year is missing")
        case .incompatibleCurrency: language("통화가 달라요", "different currencies")
        case .incompatibleComparison: language("조건이 달라요", "conditions differ")
        }
        return language("사유: ", "Reason: ") + text
    }

    /// Draft: the one sentence filled from data (board 10: company names, currencies, years).
    static func refusalReason(_ explanation: RefusalExplanation, _ language: Language) -> String {
        let names = explanation.companies.map { Titles.name(of: $0, language: language) }
        let first = explanation.companies.first
        let metric = explanation.metric?.name(language)
        let refusal = explanation.refusal
        switch refusal.reason {
        case .ambiguousRequest:
            if case .company = explanation.context, names.count == 2 {
                return language("\(Korean.and(names[0]))\(names[1])의 무엇을 비교할지 정해지지\u{00A0}않았어요.",
                                "No way to compare \(names[0]) and \(names[1]) was chosen.")
            }
            return language("어떤 숫자를 비교할지 정해지지\u{00A0}않았어요.", "No figure was chosen.")
        case .unsupportedBasis:
            let name = first.map { Titles.name(of: $0, language: language) } ?? ""
            let what = metric ?? language("숫자", "figures")
            return language("\(name)의 \(what) 숫자는 연결 기준이 아니에요.",
                            "\(possessive(name)) \(what.lowercasedFirst) figures are not on a consolidated basis.")
        case .metricOutOfScope:
            if refusal.detail == .metricNotSupportedForKind {
                return language("영업이익률은 이미 비율이라 증가율을 계산하지 않아요.",
                                "Operating margin is already a rate, so it has no growth rate.")
            }
            return language("요청한 지표는 앱이 다루는 목록에 없어요.", "The requested figure is not one the app covers.")
        case .missingPeriod:
            let missing = explanation.missing
            let company = explanation.companies.first { $0.id == missing?.companyID } ?? first
            let name = company.map { Titles.name(of: $0, language: language) } ?? ""
            let what = (missing?.metric ?? explanation.metric)?.name(language) ?? language("숫자", "figure")
            guard let year = missing?.fiscalYear else {
                return language("\(name)의 \(what) 숫자가 공시에 없어요.",
                                "The filings on file have no \(what.lowercasedFirst) for \(name).")
            }
            return language("\(name)의 \(fiscalYear(year, .ko)) \(what) 숫자가 공시에 없어요.",
                            "The filings on file have no \(fiscalYear(year, .en)) \(what.lowercasedFirst) for \(name).")
        case .incompatibleCurrency:
            guard explanation.companies.count == 2 else {
                return language("두 숫자의 통화가 달라요.", "The two figures are in different currencies.")
            }
            let (a, b) = (explanation.companies[0], explanation.companies[1])
            return language(
                "\(Korean.topic(Titles.name(of: a, language: .ko))) \(currencyWord(a.currency, .ko)), \(Korean.topic(Titles.name(of: b, language: .ko))) \(currencyWord(b.currency, .ko))로 보고해요.",
                "\(Titles.name(of: a, language: .en)) reports in \(currencyWord(a.currency, .en)) and \(Titles.name(of: b, language: .en)) in \(currencyWord(b.currency, .en)).")
        case .incompatibleComparison:
            if let baseline = explanation.baseline,
               let company = explanation.companies.first(where: { $0.id == baseline.companyID }) {
                let name = Titles.name(of: company, language: language)
                let value = exact(baseline, language)
                return language(
                    "\(name)의 \(fiscalYear(baseline.fiscalYear, .ko)) \(Korean.topic(baseline.metric.name(.ko))) \(Korean.copula(value)).",
                    "\(possessive(name)) \(baseline.metric.name(.en).lowercasedFirst) for \(fiscalYear(baseline.fiscalYear, .en)) was \(value).")
            }
            if refusal.detail == .absoluteAmountAcrossCompanies, names.count == 2 {
                return language("\(Korean.and(names[0]))\(names[1])의 금액은 나란히 놓지 않아요.",
                                "Amounts of \(names[0]) and \(names[1]) are not set side by side.")
            }
            let name = first.map { Titles.name(of: $0, language: language) } ?? ""
            let what = metric ?? language("숫자", "figures")
            return language("\(name)의 \(what) 두 해 숫자에서 조건 하나가 맞지 않아요.",
                            "One condition differs between the two years of \(possessive(name)) \(what.lowercasedFirst).")
        }
    }

    private static func currencyWord(_ currency: String, _ language: Language) -> String {
        switch currency {
        case "KRW": language("원", "won")
        case "USD": language("달러", "dollars")
        default: currency
        }
    }

    private static func possessive(_ name: String) -> String {
        name.hasSuffix("s") ? name + "’" : name + "’s"
    }

    static func insteadHeading(_ language: Language) -> String {
        language("대신 할 수 있는 비교", "You can compare instead")
    }

    /// Board 10's action for each reason, board 8's rows for another measure.
    /// Draft for a base of zero or below: the years themselves are what is left to see.
    static func actionLabel(_ action: RefusalAction, reason: RefusalReason, detail: RefusalDetail? = nil,
                            metric: ReportedMetric?, _ language: Language) -> String {
        switch action {
        case .chooseFigure: return language("지표 고르기", "Choose a figure")
        case .coveredFigures: return language("다루는 지표 보기", "See covered figures")
        case .showYears where detail == .nonpositiveBaseline:
            return language("연도별 숫자 보기", "See the figures by year")
        case .showYears:
            return switch reason {
            case .unsupportedBasis: language("연결 기준으로 보기", "View consolidated figures")
            case .incompatibleComparison: language("조건이 같은 숫자로 보기", "Compare figures that match")
            default: language("있는 해의 숫자 보기", "See the years on file")
            }
        case .compare(.operatingMargin): return language("영업이익률 비교", "Operating margin")
        case .compare(.growthRate):
            let name = metric?.name(language) ?? ""
            return language("\(name) 증가율 비교", "\(name) growth")
        case .compare(.absoluteAmount): return measureName(.absoluteAmount, language)
        }
    }
}

/// Korean particles that follow the last syllable of a name.
enum Korean {
    /// True when the word, read aloud, ends in a final consonant (받침). A Hangul syllable
    /// goes by its spelling and a digit by its reading (`3` 삼, `2` 이). A Latin letter
    /// counts as a consonant ending only for L, M and N (엘, 엠, 엔): `SDI` reads 에스디아이,
    /// and a final R is read as in `NAVER` (네이버). Nil for anything else.
    static func hasFinalConsonant(_ word: String) -> Bool? {
        guard let last = word.uppercased().unicodeScalars.last else { return nil }
        if (0xAC00...0xD7A3).contains(last.value) { return (last.value - 0xAC00) % 28 != 0 }
        if "013678".unicodeScalars.contains(last) { return true }
        if "2459".unicodeScalars.contains(last) { return false }
        if "LMN".unicodeScalars.contains(last) { return true }
        if ("A"..."Z").contains(String(last)) { return false }
        return nil
    }

    /// `삼성전자는`, `애플은`; `은(는)` after a word that does not end in Hangul.
    static func topic(_ word: String) -> String {
        switch hasFinalConsonant(word) {
        case true?: word + "은"
        case false?: word + "는"
        case nil: word + "은(는)"
        }
    }

    /// `−2,131원이에요`, `−7.49 달러예요`.
    static func copula(_ word: String) -> String {
        hasFinalConsonant(word) == false ? word + "예요" : word + "이에요"
    }

    /// `삼성전자와 `, `애플과 `, with the space before the next name.
    static func and(_ word: String) -> String {
        switch hasFinalConsonant(word) {
        case true?: word + "과 "
        case false?: word + "와 "
        case nil: word + "와(과) "
        }
    }
}

extension String {
    /// `Revenue` -> `revenue`, `Annual report` -> `annual report`; leaves `EPS` and `FY2025`.
    var lowercasedFirst: String {
        let letters = Array(self)
        guard letters.count > 1, letters[0].isUppercase, !letters[1].isUppercase else { return self }
        return letters[0].lowercased() + String(letters.dropFirst())
    }
}
