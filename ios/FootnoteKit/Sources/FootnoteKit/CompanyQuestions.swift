import Foundation

// "Ask about this company" (D95): a fixed set of questions, each answered by code from the
// bundle. The flow is question -> `QuestionIntent` -> `CompanyAnswerer` -> `Answer`. A later
// typed-question router may only choose an intent; it never writes an answer or a figure.
// Every sentence is fixed text with no digits (`contracts/company-questions.json`, checked
// by the backend's neutrality guard); figures stay exact `Decimal`s for the app to format.

/// A question a reader can ask about one company, in the order the app offers them.
public enum QuestionIntent: String, CaseIterable, Sendable, Hashable, Identifiable {
    case shouldBuy = "should_buy"
    case fundamentals
    case recentTrend = "recent_trend"
    case profitOrLoss = "profit_or_loss"
    case revenue
    case nextQuarterRevenue = "next_quarter_revenue"

    public var id: String { rawValue }

    /// The question as a reader asks it.
    public func question(_ language: Language) -> String {
        let (ko, en): (String, String) = switch self {
        case .shouldBuy: ("이 주식 사도 될까요?", "Should I buy this?")
        case .fundamentals: ("어떤 사업을 하고 실적은 어때요?", "What are the fundamentals?")
        case .recentTrend: ("최근 흐름은 어때요?", "What's the recent trend?")
        case .profitOrLoss: ("이익을 내나요, 손실을 내나요?", "Does it make or lose money?")
        case .revenue: ("매출은 어때요?", "How is revenue doing?")
        case .nextQuarterRevenue: ("다음 분기 매출은 얼마일까요?", "What's next quarter's revenue?")
        }
        return language == .ko ? ko : en
    }

    /// A question that asks for advice or a prediction. Its answer says what the app does
    /// instead and points to questions the filings can answer.
    public var isDeflected: Bool { self == .shouldBuy || self == .nextQuarterRevenue }
}

/// The fixed sentences answers are made of. None holds a digit or a judgement word; the
/// keys and text match `contracts/company-questions.json`.
public enum AnswerSentence: String, CaseIterable, Sendable, Hashable {
    case noAdvice = "no_advice"
    case reportedFacts = "reported_facts"
    case noEstimates = "no_estimates"
    case outlookFiled = "outlook_filed"
    case noOutlook = "no_outlook"
    case businessMissing = "business_missing"
    case quarterMissing = "quarter_missing"
    case yearMissing = "year_missing"
    case trendScope = "trend_scope"
    case revenueQuarterUp = "revenue_quarter_up"
    case revenueQuarterDown = "revenue_quarter_down"
    case revenueQuarterSame = "revenue_quarter_same"
    case revenueQuarterNotCompared = "revenue_quarter_not_compared"
    case revenueQuarterMissing = "revenue_quarter_missing"
    case revenueYearUp = "revenue_year_up"
    case revenueYearDown = "revenue_year_down"
    case revenueYearSame = "revenue_year_same"
    case revenueYearNotCompared = "revenue_year_not_compared"
    case revenueYearMissing = "revenue_year_missing"
    case profitQuarter = "profit_quarter"
    case lossQuarter = "loss_quarter"
    case breakEvenQuarter = "break_even_quarter"
    case incomeQuarterMissing = "income_quarter_missing"
    case profitYear = "profit_year"
    case lossYear = "loss_year"
    case breakEvenYear = "break_even_year"
    case incomeYearMissing = "income_year_missing"
    case howAnswered = "how_answered"

    public func text(_ language: Language) -> String {
        let (ko, en) = Self.texts[self]!
        return language == .ko ? ko : en
    }

