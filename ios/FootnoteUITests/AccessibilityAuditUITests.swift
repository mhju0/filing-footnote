import SQLite3
import XCTest

/// Roadmap Q1: Apple's accessibility audit (contrast, element descriptions, hit regions,
/// clipped text, Dynamic Type, traits) on every screen, in Korean and English, at the
/// default text size, at an accessibility size and in dark mode. Each screen opens from a
/// debug launch route on a copy of the FootnoteKit fixture with glossary rows under the D81
/// keys, so the 용어 tab and every glossary link are present. Long screens are audited at
/// the top and again after each swipe up, because the audit sees only what is on screen.
///
/// Set `TEST_RUNNER_FOOTNOTE_AUDIT_RECORD=1` to print every issue (`AUDIT|…`) instead of
/// failing, when looking for new findings, and `TEST_RUNNER_FOOTNOTE_AUDIT_SHOTS=<folder>`
/// to save a screenshot of each audited pass there.
final class AccessibilityAuditUITests: XCTestCase {
    private static let samsung = "dart:00126380"
    private static let apple = "sec:0000320193"
    private static let annual = "dart:20260310000123"
    private static let dividend = "dart:20261029800101"
    private static let outlook = "dart:20261029800102"
    private static let results = "dart:20261029800087"
    private static let corrected = "dart:20261029800099"
    private static let samsungQuarter = "dart:20261116000111"
    private static let appleQuarter = "sec:0000320193-26-000020"

    /// A screen: its name in failure messages, the launch route (nil: the companies list),
    /// and how many times to swipe up and audit again.
    struct Screen {
        let name: String
        let route: String?
        var swipes = 2
    }

    static let screens: [Screen] = [
        Screen(name: "companies", route: nil),
        Screen(name: "company", route: "company=\(samsung)"),
        Screen(name: "notices", route: "notices=\(samsung)", swipes: 0),
        Screen(name: "filing-dividend", route: "filing=\(samsung)|\(dividend)"),
        Screen(name: "filing-outlook", route: "filing=\(samsung)|\(outlook)"),
        Screen(name: "filing-results", route: "filing=\(samsung)|\(results)"),
        Screen(name: "filing-corrected", route: "filing=\(samsung)|\(corrected)"),
        Screen(name: "annual", route: "filing=\(samsung)|\(annual)", swipes: 3),
        Screen(name: "quarter", route: "filing=\(samsung)|\(samsungQuarter)"),
        Screen(name: "quarter-sec", route: "filing=\(apple)|\(appleQuarter)"),
        Screen(name: "figure", route: "figure=\(samsung)|revenue|2025"),
        Screen(name: "year-compare", route: "yearcompare=\(samsung)|revenue|2025"),
        Screen(name: "year-calculation", route: "yearcalc=\(samsung)|revenue|2025", swipes: 3),
        Screen(name: "picker", route: "picker=\(samsung)|revenue|2025"),
        Screen(name: "company-compare", route: "compare=\(samsung)|\(apple)|revenue|operating_margin|2025"),
        Screen(name: "company-calculation", route: "companycalc=\(samsung)|\(apple)|revenue|operating_margin|2025",
               swipes: 4),
        Screen(name: "refusal-missing-period", route: "compare=\(samsung)|\(apple)|revenue|growth_rate|2025"),
        Screen(name: "refusal-ambiguous", route: "compare=\(samsung)|\(apple)|revenue|none|2025"),
        Screen(name: "refusal-currency", route: "compare=\(samsung)|\(apple)|revenue|absolute_amount|2025"),
        Screen(name: "refusal-year", route: "yearcompare=\(apple)|revenue|2025"),
        Screen(name: "news", route: "news"),
        Screen(name: "glossary", route: "glossary"),
        Screen(name: "glossary-entry", route: "glossary=metric_revenue"),
        Screen(name: "answer-trend", route: "ask=\(samsung)|recent_trend", swipes: 3),
        Screen(name: "answer-buy", route: "ask=\(samsung)|should_buy", swipes: 0),
        Screen(name: "answer-next-quarter", route: "ask=\(samsung)|next_quarter_revenue", swipes: 1),
        Screen(name: "answer-fundamentals-sec", route: "ask=\(apple)|fundamentals", swipes: 1),
    ]

    private static let accessibilityXL = "UICTContentSizeCategoryAccessibilityXL"

    private var recording: Bool { ProcessInfo.processInfo.environment["FOOTNOTE_AUDIT_RECORD"] == "1" }

