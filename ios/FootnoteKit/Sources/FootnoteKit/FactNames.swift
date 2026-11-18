/// Plain row names for the facts a filing page lists, keyed by the fact's origin, with the
/// order the rows appear in. `contracts/filing-facts.json` holds the formal names (the
/// regulator's field names); the screen uses these shorter ones (board 12A: 처분 주식 수,
/// 주당 가격, 처분 금액). A `_start`/`_end` pair is one row: `FilingPage` folds it.
public enum FactNames {
    public struct Name: Sendable, Hashable {
        public let ko: String
        public let en: String
        /// For a period start: the name of the whole period when it ends on another day.
        public let periodKo: String?
        public let periodEn: String?

        init(_ ko: String, _ en: String, period: (String, String)? = nil) {
            self.ko = ko
            self.en = en
            periodKo = period?.0
            periodEn = period?.1
        }

        public func text(_ language: Language) -> String { language == .ko ? ko : en }

        public func periodText(_ language: Language) -> String? {
            language == .ko ? periodKo : periodEn
        }
    }

    /// In row order. An origin missing here is not listed on the page (purposes, methods and
    /// other free text belong to the summary sentences).
    static let ordered: [(origin: String, name: Name)] = [
        // Treasury share purchase (tsstkAqDecsn)
        ("opendart:tsstkAqDecsn.aqpln_stk_ostk", Name("취득 주식 수 (보통주)", "Shares to buy, common")),
        ("opendart:tsstkAqDecsn.aqpln_stk_estk", Name("취득 주식 수 (기타주)", "Shares to buy, other classes")),
        ("opendart:tsstkAqDecsn.aqpln_prc_ostk", Name("취득 금액 (보통주)", "Amount, common")),
        ("opendart:tsstkAqDecsn.aqpln_prc_estk", Name("취득 금액 (기타주)", "Amount, other classes")),
        ("opendart:tsstkAqDecsn.aqexpd_bgd",
         Name("취득 예정일", "Purchase date", period: ("취득 기간", "Purchase period"))),
        ("opendart:tsstkAqDecsn.aq_dd", Name("이사회 결정일", "Board decision")),
        // Treasury share disposal (tsstkDpDecsn)
        ("opendart:tsstkDpDecsn.dppln_stk_ostk", Name("처분 주식 수", "Shares")),
        ("opendart:tsstkDpDecsn.dppln_stk_estk", Name("처분 주식 수 (기타주)", "Shares, other classes")),
        ("opendart:tsstkDpDecsn.dpstk_prc_ostk", Name("주당 가격", "Price per share")),
        ("opendart:tsstkDpDecsn.dppln_prc_ostk", Name("처분 금액", "Amount")),
        ("opendart:tsstkDpDecsn.dpprpd_bgd",
         Name("처분 예정일", "Disposal date", period: ("처분 기간", "Disposal period"))),
        ("opendart:tsstkDpDecsn.dp_dd", Name("이사회 결정일", "Board decision")),
        // Share issue for cash (piicDecsn)
        ("opendart:piicDecsn.nstk_ostk_cnt", Name("새로 내는 주식 (보통주)", "New shares, common")),
        ("opendart:piicDecsn.nstk_estk_cnt", Name("새로 내는 주식 (기타주)", "New shares, other classes")),
        ("opendart:piicDecsn.bfic_tisstk_ostk", Name("증자 전 주식 수 (보통주)", "Shares before the issue, common")),
        ("opendart:piicDecsn.bfic_tisstk_estk", Name("증자 전 주식 수 (기타주)", "Shares before the issue, other classes")),
        ("opendart:piicDecsn.fv_ps", Name("1주당 액면가", "Par value per share")),
        ("opendart:piicDecsn.fdpp_fclt", Name("시설 자금", "For facilities")),
        ("opendart:piicDecsn.fdpp_bsninh", Name("영업 양수 자금", "For a business acquisition")),
        ("opendart:piicDecsn.fdpp_op", Name("운영 자금", "For operations")),
        ("opendart:piicDecsn.fdpp_dtrp", Name("채무 상환 자금", "For debt repayment")),
        ("opendart:piicDecsn.fdpp_ocsa", Name("다른 회사 증권 취득 자금", "For other companies' securities")),
        ("opendart:piicDecsn.fdpp_etc", Name("기타 자금", "For other uses")),
        // Dividend table (dartdoc:dividend)
        ("dartdoc:dividend.dividend_per_share_common", Name("주당 배당금 (보통주)", "Dividend per share, common")),
        ("dartdoc:dividend.dividend_per_share_preferred", Name("주당 배당금 (종류주)", "Dividend per share, other classes")),
        ("dartdoc:dividend.dividend_yield_common", Name("시가 배당률 (보통주)", "Dividend yield, common")),
        ("dartdoc:dividend.dividend_total", Name("배당금 총액", "Total dividend")),
        ("dartdoc:dividend.dividend_record_date", Name("배당 기준일", "Record date")),
        ("dartdoc:dividend.dividend_payment_date", Name("지급 예정일", "Planned payment date")),
        ("dartdoc:dividend.dividend_yield_preferred", Name("시가 배당률 (종류주)", "Dividend yield, other classes")),
        ("dartdoc:dividend.dividend_decision_date", Name("이사회 결정일", "Board decision")),
        // SEC 8-K (submissions)
        ("sec:submissions.items", Name("보고 항목", "Items reported")),
        ("sec:submissions.reportDate", Name("사건 발생일", "Date of the event")),
    ]

    static let byOrigin: [String: Name] = Dictionary(
        uniqueKeysWithValues: ordered.map { ($0.origin, $0.name) })

    static let rank: [String: Int] = Dictionary(
        uniqueKeysWithValues: ordered.enumerated().map { ($1.origin, $0) })

    public static func name(origin: String) -> Name? { byOrigin[origin] }
}