    private static let texts: [AnswerSentence: (String, String)] = [
        .noAdvice: (
            "이 앱은 주식을 사라거나 팔라고 권하지 않아요.",
            "This app doesn't tell you to buy or sell shares."),
        .reportedFacts: (
            "대신 회사가 공시에서 밝힌 사업과 실적을 보여 드려요. 판단은 직접 해 주세요.",
            "Instead, it shows the business and results the company reported in its filings. The decision is yours."),
        .noEstimates: (
            "이 앱은 이미 끝난 기간의 실적만 보여 줘요. 앞으로의 매출은 추정하지 않아요.",
            "This app shows results for periods that have ended. It doesn't estimate future revenue."),
        .outlookFiled: (
            "회사가 직접 낸 전망 공시가 있어요. 확정된 실적이 아니라 회사가 스스로 밝힌 내용이에요.",
            "The company filed its own outlook. It is what the company said about the future, not a reported result."),
        .noOutlook: (
            "이 회사가 낸 전망 공시는 앱에 없어요.",
            "The app has no outlook filing from this company."),
        .businessMissing: (
            "회사가 밝힌 사업 설명이 아직 앱에 없어요.",
            "The app doesn't have the company's own description of its business yet."),
        .quarterMissing: (
            "이 회사의 분기 보고서가 앱에 없어요.",
            "The app has no quarterly report from this company."),
        .yearMissing: (
            "이 회사의 연간 실적이 앱에 없어요.",
            "The app has no annual figures from this company."),
        .trendScope: (
            "각 기간을 작년 같은 기간과 비교했어요. 더 긴 기간의 흐름은 다루지 않아요.",
            "Each period is compared with the same period a year earlier. The app doesn't cover a longer trend."),
        .revenueQuarterUp: (
            "회사는 최근 분기 매출이 작년 같은 분기보다 늘었다고 보고했어요.",
            "The company reported higher revenue for its latest quarter than for the same quarter a year earlier."),
        .revenueQuarterDown: (
            "회사는 최근 분기 매출이 작년 같은 분기보다 줄었다고 보고했어요.",
            "The company reported lower revenue for its latest quarter than for the same quarter a year earlier."),
        .revenueQuarterSame: (
            "회사는 최근 분기 매출이 작년 같은 분기와 비슷했다고 보고했어요.",
            "The company reported about the same revenue for its latest quarter as for the same quarter a year earlier."),
        .revenueQuarterNotCompared: (
            "최근 분기 매출은 작년 같은 분기와 비교할 수 없어요.",
            "The latest quarter's revenue can't be compared with the same quarter a year earlier."),
        .revenueQuarterMissing: (
            "앱에 있는 최근 분기 보고서에는 매출이 없어요.",
            "The latest quarterly report in the app doesn't state revenue."),
        .revenueYearUp: (
            "회사는 최근 회계연도 매출이 그 전 해보다 늘었다고 보고했어요.",
            "The company reported higher revenue for its latest fiscal year than for the year before."),
        .revenueYearDown: (
            "회사는 최근 회계연도 매출이 그 전 해보다 줄었다고 보고했어요.",
            "The company reported lower revenue for its latest fiscal year than for the year before."),
        .revenueYearSame: (
            "회사는 최근 회계연도 매출이 그 전 해와 비슷했다고 보고했어요.",
            "The company reported about the same revenue for its latest fiscal year as for the year before."),
        .revenueYearNotCompared: (
            "최근 회계연도 매출은 그 전 해와 비교할 수 없어요.",
            "The latest fiscal year's revenue can't be compared with the year before."),
        .revenueYearMissing: (
            "앱에 있는 최근 사업보고서에는 매출이 없어요.",
            "The latest annual report in the app doesn't state revenue."),
        .profitQuarter: (
            "회사는 최근 분기에 순이익을 냈다고 보고했어요.",
            "The company reported a net profit for its latest quarter."),
        .lossQuarter: (
            "회사는 최근 분기에 순손실을 냈다고 보고했어요.",
            "The company reported a net loss for its latest quarter."),
        .breakEvenQuarter: (
            "회사는 최근 분기에 순이익도 순손실도 없었다고 보고했어요.",
            "The company reported neither a net profit nor a net loss for its latest quarter."),
        .incomeQuarterMissing: (
            "앱에 있는 최근 분기 보고서에는 순이익이 없어요.",
            "The latest quarterly report in the app doesn't state net income."),
        .profitYear: (
            "회사는 최근 회계연도에 순이익을 냈다고 보고했어요.",
            "The company reported a net profit for its latest fiscal year."),
        .lossYear: (
            "회사는 최근 회계연도에 순손실을 냈다고 보고했어요.",
            "The company reported a net loss for its latest fiscal year."),
        .breakEvenYear: (
            "회사는 최근 회계연도에 순이익도 순손실도 없었다고 보고했어요.",
            "The company reported neither a net profit nor a net loss for its latest fiscal year."),
        .incomeYearMissing: (
            "앱에 있는 최근 사업보고서에는 순이익이 없어요.",
            "The latest annual report in the app doesn't state net income."),
        .howAnswered: (
            "답은 이 앱에 담긴 공시로 정해진 규칙에 따라 만들어요. 투자 조언이 아니에요.",
            "Answers are built by fixed rules from the filings in this app. They are not investment advice."),
    ]
}

