import FootnoteKit

/// Copy for the source sentence under each summary line (D100).
enum SourceCopy {
    /// The disclosure under a line.
    static func disclosure(count: Int, _ language: Language) -> String {
        language("출처 문장", count > 1 ? "Source sentences" : "Source sentence")
    }

    /// Above the excerpt: the language it is written in and the filing it is from.
    static func caption(excerptLanguage: Language, filingName: String, _ language: Language) -> String {
        let original = switch (excerptLanguage, language) {
        case (.ko, .ko): "한국어 원문"
        case (.en, .ko): "영어 원문"
        case (.ko, .en): "Korean original"
        case (.en, .en): "English original"
        }
        return original + Titles.separator + filingName
    }

    /// A template line (D78) has no sentence of its own in the filing.
    static func template(_ language: Language) -> String {
        language(
            "정해진 문장에 공시 표의 값을 넣어 썼어요.",
            "Written from a fixed sentence with the values in the filing's table.")
    }
}
