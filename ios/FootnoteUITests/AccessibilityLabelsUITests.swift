import XCTest

/// Roadmap Q1, the checks the audit does not make: every control has a label and a target of
/// at least 44 points, figures read their values and
/// directions in words, and the reading order follows the screen from top to bottom.
final class AccessibilityLabelsUITests: XCTestCase {
    private static let samsung = "dart:00126380"
    private static let apple = "sec:0000320193"

    /// Every screen of the audit, in both languages: control labels, target sizes, images.
    @MainActor func testControlsHaveLabelsAndTargets() throws {
        try checkControls(language: "ko")
        try checkControls(language: "en")
    }

    @MainActor private func checkControls(language: String) throws {
        continueAfterFailure = true
        AuditFixture.prepareDevice(for: self)
        let bundle = try AuditFixture.glossaryBundle(for: self)
        let only = ProcessInfo.processInfo.environment["FOOTNOTE_AUDIT_ONLY"].map { $0.split(separator: ",").map(String.init) }
        for screen in AccessibilityAuditUITests.screens where only?.contains(screen.name) ?? true {
            let app = AuditFixture.launch(screen.route, language: language, bundle: bundle)
            XCTAssertTrue(app.navigationBars.firstMatch.waitForExistence(timeout: 10), screen.name)
            sleep(1)
            for pass in 0...screen.swipes {
                if pass > 0 {
                    app.swipeUp()
                    sleep(2)
                }
                checkVisible(app, "\(screen.name) \(language) #\(pass)")
            }
            app.terminate()
        }
    }

    /// The controls on screen now. Elements partly off screen or in the bars are skipped for
    /// size: the list has scrolled them half out of view, or iOS sizes them.
    @MainActor private func checkVisible(_ app: XCUIApplication, _ config: String) {
        let screen = app.windows.firstMatch.frame
        // Navigation- and tab-bar items: iOS sizes their glass capsules and touch areas
        // itself and reports only the content frame (36 points for the language button), so
        // they are checked for a label only; the audit's hit-region check covers them.
        let bars = (app.navigationBars.allElementsBoundByIndex + app.tabBars.allElementsBoundByIndex).map(\.frame)
        let buttons = app.buttons.allElementsBoundByIndex.filter(\.exists)
        // The sheet's grabber is the system's drag handle, sized by iOS.
        let grabber: Set<String> = ["시트 손잡이", "Sheet Grabber"]
        for button in buttons where button.isHittable && !grabber.contains(button.label) {
            let frame = button.frame
            XCTAssertFalse(button.label.trimmingCharacters(in: .whitespaces).isEmpty,
                           "\(config): a button has no label: \(button.debugDescription)")
            guard screen.contains(frame), !bars.contains(where: { $0.contains(frame) }) else { continue }
            XCTAssertGreaterThanOrEqual(frame.height, 44, "\(config): \(button.label) is \(frame.size)")
            XCTAssertGreaterThanOrEqual(frame.width, 44, "\(config): \(button.label) is \(frame.size)")
        }
        // Decorative images are not checked here: XCUITest lists images marked
        // `accessibilityHidden` too (the calculation's check marks), so its image query does
        // not show what VoiceOver reads. The audit's element-description check and the Q1
        // review of every `Image(` in the app cover them.
    }

    /// Values and directions read as words, never as a sign or colour alone.
    @MainActor func testFiguresReadValuesAndDirectionsInWords() throws {
        continueAfterFailure = true
        AuditFixture.prepareDevice(for: self)
        let bundle = try AuditFixture.glossaryBundle(for: self)
        let expectations: [(route: String, id: String, ko: [String], en: [String])] = [
            ("figure=\(Self.samsung)|revenue|2025", "figure-page",
             ["300조 8,709억 300만원", "전년보다 16.20퍼센트 증가"],
             ["increased 16.20 percent from the year before"]),
            ("yearcompare=\(Self.samsung)|revenue|2025", "year-change",
             ["전년보다 16.20퍼센트 증가", "차이"], ["increased 16.20 percent from the year before"]),
            ("filing=\(Self.samsung)|dart:20260310000123", "figure-revenue",
             ["전년보다 16.20퍼센트 증가", "300조 8,709억 300만원"], ["increased 16.20 percent"]),
            ("compare=\(Self.samsung)|\(Self.apple)|revenue|operating_margin|2025", "rate-\(Self.samsung)",
             ["삼성전자", "영업이익률"], ["Samsung Electronics", "Operating margin"]),
            ("compare=\(Self.samsung)|\(Self.apple)|revenue|operating_margin|2025", "rate-difference",
             ["퍼센트포인트"], ["percentage points"]),
        ]
        for language in ["ko", "en"] {
            for item in expectations {
                let app = AuditFixture.launch(item.route, language: language, bundle: bundle)
                let label: String
                if item.id == "figure-page" {
                    label = headerLabel(app)
                } else {
                    let element = app.descendants(matching: .any)[item.id].firstMatch
                    XCTAssertTrue(element.waitForExistence(timeout: 10), item.id)
                    var tries = 0
                    while !element.isHittable && tries < 6 {
                        app.swipeUp()
                        tries += 1
                    }
                    label = element.label
                }
                for word in language == "ko" ? item.ko : item.en {
                    XCTAssertTrue(label.contains(word), "\(item.id) \(language): \(label) lacks \(word)")
                }
                app.terminate()
            }
        }
    }

    /// The figure header: the first element on the figure page that is a header.
    @MainActor private func headerLabel(_ app: XCUIApplication) -> String {
        let header = app.descendants(matching: .any)
            .matching(NSPredicate(format: "label CONTAINS %@ OR label CONTAINS %@", "매출,", "Revenue,")).firstMatch
        XCTAssertTrue(header.waitForExistence(timeout: 10))
        return header.label
    }

    /// VoiceOver reads the figure screen top to bottom: header, meaning, years, actions.
    @MainActor func testFigureReadingOrder() throws {
        AuditFixture.prepareDevice(for: self)
        let app = AuditFixture.launch("figure=\(Self.samsung)|revenue|2025", language: "ko",
                                      bundle: try AuditFixture.glossaryBundle(for: self))
        XCTAssertTrue(app.buttons["compare-last-year"].waitForExistence(timeout: 10))
        let tree = app.debugDescription
        let order = ["300조 8,709억 300만원", "이 숫자의 뜻", "용어 풀이 더 보기", "연도별", "2024 회계연도",
                     "작년과 비교", "다른 회사와 비교"]
        let positions = order.map { tree.range(of: $0)?.lowerBound }
        for (text, position) in zip(order, positions) { XCTAssertNotNil(position, text) }
        let found = positions.compactMap { $0 }
        XCTAssertEqual(found, found.sorted(), "reading order: \(order)")
    }
}