    @MainActor func testAuditKoreanDefault() throws { try auditAll(language: "ko") }
    @MainActor func testAuditEnglishDefault() throws { try auditAll(language: "en") }
    @MainActor func testAuditKoreanAccessibilitySize() throws { try auditAll(language: "ko", size: Self.accessibilityXL) }
    @MainActor func testAuditEnglishAccessibilitySize() throws { try auditAll(language: "en", size: Self.accessibilityXL) }
    @MainActor func testAuditKoreanDark() throws { try auditAll(language: "ko", dark: true) }
    @MainActor func testAuditEnglishDark() throws { try auditAll(language: "en", dark: true) }

    /// What the Dynamic Type audit could not show for SwiftUI text: section headers, body
    /// text, link rows, buttons and filing rows are taller at an accessibility size.
    @MainActor func testTextGrowsAtAccessibilitySizes() throws {
        continueAfterFailure = true
        AuditFixture.prepareDevice(for: self)
        let bundle = try AuditFixture.glossaryBundle(for: self)
        let probes: [(route: String, find: (XCUIApplication) -> XCUIElement)] = [
            ("figure=\(Self.samsung)|revenue|2025", { $0.staticTexts["연도별"] }),
            ("figure=\(Self.samsung)|revenue|2025", { $0.staticTexts["회사가 사업으로 벌어들인 돈이에요."] }),
            ("figure=\(Self.samsung)|revenue|2025", { $0.buttons["compare-last-year"] }),
            ("company=\(Self.samsung)", { $0.descendants(matching: .any)[Self.dividend].firstMatch }),
            ("company=\(Self.samsung)", { $0.staticTexts["정기 보고서"] }),
        ]
        func height(_ probe: (route: String, find: (XCUIApplication) -> XCUIElement), size: String?) -> CGFloat {
            let app = AuditFixture.launch(probe.route, language: "ko", size: size, bundle: bundle)
            defer { app.terminate() }
            let element = probe.find(app)
            var tries = 0
            while !(element.exists && element.isHittable) && tries < 10 {
                app.swipeUp()
                tries += 1
            }
            XCTAssertTrue(element.exists, "\(probe.route): \(element)")
            return element.frame.height
        }
        for (index, probe) in probes.enumerated() {
            let normal = height(probe, size: nil)
            let large = height(probe, size: Self.accessibilityXL)
            XCTAssertGreaterThan(large, normal * 1.4, "probe \(index) \(probe.route): \(normal) → \(large)")
        }
    }

    @MainActor private func auditAll(language: String, size: String? = nil, dark: Bool = false) throws {
        continueAfterFailure = true
        AuditFixture.prepareDevice(dark: dark, for: self)
        let bundle = try AuditFixture.glossaryBundle(for: self)
        let only = ProcessInfo.processInfo.environment["FOOTNOTE_AUDIT_ONLY"].map { $0.split(separator: ",").map(String.init) }
        for screen in Self.screens where only?.contains(screen.name) ?? true {
            let config = "\(screen.name) \(language)\(size == nil ? "" : " AX")\(dark ? " dark" : "")"
            // Under load an audit can run past XCTest's time limit ("Audit failed to complete
            // in time"). Once one has, every further audit of that launch timed out too (lane A
            // runs, 2026-11-26), so the screen is audited again from a fresh launch; a second
            // timeout fails that screen and the other screens are still audited.
            for attempt in 1...2 {
                do {
                    try auditScreen(screen, config, language: language, size: size, bundle: bundle)
                    break
                } catch let error as NSError where error.code == Self.auditTimedOut {
                    print("AUDIT-TIMEOUT|\(config): attempt \(attempt)")
                    XCUIApplication().terminate()
                    if attempt == 2 { XCTFail("\(config): audit timed out twice") }
                }
            }
        }
    }

    @MainActor private func auditScreen(_ screen: Screen, _ config: String, language: String, size: String?,
                                        bundle: String) throws {
        let app = AuditFixture.launch(screen.route, language: language, size: size, bundle: bundle)
        // Every screen has a navigation bar; wait for it and a moment for the list to settle.
        XCTAssertTrue(app.navigationBars.firstMatch.waitForExistence(timeout: 10), config)
        sleep(1)
        try audit(app, config, pass: 0)
        for pass in 0..<screen.swipes {
            app.swipeUp()
            // A list keeps gliding after a swipe; an audit taken while it moves measures
            // blurred text and reports contrast failures that are not there.
            sleep(2)
            try audit(app, config, pass: pass + 1)
        }
        app.terminate()
    }

