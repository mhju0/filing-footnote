import FootnoteKit
import Testing
@testable import Footnote

@Suite("Source sentence copy")
struct SourceCopyTests {
    /// The source sentence disclosure (D101): the filing's language and name above the excerpt.
    @Test func sourceSentence() {
        #expect(SourceCopy.disclosure(count: 2, .ko) == "출처 문장")
        #expect(SourceCopy.disclosure(count: 1, .en) == "Source sentence")
        #expect(SourceCopy.disclosure(count: 2, .en) == "Source sentences")
        let name = "자기주식 취득 결정"
        #expect(SourceCopy.caption(excerptLanguage: .ko, filingName: name, .ko) == "한국어 원문\u{00A0}· 자기주식 취득 결정")
        #expect(SourceCopy.caption(excerptLanguage: .ko, filingName: name, .en) == "Korean original\u{00A0}· 자기주식 취득 결정")
        #expect(SourceCopy.caption(excerptLanguage: .en, filingName: "8-K", .ko) == "영어 원문\u{00A0}· 8-K")
        for language in [Language.ko, .en] {
            let hasDigit = SourceCopy.template(language).contains { $0.isNumber }
            #expect(!hasDigit)
        }
    }
}
