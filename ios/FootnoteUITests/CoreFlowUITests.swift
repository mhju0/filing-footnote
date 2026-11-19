import XCTest

/// Roadmap Q1: the core flow end to end by taps alone, on iPhone (tabs) and iPad (split
/// view), in Korean then English: company → filing and its original → the annual report →
/// figure and earlier years → compare with last year and its calculation → compare with
/// another company (refused, then the margin with its caveat) and its calculation → the
/// glossary → switch the language. Runs on the glossary copy of the FootnoteKit fixture.
final class CoreFlowUITests: XCTestCase {
    private static let samsung = "dart:00126380"
    private static let apple = "sec:0000320193"
    private static let annual = "dart:20260310000123"
    private static let dividend = "dart:20261029800101"

    @MainActor func testCoreFlowKorean() throws { try coreFlow(.ko) }
    @MainActor func testCoreFlowEnglish() throws { try coreFlow(.en) }

    enum Lang { case ko, en }

    @MainActor private func coreFlow(_ lang: Lang) throws {
        continueAfterFailure = false
        AuditFixture.prepareDevice(for: self)
        let ko = lang == .ko
        let app = AuditFixture.launch(nil, language: ko ? "ko" : "en", bundle: try AuditFixture.glossaryBundle(for: self))

        // Company: the companies list on iPhone, the sidebar on iPad.
        let company = app.descendants(matching: .any)
            .matching(NSPredicate(format: "label BEGINSWITH %@", ko ? "삼성전자, 005930" : "Samsung Electronics, 005930"))
            .firstMatch
        XCTAssertTrue(company.waitForExistence(timeout: 10))
        company.tap()

        // An event filing, its sentences and its original.
        let filingRow = identified(Self.dividend, in: app)
        reveal(filingRow, in: app)
        filingRow.tap()
        XCTAssertTrue(identified("filing-page", in: app).waitForExistence(timeout: 5))
        let original = app.buttons["open-original"]
        reveal(original, in: app)
        XCTAssertTrue(original.isHittable)
        XCTAssertGreaterThanOrEqual(original.frame.height, 44)
        XCTAssertTrue(original.label.contains(ko ? "DART에서 원문 보기" : "Open the original on DART"), original.label)
        goBack(from: "filing-page", in: app)

        // The annual report, then a figure and its earlier years.
        let annualRow = identified(Self.annual, in: app)
        revealUpward(annualRow, in: app)
        annualRow.tap()
        XCTAssertTrue(identified("annual-page", in: app).waitForExistence(timeout: 5))
        let revenue = app.buttons["figure-revenue"]
        reveal(revenue, in: app)
        revenue.tap()
        XCTAssertTrue(identified("figure-page", in: app).waitForExistence(timeout: 5))
        XCTAssertTrue(element(ko ? "퍼센트 늘었어요" : "percent from the year before", in: app).exists)
        let prior = element(ko ? "2024 회계연도" : "FY2024", in: app)
        reveal(prior, in: app)
        XCTAssertTrue(prior.exists)

        // Compare with last year and its calculation.
        tapRevealed(app.buttons["compare-last-year"], in: app)
        XCTAssertTrue(identified("year-compare-page", in: app).waitForExistence(timeout: 5))
        XCTAssertTrue(identified("year-change", in: app).label.contains(ko ? "늘었어요" : "up"))
        tapRevealed(app.buttons["see-calculation"], in: app)
        XCTAssertTrue(identified("calculation-page", in: app).waitForExistence(timeout: 5))
        XCTAssertTrue(identified("equation", in: app).exists)
        goBack(from: "calculation-page", in: app)
        goBack(from: "year-compare-page", in: app)

        // Compare with another company: growth is refused (Apple has one year in the
        // fixture), the margin is possible instead and carries the caveat.
        tapRevealed(app.buttons["compare-company"], in: app)
        XCTAssertTrue(identified("peer-picker", in: app).waitForExistence(timeout: 5))
        tapRevealed(identified("peer-\(Self.apple)", in: app), in: app)
        XCTAssertTrue(identified("refusal-missing_period", in: app).waitForExistence(timeout: 5))
        tapRevealed(identified("instead-0", in: app), in: app)
        XCTAssertTrue(identified("rate-\(Self.samsung)", in: app).waitForExistence(timeout: 5))
        let caveat = identified("caveat", in: app)
        reveal(caveat, in: app)
        XCTAssertTrue(caveat.label.contains("K-IFRS, US GAAP"), caveat.label)
        tapRevealed(app.buttons["see-calculation"], in: app)
        XCTAssertTrue(identified("calculation-page", in: app).waitForExistence(timeout: 5))
        goBack(from: "calculation-page", in: app)
        goBack(from: "company-compare-page", in: app)

        // The glossary entry for the figure.
        XCTAssertTrue(identified("figure-page", in: app).waitForExistence(timeout: 5))
        tapRevealed(app.buttons["more-in-glossary"], in: app)
        XCTAssertTrue(identified("glossary-page", in: app).waitForExistence(timeout: 5))
        XCTAssertTrue(identified("glossary-metric_revenue", in: app).isSelected)

        // One tap switches the language. The launch above pins it with `-language` (the
        // argument wins over what the app saves), so the figure is opened again without it
        // and switched there and back.
        app.terminate()
        let free = AuditFixture.launch("figure=\(Self.samsung)|revenue|2025", language: nil,
                                       bundle: try AuditFixture.glossaryBundle(for: self))
        let toEnglish = free.buttons["Switch to English"]
        let toKorean = free.buttons["한국어로 보기"]
        XCTAssertTrue(toEnglish.waitForExistence(timeout: 10) || toKorean.exists)
        let startsKorean = toEnglish.exists
        // A navigation-bar item: iOS sizes its glass capsule and touch area itself (the
        // reported frame is the 36-point content), so this checks it can be tapped; the
        // audit's hit-region check covers its size.
        let first = startsKorean ? toEnglish : toKorean
        XCTAssertTrue(first.isHittable)
        XCTAssertGreaterThanOrEqual(first.frame.width, 44)
        for round in 0..<2 {
            let isKorean = startsKorean == (round == 0)
            (isKorean ? toEnglish : toKorean).tap()
            XCTAssertTrue((isKorean ? toKorean : toEnglish).waitForExistence(timeout: 5))
            XCTAssertTrue(element(isKorean ? "Revenue" : "매출", in: free).waitForExistence(timeout: 5))
        }
    }

