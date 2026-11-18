/// Rule-based display titles. A bundle stores each filing's title as the regulator wrote it
/// (`주요사항보고서(자기주식처분결정)`, `8-K`); the screens show a short title in the reader's
/// language instead, built only from the report name, the SEC item numbers and the period
/// label. Nothing is inferred from the filing's text. An unknown DART report name keeps its
/// original wording in Korean and falls back to the category label in English.
public enum Titles {
    // MARK: - Filings

    public static func title(for filing: Filing, language: Language) -> String {
        switch (filing.kind, regulator(of: filing)) {
        case (.annual, .dart): dartAnnual(filing, language)
        case (.annual, .sec): secAnnual(filing, language)
        case (.event, .dart): dartEvent(filing, language)
        case (.event, .sec): secEvent(filing, language)
        }
    }

    private static func regulator(of filing: Filing) -> Regulator {
        filing.id.hasPrefix("sec:") ? .sec : .dart
    }

    /// `FY2025` -> `2025`; nil when the label has another shape.
    private static func fiscalYear(_ filing: Filing) -> String? {
        guard let label = filing.periodLabel, label.hasPrefix("FY") else { return nil }
        let year = label.dropFirst(2)
        return year.count == 4 && year.allSatisfy(\.isNumber) ? String(year) : nil
    }

    private static func dartAnnual(_ filing: Filing, _ language: Language) -> String {
        guard let year = fiscalYear(filing) else {
            return language == .ko ? "사업보고서" : "Annual report"
        }
        return language == .ko ? "\(year)년 사업보고서" : "Annual report, FY\(year)"
    }

    private static func secAnnual(_ filing: Filing, _ language: Language) -> String {
        let form = filing.form
        guard let year = fiscalYear(filing) else {
            return language == .ko ? "연차보고서 (\(form))" : "Annual report (\(form))"
        }
        return language == .ko
            ? "\(year) 회계연도 연차보고서 (\(form))" : "Annual report, FY\(year) (\(form))"
    }

    // MARK: DART events

    /// Markers DART appends to a report name that say how it was filed, not what it is.
    private static let filingMarkers = ["(공정공시)", "(자율공시)", "(안내공시)"]
    private static let subsidiaryMarker = "(종속회사의주요경영사항)"
    private static let majorMattersPrefix = "주요사항보고서("

    /// A DART report name split into the part the table knows and the extras around it.
    struct DartName: Equatable {
        var base: String
        var subsidiary = false
        /// Text DART adds after a space, such as `(2025년 재공시)`.
        var detail: String?
    }

    static func parseDart(_ title: String) -> DartName {
        var text = title.trimmingCharacters(in: .whitespaces)
        // Status prefixes such as [기재정정] or [첨부추가]: the corrected tag says it instead.
        while text.hasPrefix("["), let close = text.firstIndex(of: "]") {
            text = String(text[text.index(after: close)...]).trimmingCharacters(in: .whitespaces)
        }
        var detail: String?
        if let space = text.firstIndex(of: " ") {
            let rest = text[space...].trimmingCharacters(in: .whitespaces)
            if rest.hasPrefix("("), rest.hasSuffix(")") {
                let inner = rest.dropFirst().dropLast().trimmingCharacters(in: .whitespaces)
                detail = inner.isEmpty ? nil : inner
                text = String(text[..<space])
            }
        }
        if text.hasPrefix(majorMattersPrefix), text.hasSuffix(")") {
            text = String(text.dropFirst(majorMattersPrefix.count).dropLast())
        }
        var subsidiary = false
        var stripped = true
        while stripped {
            stripped = false
            for marker in filingMarkers + [subsidiaryMarker] where text.hasSuffix(marker) {
                if marker == subsidiaryMarker { subsidiary = true }
                text = String(text.dropLast(marker.count))
                stripped = true
            }
        }
        return DartName(base: text, subsidiary: subsidiary, detail: detail)
    }