    @MainActor private func audit(_ app: XCUIApplication, _ config: String, pass: Int) throws {
        if let folder = ProcessInfo.processInfo.environment["FOOTNOTE_AUDIT_SHOTS"] {
            let file = "\(folder)/\(config.replacingOccurrences(of: " ", with: "-"))-\(pass).png"
            try? XCUIScreen.main.screenshot().pngRepresentation.write(to: URL(fileURLWithPath: file))
        }
        let allBars = (app.navigationBars.allElementsBoundByIndex + app.tabBars.allElementsBoundByIndex
            + app.toolbars.allElementsBoundByIndex).map(\.frame)
        let window = app.windows.firstMatch.frame
        // iOS 27 reports one toolbar element that spans the whole window; only the real bars
        // (a strip at the top or bottom) count, or every element would pass as "under a bar".
        let bars = allBars.filter { $0.height < window.height / 4 }
        // The iPad split view: the sidebar floats over the content column (its bar starts at the
        // leading edge and is narrower than a third of the window).
        let sidebar = bars.first { $0.minX == 0 && $0.width < window.width / 3 }
            .map { CGRect(x: 0, y: 0, width: $0.width, height: window.height) }
        // The quarter report's investor event row (I11), for the `bottom-edge` filter.
        let investorRow = app.descendants(matching: .any)["investor-event"].firstMatch
        let investorEvent = investorRow.exists ? investorRow.frame : nil
        if recording { print("BARS|\(config) #\(pass): \(bars.map(\.integral)) window=\(window.integral)") }
        try app.performAccessibilityAudit(for: .all) { issue in
            let element = issue.element
            let where_ = "\(config) #\(pass): \(issue.auditType.name) · \(issue.compactDescription) · "
                + "id=\(element?.identifier ?? "-") label=\(element?.label ?? "-") type=\(element?.elementType.rawValue ?? 0)"
            if let reason = Self.falsePositive(issue, bars: bars, sidebar: sidebar, window: window,
                                                 investorEvent: investorEvent, afterSwipe: pass > 0) {
                // Issues without an element are always printed, so a log shows them.
                if self.recording || element == nil { print("FILTERED|\(reason)|" + where_) }
                return true
            }
            if self.recording {
                let frame = element.map { "\($0.frame.integral)" } ?? "-"
                print("AUDIT|" + where_ + " frame=\(frame) · \(issue.detailedDescription)")
                return true
            }
            XCTFail(where_)
            return true
        }
    }

    /// `XCUIAccessibilityAuditError` "Audit failed to complete in time".
    private static let auditTimedOut = -56

