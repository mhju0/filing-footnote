/// Closed vocabularies shared with the backend. Case order and raw values match
/// `contracts/financial-vocabulary.json` and `contracts/filing-categories.json`; the
/// contract tests fail when either side drifts.

public enum ReportedMetric: String, CaseIterable, Sendable, Hashable {
    case revenue
    case operatingIncome = "operating_income"
    case netIncome = "net_income"
    case netIncomeAttributable = "net_income_attributable"
    case eps
    case epsDiluted = "eps_diluted"
}

public enum DerivedMetric: String, CaseIterable, Sendable, Hashable {
    case operatingMargin = "operating_margin"
}

public enum PeriodKind: String, CaseIterable, Sendable, Hashable {
    case instant
    case duration
}

public enum Regulator: String, CaseIterable, Sendable, Hashable {
    case dart = "DART"
    case sec = "SEC"
}

public enum FilingKind: String, CaseIterable, Sendable, Hashable {
    case annual
    case event
}

public enum Language: String, CaseIterable, Sendable, Hashable {
    case ko
    case en
}

/// Summary sections a filing can carry (`app.build.model.SUMMARY_SECTIONS`).
public enum SummarySection: String, CaseIterable, Sendable, Hashable {
    /// The three lines of an event filing.
    case summary
    case oneLine = "one_line"
    case business
    case changes
    case risks
}

/// `filing_facts.value_kind`.
public enum FactValueKind: String, CaseIterable, Sendable, Hashable {
    case amount
    case shares
    case ratio
    case date
    case text
}

/// A filing's category: the event categories in contract priority order, then `annual`.
public enum FilingCategory: String, CaseIterable, Sendable, Hashable {
    case earnings
    case unitSales = "unit_sales"
    case buyback
    case dividend
    case capital
    case deal
    case leadership
    case legal
    case outlook
    case shareholderValue = "shareholder_value"
    case meeting
    case operations
    case lending
    case management
    case clarification
    case annual

    public func label(_ language: Language) -> String {
        let (ko, en): (String, String) = switch self {
        case .earnings: ("실적", "Earnings")
        case .unitSales: ("판매 대수", "Unit sales")
        case .buyback: ("자사주", "Buyback")
        case .dividend: ("배당", "Dividend")
        case .capital: ("증자·사채", "Capital")
        case .deal: ("인수·계약", "Deals and contracts")
        case .leadership: ("경영진", "Leadership")
        case .legal: ("소송", "Legal")
        case .outlook: ("회사 전망", "Company outlook")
        case .shareholderValue: ("주주가치", "Shareholder value")
        case .meeting: ("주주총회", "Shareholder meeting")
        case .operations: ("생산·사고", "Operations")
        case .lending: ("대여·보증", "Loans and guarantees")
        case .management: ("경영사항", "Management matters")
        case .clarification: ("해명", "Clarification")
        case .annual: ("사업보고서", "Annual report")
        }
        return language == .ko ? ko : en
    }
}

/// A notice's category (`notice_categories`): listed on one grouped row, never summarised.
public enum NoticeCategory: String, CaseIterable, Sendable, Hashable {
    case irEvent = "ir_event"
    case recordDate = "record_date"
    case meetingNotice = "meeting_notice"
    case earningsNotice = "earnings_notice"
    case auditReport = "audit_report"
    case governanceReport = "governance_report"
    case sustainabilityReport = "sustainability_report"
    case complianceProgram = "compliance_program"
    case noticeOnly = "notice_only"
    case marketAction = "market_action"

    public func label(_ language: Language) -> String {
        let (ko, en): (String, String) = switch self {
        case .irEvent: ("IR 행사", "Investor event")
        case .recordDate: ("기준일", "Record date")
        case .meetingNotice: ("주주총회 소집", "Meeting notice")
        case .earningsNotice: ("실적 발표 예고", "Results date")
        case .auditReport: ("감사보고서", "Audit report")
        case .governanceReport: ("지배구조 보고서", "Governance report")
        case .sustainabilityReport: ("지속가능경영 보고서", "Sustainability report")
        case .complianceProgram: ("공정거래 자율준수", "Compliance program")
        case .noticeOnly: ("기타 안내", "Other notice")
        case .marketAction: ("거래소 조회", "Exchange inquiry")
        }
        return language == .ko ? ko : en
    }
}