/// What `CompanyAnswerer` returns: parts in reading order, then questions to try next.
public struct Answer: Sendable, Hashable {
    public let intent: QuestionIntent
    public let company: Company
    public let dataAsOf: CivilDate
    public let parts: [AnswerPart]
    /// Questions the filings can answer, offered after a deflected question.
    public let related: [QuestionIntent]

    /// Every filing the answer cites, in the order the parts cite them.
    public var sources: [Filing] {
        var seen: Set<String> = []
        return parts.compactMap(\.source).filter { seen.insert($0.id).inserted }
    }
}

public enum AnswerPart: Sendable, Hashable {
    /// A sentence about what the app does or does not have; it cites no filing.
    case statement(AnswerSentence)
    /// The approved summary lines of one section of a filing, in both languages.
    case summary(AnswerSummary)
    /// Figures from one report, with the sentence that reads them.
    case figures(AnswerFigures)
    /// A sentence that points to one filing, such as the company's own outlook.
    case filing(AnswerSentence, Filing)

    /// The filing this part cites; nil for a statement.
    public var source: Filing? {
        switch self {
        case .statement: nil
        case .summary(let summary): summary.filing
        case .figures(let figures): figures.filing
        case .filing(_, let filing): filing
        }
    }
}

/// Approved summary lines quoted from a filing.
public struct AnswerSummary: Sendable, Hashable {
    public let filing: Filing
    public let section: SummarySection
    let ko: [String]
    let en: [String]

    /// The approved lines in `language`; empty when that language has none.
    public func lines(_ language: Language) -> [String] { language == .ko ? ko : en }
}

/// A span of days, both ends included.
public struct AnswerPeriod: Sendable, Hashable {
    public let start: CivilDate
    public let end: CivilDate
}

/// An exact reported amount.
public struct AnswerAmount: Sendable, Hashable {
    public let value: Decimal
    /// For example `KRW` or `USD`.
    public let unit: String
    public let currency: String?
}

/// One report's figures for its latest period, each with the same period a year earlier.
public struct AnswerFigures: Sendable, Hashable {
    public enum Span: Sendable, Hashable {
        case quarter(fiscalYear: Int, fiscalQuarter: Int)
        case year(fiscalYear: Int)
    }

    public let span: Span
    /// The report the figures come from.
    public let filing: Filing
    /// The sentence that reads the figures; nil when the figures speak for themselves.
    public let statement: AnswerSentence?
    public let period: AnswerPeriod
    /// The same period a year earlier, from the first row that states it.
    public let priorPeriod: AnswerPeriod?
    public let basis: String
    public let rows: [AnswerFigureRow]
}

/// One metric: this period, the same period a year earlier, and the change.
public struct AnswerFigureRow: Sendable, Hashable, Identifiable {
    public let metric: ReportedMetric
    /// Nil when the report does not state the metric; the app then says so, never zero.
    public let current: AnswerAmount?
    public let prior: AnswerAmount?
    /// The change in percent, rounded half-up to two places, or why there is none. Nil
    /// when there is no current figure.
    public let change: Comparison<Decimal>?

    public var id: String { metric.rawValue }
}