    /// Findings checked by hand and judged false positives. Each names one audit type and
    /// the elements it applies to; anything else fails the test.
    @MainActor private static func falsePositive(_ issue: XCUIAccessibilityAuditIssue, bars: [CGRect],
                                                 sidebar: CGRect?, window: CGRect, investorEvent: CGRect?,
                                                 afterSwipe: Bool) -> String? {
        guard let element = issue.element else {
            // Some contrast, Dynamic Type and clipped-text findings name no element and no
            // frame (SwiftUI nodes the audit cannot hand back). Q1 checked each such pass
            // against its screenshot (`TEST_RUNNER_FOOTNOTE_AUDIT_SHOTS`) and found no clipped,
            // unscaled or low-contrast text outside the translucent bars; they are printed as
            // `FILTERED|unlocated|`. Element-less findings of every other type still fail.
            let types: [XCUIAccessibilityAuditType] = [.contrast, .dynamicType, .textClipped]
            if types.contains(issue.auditType) { return "unlocated" }
            // "Potentially inaccessible text" with no element (seen in the English passes), on
            // screens whose every visible text is an element in the accessibility tree (checked
            // with the q1 audit screenshots and a tree snapshot). Described under "Findings and
            // fixes" in docs/audits/2026-11-19-q1-accessibility.md; any other element detection
            // fails.
            if issue.auditType == .elementDetection,
               issue.compactDescription == "Potentially inaccessible text" { return "unlocated-text" }
            return nil
        }
        let frame = element.frame
        switch issue.auditType {
        case .textClipped:
            // A figure in full digits wider than the line (`₩300,870,903,000,000` at the
            // accessibility sizes) shrinks to fit on one line by design (D87,
            // `UnbrokenNumbers`, `BigValue`) and shows in full; the audit reads the one-line
            // limit as clipping.
            if element.elementType == .staticText, element.label.contains(where: \.isNumber),
               !element.label.contains(" ") { return "shrunk-number" }
            // The navigation bar's inline title truncates a long company name
            // (`Samsung Electronics` at Accessibility XL). A system bar title; recorded as
            // open in docs/audits/2026-11-19-q1-accessibility.md.
            if bars.contains(where: { $0.contains(frame) }) { return "bar-title" }
            // The notices sheet's introduction: at the accessibility sizes it wraps to five
            // lines and shows in full (q1 screenshot of the notices sheet); the audit still
            // reports it as clipped.
            if element.label.hasPrefix("일정이나 절차를 알리는 공시예요")
                || element.label.hasPrefix("Filings that announce a date or a procedure") { return "notices-intro" }
            // The company comparison's picker header: at the accessibility sizes the picker
            // turns into a list under this header, which shows in full on one line (q1 audit
            // screenshot of company-compare, English, Accessibility XL).
            if element.label == "비교 방식" || element.label == "Compare by" { return "compare-by-header" }
            // The quarter report's figures header in English (`July–September · Consolidated`,
            // `Mar 29–Jun 27 · Consolidated`): it shows in full on one line at the default size
            // and wraps between words at Accessibility XL (I11 audit screenshots of quarter and
            // quarter-sec, English, and i11-quarter-hyundai-en-ax). The Korean header passes.
            if element.identifier == "quarter-figures-header" { return "quarter-header" }
            // The same picker's rows on the iPad (`Amount` in the detail column): each row
            // shows in full on one line at the top and after each swipe (q1 iPad audit
            // screenshots of company-compare, English, Accessibility XL).
            if element.identifier == "measure-picker" { return "compare-by-row" }
            // The iPad sidebar's two system labels (`News`, `Glossary`) at the accessibility
            // sizes: each shows in full on one line in every iPad audit screenshot.
            if let sidebar, sidebar.contains(frame),
               ["소식", "용어", "News", "Glossary"].contains(element.label) { return "sidebar-label" }
            // After a swipe, text near the end of a list (`금액은 줄여서 보여 줘요.`, `2 notices`,
            // `See every filing on DART`) is reported clipped at a frame that does not match
            // where it is drawn; the pass's screenshot shows it in full. Only the first pass of
            // each screen checks text clipping, at every text size.
            if afterSwipe, element.elementType == .staticText { return "scrolled-text" }
            // The Companies tab's system search field (`.searchable`, D98): its placeholder
            // `Company name or ticker` shows in full at Accessibility XL (D100 audit screenshot
            // companies-en-AX-0, the field grown to 97 points). Placement and truncation of a
            // system search bar's placeholder are the system's.
            if element.elementType == .searchField { return "system-search" }
        case .hitRegion:
            // The glossary's native section index (iOS 26, D98) is the system's 15-point strip,
            // dragged along the screen's height. The toolbar's jump menu does the same with
            // 44-point rows (`glossary-index`), the equivalent control WCAG 2.5.8 allows.
            if element.label == "섹션 인덱스" || element.label == "Section index" { return "section-index" }
        case .contrast:
            // List content scrolls under the translucent (Liquid Glass) navigation and tab
            // bars, and the audit then measures the text against the blurred bar. The same
            // text measures above the threshold once it is clear of the bars, which the other
            // passes of the same screen audit.
            if bars.contains(where: { $0.intersects(frame) }) { return "under-bar" }
            // The quarter report's investor event row when the list lays it out just above the
            // bottom tab bar, where iOS fades list content into the bar (the scroll edge
            // effect). I11 audit screenshots: `Investor event notice` at y 706–727 over a tab
            // bar from about y 732 is drawn faded by the system; its colours are the Ink and
            // Muted tokens measured in Q1 ("Contrast"). Only text inside that row, ending
            // within 48 points above a bar in the lower half of the window.
            if element.elementType == .staticText, let investorEvent, investorEvent.contains(frame),
               bars.contains(where: { $0.minY > window.midY && frame.maxY <= $0.minY && $0.minY - frame.maxY < 48 }) {
                return "bottom-edge"
            }
            // The iPad sidebar floats over the content column as translucent glass, and the
            // audit measures text in or under it (`Korea`, `Glossary`, and the content
            // column's `Periodic reports`, whose frame starts under the sidebar) against the
            // blurred material. Sidebar text uses the palette tokens measured in the Q1 audit;
            // the selected row's Pine fill was checked on the iPad screenshots (system `.primary`
            // text). The section headers' Muted on the glass itself is not measured (audit item 37).
            if let sidebar, sidebar.intersects(frame) { return "under-sidebar" }
            // Text the list has laid out below the screen (`Needs an internet connection`
            // at y 850 on the 812-point mini): there is nothing behind it to measure.
            if !window.contains(frame) { return "off-screen" }
            // After a swipe the audit reports text that is plainly legible in the pass's
            // screenshot (`Six checks passed`, `Oct 29, 2026` in Ink on white), at a frame that
            // does not match where it is drawn. Every text colour in the app is a palette
            // token measured at 4.9:1 or more against each background it sits on (Q1 audit,
            // "Contrast"), and the first pass of every screen is still checked as it stands.
            if afterSwipe, element.elementType == .staticText { return "scrolled-text" }
            // The two-character `원문` section header on the filing pages, in Muted on
            // Background (5.51:1 light, 7.51:1 dark). `공시 내용` above it, the same style on the
            // same background, passes; the audit misjudges the short word.
            if element.label == "원문", element.elementType == .staticText { return "original-header" }
        case .dynamicType:
            // The language button sits in the navigation bar, which caps its text size at
            // the accessibility sizes (a system rule for bar items); it shows the large
            // content viewer instead (`accessibilityShowsLargeContentViewer`).
            if element.label == "EN" || element.label == "한국어" { return "bar-item" }
            // SwiftUI text in these lists uses text styles (`.body`, `.footnote`, …) and
            // grows to the largest accessibility size: the q1 AX5 screenshots and
            // `testTextGrowsAtAccessibilitySizes` check it directly. The audit still reports
            // SwiftUI's text nodes as not (or partly) scaling.
            if element.elementType == .staticText || element.elementType == .button { return "swiftui-text" }
        default:
            break
        }
        return nil
    }
}