    /// Known DART report names (after `parseDart`) with their Korean and English titles.
    static let dartNames: [String: (ko: String, en: String)] = [
        "연결재무제표기준영업(잠정)실적": ("잠정 실적 (연결)", "Preliminary results, consolidated"),
        "영업(잠정)실적": ("잠정 실적", "Preliminary results"),
        "풍문또는보도에대한해명(미확정)": ("보도에 대한 해명 (미확정)", "Response to a press report, unconfirmed"),
        "풍문또는보도에대한해명": ("보도에 대한 해명", "Response to a press report"),
        "조회공시요구(풍문또는보도)에대한답변(미확정)":
            ("거래소 조회에 대한 답변 (미확정)", "Reply to an exchange inquiry, unconfirmed"),
        "조회공시요구(풍문또는보도)에대한답변": ("거래소 조회에 대한 답변", "Reply to an exchange inquiry"),
        "기타경영사항": ("기타 경영 사항", "Other management matter"),
        "투자판단관련주요경영사항": ("투자 판단 관련 경영 사항", "Management matter for investors"),
        "현금ㆍ현물배당결정": ("현금·현물 배당 결정", "Dividend decision"),
        "장래사업ㆍ경영계획": ("사업·경영 계획", "Business plan"),
        "영업실적등에대한전망": ("실적 전망", "Earnings outlook"),
        "연결재무제표기준영업실적등에대한전망": ("실적 전망 (연결)", "Earnings outlook, consolidated"),
        "자기주식처분결정": ("자사주 처분 결정", "Treasury share disposal"),
        "자기주식취득결정": ("자사주 취득 결정", "Treasury share purchase"),
        "자기주식취득신탁계약체결결정": ("자사주 신탁 계약 체결", "Treasury share trust signed"),
        "자기주식취득신탁계약해지결정": ("자사주 신탁 계약 해지", "Treasury share trust ended"),
        "주식소각결정": ("주식 소각 결정", "Share cancellation"),
        "수시공시의무관련사항": ("수시 공시 의무 관련 사항", "Disclosure under listing rules"),
        "타인에대한채무보증결정": ("채무 보증 결정", "Debt guarantee"),
        "타인에대한담보제공결정": ("담보 제공 결정", "Collateral provided"),
        "금전대여결정": ("금전 대여 결정", "Loan decision"),
        "유상증자결정": ("유상 증자 결정", "Share issue for cash"),
        "유상증자또는주식관련사채등의청약결과": ("증자·사채 청약 결과", "Share or bond subscription results"),
        "유상증자또는주식관련사채등의발행결과": ("증자·사채 발행 결과", "Share or bond issue results"),
        "유상증자신주발행가액": ("신주 발행 가액", "New share issue price"),
        "단일판매ㆍ공급계약체결": ("판매·공급 계약 체결", "Sales or supply contract"),
        "타법인주식및출자증권취득결정": ("다른 회사 주식 취득 결정", "Purchase of shares in another company"),
        "타법인주식및출자증권처분결정": ("다른 회사 주식 처분 결정", "Sale of shares in another company"),
        "타법인주식및출자증권양수결정": ("다른 회사 주식 양수 결정", "Acquisition of shares in another company"),
        "타법인주식및출자증권양도결정": ("다른 회사 주식 양도 결정", "Transfer of shares in another company"),
        "주식교환ㆍ이전결정": ("주식 교환·이전 결정", "Share exchange or transfer"),
        "중대재해발생": ("중대 재해 발생", "Serious industrial accident"),
        "생산중단": ("생산 중단", "Production halted"),
        "생산재개": ("생산 재개", "Production resumed"),
        "정기주주총회결과": ("정기 주주총회 결과", "Annual shareholder meeting results"),
        "임시주주총회결과": ("임시 주주총회 결과", "Extraordinary shareholder meeting results"),
        "대표이사(대표집행임원)변경": ("대표이사 변경", "Change of chief executive"),
        "기업가치제고계획": ("기업 가치 제고 계획", "Corporate value-up plan"),
    ]

    private static func dartEvent(_ filing: Filing, _ language: Language) -> String {
        let name = parseDart(filing.titleOriginal)
        var titles = dartNames[name.base]
        // One report name covers both monthly unit sales and quarterly results.
        if name.base == "영업(잠정)실적" && filing.category == .unitSales {
            titles = ("판매 실적 (잠정)", "Preliminary unit sales")
        }
        switch language {
        case .ko:
            var title = titles?.ko ?? name.base
            if name.subsidiary { title += " (자회사)" }
            if let detail = name.detail { title += " · " + detail }
            return title
        case .en:
            let title = titles?.en ?? filing.category.label(.en)
            return name.subsidiary ? title + " (subsidiary)" : title
        }
    }