/// Answers each `QuestionIntent` from the bundle alone. The same bundle, company and intent
/// always give the same answer.
public enum CompanyAnswerer {
    /// Nil for a company the bundle does not hold.
    public static func answer(_ intent: QuestionIntent, store: BundleStore, companyID: String) -> Answer? {
        guard let company = store.company(id: companyID) else { return nil }
        let reports = Reports(store: store, companyID: companyID)
        let parts: [AnswerPart]
        var related: [QuestionIntent] = []
        switch intent {
        case .shouldBuy:
            parts = [.statement(.noAdvice), .statement(.reportedFacts)]
            related = [.fundamentals, .profitOrLoss, .recentTrend]
        case .fundamentals:
            parts = [reports.business, reports.quarter(Self.mainMetrics, statement: nil)]
        case .recentTrend:
            parts = [
                .statement(.trendScope),
                reports.quarter(Self.mainMetrics, statement: revenueQuarter),
                reports.year(Self.mainMetrics, statement: revenueYear),
            ]
        case .profitOrLoss:
            parts = [
                reports.quarter([.netIncomeAttributable, .operatingIncome], statement: incomeQuarter),
                reports.year([.netIncomeAttributable, .operatingIncome], statement: incomeYear),
            ]
        case .revenue:
            parts = [
                reports.quarter([.revenue], statement: revenueQuarter),
                reports.year([.revenue], statement: revenueYear),
            ]
        case .nextQuarterRevenue:
            let outlook = store.eventFilings(forCompany: companyID).first { $0.category == .outlook }
            parts = [.statement(.noEstimates), outlook.map { .filing(.outlookFiled, $0) } ?? .statement(.noOutlook)]
            related = [.revenue, .recentTrend]
        }
        return Answer(intent: intent, company: company, dataAsOf: store.meta.dataAsOf, parts: parts, related: related)
    }

    /// Revenue, operating income, then net income attributable to owners (or net income
    /// when a report states no attributable figure), as the quarter report shows them.
    static let mainMetrics: [ReportedMetric] = [.revenue, .operatingIncome, .netIncomeAttributable]

    // MARK: - Sentences that read figures

    static func revenueQuarter(_ rows: [AnswerFigureRow]) -> AnswerSentence {
        direction(rows.first { $0.metric == .revenue },
                  up: .revenueQuarterUp, down: .revenueQuarterDown, same: .revenueQuarterSame,
                  notCompared: .revenueQuarterNotCompared, missing: .revenueQuarterMissing)
    }

    static func revenueYear(_ rows: [AnswerFigureRow]) -> AnswerSentence {
        direction(rows.first { $0.metric == .revenue },
                  up: .revenueYearUp, down: .revenueYearDown, same: .revenueYearSame,
                  notCompared: .revenueYearNotCompared, missing: .revenueYearMissing)
    }

    static func incomeQuarter(_ rows: [AnswerFigureRow]) -> AnswerSentence {
        sign(of: rows.first { $0.metric.isNetIncome }?.current,
             profit: .profitQuarter, loss: .lossQuarter, zero: .breakEvenQuarter, missing: .incomeQuarterMissing)
    }

    static func incomeYear(_ rows: [AnswerFigureRow]) -> AnswerSentence {
        sign(of: rows.first { $0.metric.isNetIncome }?.current,
             profit: .profitYear, loss: .lossYear, zero: .breakEvenYear, missing: .incomeYearMissing)
    }

    /// The direction the displayed change shows: the percentage rounded to two places, so a
    /// change shown as `0.00%` reads as about the same.
    private static func direction(
        _ row: AnswerFigureRow?, up: AnswerSentence, down: AnswerSentence, same: AnswerSentence,
        notCompared: AnswerSentence, missing: AnswerSentence
    ) -> AnswerSentence {
        guard let row, row.current != nil, let change = row.change else { return missing }
        guard case .result(let percent) = change else { return notCompared }
        let rounded = DecimalText.roundHalfUp(percent, scale: 2)
        return rounded > 0 ? up : rounded < 0 ? down : same
    }

    private static func sign(
        of amount: AnswerAmount?, profit: AnswerSentence, loss: AnswerSentence, zero: AnswerSentence,
        missing: AnswerSentence
    ) -> AnswerSentence {
        guard let amount else { return missing }
        return amount.value > 0 ? profit : amount.value < 0 ? loss : zero
    }
}

extension ReportedMetric {
    var isNetIncome: Bool { self == .netIncome || self == .netIncomeAttributable }
}

/// The company's newest quarterly and annual reports, read once per answer.
private struct Reports {
    let store: BundleStore
    let quarterPage: QuarterPage?
    let annualPage: AnnualPage?