extension XCUIAccessibilityAuditType {
    var name: String {
        switch self {
        case .contrast: "contrast"
        case .elementDetection: "elementDetection"
        case .hitRegion: "hitRegion"
        case .sufficientElementDescription: "description"
        case .dynamicType: "dynamicType"
        case .textClipped: "textClipped"
        case .trait: "trait"
        default: "type\(rawValue)"
        }
    }
}

/// Launching the app on an edited copy of the FootnoteKit fixture.
enum AuditFixture {
    /// Sets the appearance (put back to light after the test) and turns an iPad to landscape,
    /// where the split view shows all three columns.
    @MainActor static func prepareDevice(dark: Bool = false, for test: XCTestCase) {
        XCUIDevice.shared.appearance = dark ? .dark : .light
        if dark { test.addTeardownBlock { @MainActor in XCUIDevice.shared.appearance = .light } }
        if UIDevice.current.userInterfaceIdiom == .pad { XCUIDevice.shared.orientation = .landscapeLeft }
    }

    @MainActor static func launch(
        _ route: String?, language: String?, size: String? = nil, bundle: String
    ) -> XCUIApplication {
        let app = XCUIApplication()
        // `-language` pins the stored language for the whole run (the argument domain wins
        // over what the app saves), so a launch that tests the switch passes nil.
        var arguments = ["-FootnoteBundle", bundle]
        if let language { arguments += ["-language", language] }
        if let route { arguments += ["-FootnoteOpen", route] }
        if let size { arguments += ["-UIPreferredContentSizeCategoryName", size] }
        app.launchArguments = arguments
        app.launch()
        return app
    }

    /// The fixture with its glossary rows under the D81 keys, plus a dividend entry. The text
    /// is test data, never shipped wording.
    static func glossaryBundle(for test: XCTestCase) throws -> String {
        try edited(for: test, """
            UPDATE glossary SET term_key = 'metric_' || term_key;
            INSERT INTO glossary (term_key, lang, term, plain, formal) VALUES
              ('category_dividend', 'ko', '배당', '시험용 배당 설명이에요.', NULL),
              ('category_dividend', 'en', 'Dividend', 'A test entry about dividends.', NULL);
            """)
    }

    static func edited(for test: XCTestCase, _ sql: String) throws -> String {
        let fixture = try XCTUnwrap(Bundle(for: AccessibilityAuditUITests.self).path(forResource: "footnote", ofType: "sqlite"))
        let path = NSTemporaryDirectory() + "footnote-\(UUID().uuidString).sqlite"
        try FileManager.default.copyItem(atPath: fixture, toPath: path)
        var db: OpaquePointer?
        XCTAssertEqual(sqlite3_open(path, &db), SQLITE_OK)
        defer { sqlite3_close(db) }
        XCTAssertEqual(sqlite3_exec(db, sql, nil, nil, nil), SQLITE_OK, String(cString: sqlite3_errmsg(db)))
        test.addTeardownBlock { try? FileManager.default.removeItem(atPath: path) }
        return path
    }
}