    // MARK: - Helpers

    @MainActor private func element(_ text: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", text)).firstMatch
    }

    @MainActor private func identified(_ id: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any)[id].firstMatch
    }

    @MainActor private func reveal(_ element: XCUIElement, in app: XCUIApplication) {
        var tries = 0
        while !(element.exists && element.isHittable) && tries < 8 {
            swipe(up: true, toward: element, in: app)
            tries += 1
        }
    }

    @MainActor private func revealUpward(_ element: XCUIElement, in app: XCUIApplication) {
        var tries = 0
        while !(element.exists && element.isHittable) && tries < 8 {
            swipe(up: false, toward: element, in: app)
            tries += 1
        }
    }

    /// On iPhone a swipe anywhere scrolls the one screen. On the iPad's split view the
    /// window's centre lies in the content column, so the swipe goes to the column the
    /// element is in: the content column for a filing row, the detail column otherwise.
    @MainActor private func swipe(up: Bool, toward element: XCUIElement, in app: XCUIApplication) {
        guard UIDevice.current.userInterfaceIdiom == .pad else {
            if up { app.swipeUp() } else { app.swipeDown() }
            return
        }
        let window = app.windows.firstMatch.frame
        let x = element.exists ? element.frame.midX / window.width : 0.8
        let from = app.coordinate(withNormalizedOffset: CGVector(dx: x, dy: up ? 0.7 : 0.3))
        let to = app.coordinate(withNormalizedOffset: CGVector(dx: x, dy: up ? 0.3 : 0.7))
        from.press(forDuration: 0.05, thenDragTo: to)
    }

    @MainActor private func tapRevealed(_ element: XCUIElement, in app: XCUIApplication) {
        reveal(element, in: app)
        XCTAssertTrue(element.isHittable, element.debugDescription)
        element.tap()
    }

    /// The back button of the navigation bar over `page`. iPad's split view picks the next
    /// filing from the content column instead, so a filing page needs no back there.
    @MainActor private func goBack(from page: String, in app: XCUIApplication) {
        if UIDevice.current.userInterfaceIdiom == .pad && (page == "filing-page" || page == "annual-page") { return }
        let back = app.navigationBars.buttons.matching(identifier: "BackButton").firstMatch
        XCTAssertTrue(back.waitForExistence(timeout: 5), app.debugDescription)
        back.tap()
        XCTAssertTrue(identified(page, in: app).waitForNonExistence(timeout: 5), page)
    }
}