    // MARK: SEC events

    /// SEC 8-K item names, by item number.
    static let secItems: [String: (ko: String, en: String)] = [
        "1.01": ("주요 계약 체결", "Material agreement"),
        "1.02": ("주요 계약 종료", "Agreement terminated"),
        "1.05": ("사이버 보안 사고", "Cybersecurity incident"),
        "2.01": ("자산 인수·처분 완료", "Acquisition or disposal completed"),
        "2.02": ("실적 발표", "Results of operations"),
        "2.03": ("채무 발생", "New debt obligation"),
        "3.03": ("주주 권리 변경", "Change to shareholder rights"),
        "5.02": ("임원 변경", "Officer or director change"),
        "5.03": ("정관 변경", "Charter or bylaw change"),
        "5.07": ("주주총회 투표 결과", "Shareholder vote results"),
    ]

    /// Items that name the category the filing was sorted into, in order. A filing whose
    /// category no listed item names (a dividend or buyback told under 8.01, say) gets the
    /// category's own title, so the title never disagrees with the tag beside it.
    private static let categoryItems: [FilingCategory: [String]] = [
        .earnings: ["2.02"], .unitSales: ["2.02"], .leadership: ["5.02"], .meeting: ["5.07"],
        .deal: ["2.01", "1.01", "1.02"], .capital: ["2.03", "3.03", "1.01"],
        .management: ["5.03"], .legal: ["1.05"],
    ]

    private static func secEvent(_ filing: Filing, _ language: Language) -> String {
        let items = (filing.secItems ?? "").split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespaces) }
        let preferred = categoryItems[filing.category] ?? []
        let item = preferred.first { items.contains($0) }
        let form = filing.form
        if let item, var names = secItems[item] {
            if item == "2.02" && filing.category == .unitSales {
                names = ("판매·인도 실적", "Production and deliveries")
            }
            return (language == .ko ? names.ko : names.en) + " (\(form))"
        }
        return language == .ko
            ? "\(filing.category.label(.ko)) 관련 공시 (\(form))"
            : "\(filing.category.label(.en)) filing (\(form))"
    }

    // MARK: - Notices

    public static func title(for notice: Notice, language: Language) -> String {
        let (ko, en): (String, String) = switch notice.category {
        case .irEvent: ("IR 행사 안내", "Investor event notice")
        case .recordDate: ("기준일 설정", "Record date set")
        case .meetingNotice: ("주주총회 소집", "Shareholder meeting called")
        case .earningsNotice: ("실적 발표 예고", "Results date announced")
        case .auditReport: ("감사보고서 제출", "Audit report filed")
        case .governanceReport: ("기업 지배구조 보고서", "Corporate governance report")
        case .sustainabilityReport: ("지속가능경영 보고서", "Sustainability report")
        case .complianceProgram: ("공정거래 자율준수 프로그램 운영 현황", "Fair trade compliance program")
        case .noticeOnly: ("기타 안내", "Other notice")
        case .marketAction: ("거래소 조회 요구", "Exchange inquiry")
        }
        return language == .ko ? ko : en
    }

    // MARK: - Company names

    /// Short English names. The bundle's `name_en` is the regulator's registered name
    /// (`HYUNDAI MOTOR CO`), which reads as shouting in a title.
    static let englishNames: [String: String] = [
        "000270": "Kia", "000660": "SK hynix", "005380": "Hyundai Motor",
        "005930": "Samsung Electronics", "006400": "Samsung SDI", "035420": "NAVER",
        "051910": "LG Chem", "066570": "LG Electronics", "207940": "Samsung Biologics",
        "AAPL": "Apple", "AMZN": "Amazon", "COST": "Costco", "GOOGL": "Alphabet",
        "META": "Meta", "MSFT": "Microsoft", "NVDA": "NVIDIA", "TSLA": "Tesla", "WMT": "Walmart",
    ]

    /// The company's name for a title: `name_ko` in Korean, the short English name (or
    /// `name_en` for a company not in the table) in English.
    public static func name(of company: Company, language: Language) -> String {
        language == .ko ? company.nameKo : englishNames[company.ticker] ?? company.nameEn
    }
}