    init(store: BundleStore, companyID: String) {
        self.store = store
        quarterPage = store.quarterlyFilings(forCompany: companyID).first
            .flatMap { QuarterPage(store: store, filingID: $0.id) }
        annualPage = store.annualFilings(forCompany: companyID).first
            .flatMap { AnnualPage(store: store, filingID: $0.id) }
    }

    /// The newest annual report's approved business section, quoted in both languages.
    var business: AnswerPart {
        guard let page = annualPage else { return .statement(.businessMissing) }
        let ko = page.lines(.business, .ko), en = page.lines(.business, .en)
        guard !ko.isEmpty || !en.isEmpty else { return .statement(.businessMissing) }
        return .summary(AnswerSummary(filing: page.filing, section: .business, ko: ko, en: en))
    }

    /// The newest quarterly report's figures for `metrics`, against the same quarter a year
    /// earlier. A metric the report does not state stays as a row with no figure.
    func quarter(
        _ metrics: [ReportedMetric], statement: (([AnswerFigureRow]) -> AnswerSentence)?
    ) -> AnswerPart {
        guard let page = quarterPage, let first = page.rows.first else { return .statement(.quarterMissing) }
        let rows = metrics.map { metric -> AnswerFigureRow in
            let found = page.rows.first { metric.isNetIncome ? $0.metric.isNetIncome : $0.metric == metric }
            guard let found else { return AnswerFigureRow(metric: metric, current: nil, prior: nil, change: nil) }
            let change: Comparison<Decimal> = switch found.comparison {
            case .result(let result): .result(result.percentChange)
            case .refusal(let refusal): .refusal(refusal)
            }
            return AnswerFigureRow(
                metric: found.metric, current: found.current.amount, prior: found.prior?.amount, change: change)
        }
        let prior = page.priorPeriod.map { AnswerPeriod(start: $0.start, end: $0.end) }
        return .figures(AnswerFigures(
            span: .quarter(fiscalYear: first.current.fiscalYear, fiscalQuarter: first.current.fiscalQuarter),
            filing: page.filing, statement: statement?(rows),
            period: AnswerPeriod(start: first.current.periodStart, end: first.current.periodEnd),
            priorPeriod: prior, basis: first.current.basis, rows: rows))
    }

    /// The newest annual report's figures for `metrics`, against the year before, on the
    /// basis the annual page shows.
    func year(
        _ metrics: [ReportedMetric], statement: (([AnswerFigureRow]) -> AnswerSentence)?
    ) -> AnswerPart {
        guard let page = annualPage, let fiscalYear = page.fiscalYear, let basis = page.basis,
              let first = page.rows.lazy.compactMap(\.current).first
        else { return .statement(.yearMissing) }
        let rows = metrics.map { metric -> AnswerFigureRow in
            // Net income attributable to owners, else net income, as for the quarter.
            let candidates = metric.isNetIncome ? [ReportedMetric.netIncomeAttributable, .netIncome] : [metric]
            let found = candidates.lazy.compactMap { candidate in
                page.rows.first { $0.metric == candidate && $0.current != nil }
            }.first
            guard let found, let current = found.current else {
                return AnswerFigureRow(metric: metric, current: nil, prior: nil, change: nil)
            }
            let change: Comparison<Decimal> = switch found.comparison {
            case .result(let result)?: .result(result.percentChange)
            case .refusal(let refusal)?: .refusal(refusal)
            case nil: .refusal(Refusal(.missingPeriod, .missingFact))
            }
            return AnswerFigureRow(
                metric: found.metric, current: current.amount, prior: found.prior?.amount, change: change)
        }
        let prior = page.rows.lazy.compactMap(\.prior).first.map { AnswerPeriod(start: $0.periodStart, end: $0.periodEnd) }
        return .figures(AnswerFigures(
            span: .year(fiscalYear: fiscalYear), filing: page.filing, statement: statement?(rows),
            period: AnswerPeriod(start: first.periodStart, end: first.periodEnd),
            priorPeriod: prior, basis: basis, rows: rows))
    }
}

private extension QuarterFigure {
    var amount: AnswerAmount { AnswerAmount(value: value, unit: unit, currency: currency) }
}

private extension Figure {
    var amount: AnswerAmount { AnswerAmount(value: value, unit: unit, currency: currency) }
}
