import XCTest

/// The first-run guide and the tips (D104): the guide shows on first launch only, Skip ends
/// it, it reopens from the end of the glossary, and no tip shows while it is up. Each test
/// resets the guide flag and TipKit's datastore through debug launch arguments.
final class GuideTipsUITests: XCTestCase {
    override func setUp() {
        continueAfterFailure = false
    }

    @MainActor private func launch(_ arguments: [String], bundle: String) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-FootnoteBundle", bundle] + arguments
        app.launch()
        return app
    }

    @MainActor private func identified(_ id: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: id).firstMatch
    }

    @MainActor private func text(_ label: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", label)).firstMatch
    }

    @MainActor func testFirstLaunchSkipAndReopen() throws {
        AuditFixture.prepareDevice(for: self)
        let bundle = try AuditFixture.glossaryBundle(for: self)
        var app = launch(["-FootnoteResetGuide", "-language", "ko"], bundle: bundle)

        // First launch: the guide is up, with Skip on its first page.
        let guide = identified("guide", in: app)
        XCTAssertTrue(guide.waitForExistence(timeout: 10))
        XCTAssertTrue(app.buttons["guide-skip"].exists)
        XCTAssertTrue(text("공시를 쉬운 말로", in: app).exists)
        XCTAssertEqual(identified("guide-dots", in: app).label, "페이지 1/4")

        // Skip ends it and lands on the app.
        app.buttons["guide-skip"].tap()
        XCTAssertTrue(guide.waitForNonExistence(timeout: 5))

        // The next launch does not show it again.
        app.terminate()
        app = launch(["-language", "ko", "-FootnoteOpen", "glossary", "-FootnoteScroll", "bottom"], bundle: bundle)
        let row = app.buttons["guide-reopen"]
        XCTAssertTrue(row.waitForExistence(timeout: 10))
        XCTAssertFalse(identified("guide", in: app).exists)

        // The glossary's last row reopens it; Next walks the pages, Skip stays on each one,
        // and the last page ends with 시작하기.
        if !row.isHittable { app.swipeUp() }
        row.tap()
        XCTAssertTrue(identified("guide", in: app).waitForExistence(timeout: 5))
        for page in 2...4 {
            app.buttons["guide-next"].tap()
            XCTAssertTrue(app.buttons["guide-skip"].exists)
            XCTAssertTrue(identified("guide-dots", in: app).waitForLabel("페이지 \(page)/4"))
        }
        XCTAssertTrue(text("소식과 용어", in: app).exists)
        XCTAssertFalse(app.buttons["guide-next"].exists)
        app.buttons["guide-start"].tap()
        XCTAssertTrue(identified("guide", in: app).waitForNonExistence(timeout: 5))
    }

    /// Every tip is forced on, yet none shows until the guide closes.
    @MainActor func testNoTipWhileTheGuideIsUp() throws {
        AuditFixture.prepareDevice(for: self)
        let fixture = try XCTUnwrap(Bundle(for: Self.self).path(forResource: "footnote", ofType: "sqlite"))
        let app = launch(
            ["-FootnoteResetGuide", "-FootnoteResetTips", "-FootnoteShowAllTips", "-FootnoteOpen", "news",
             "-language", "en"],
            bundle: fixture)
        XCTAssertTrue(identified("guide", in: app).waitForExistence(timeout: 10))
        let tip = text("Filter by filing type", in: app)
        XCTAssertFalse(tip.waitForExistence(timeout: 3), "a tip showed while the guide was up")

        app.buttons["guide-skip"].tap()
        XCTAssertTrue(identified("guide", in: app).waitForNonExistence(timeout: 5))
        XCTAssertTrue(tip.waitForExistence(timeout: 5), "the News tip did not show after the guide closed")
    }

    /// From a reset datastore, the News filter tip waits for the second visit to News (its
    /// own rule).
    @MainActor func testNewsTipShowsOnTheSecondVisit() throws {
        AuditFixture.prepareDevice(for: self)
        try XCTSkipIf(UIDevice.current.userInterfaceIdiom == .pad, "the tab bar flow is the iPhone's")
        let fixture = try XCTUnwrap(Bundle(for: Self.self).path(forResource: "footnote", ofType: "sqlite"))
        let app = launch(["-FootnoteResetGuide", "-FootnoteResetTips", "-language", "en"], bundle: fixture)
        XCTAssertTrue(identified("guide", in: app).waitForExistence(timeout: 10))
        app.buttons["guide-skip"].tap()

        let news = app.tabBars.buttons["News"]
        let companies = app.tabBars.buttons["Companies"]
        let tip = text("Filter by filing type", in: app)
        news.tap()
        XCTAssertTrue(identified("news-page", in: app).waitForExistence(timeout: 5))
        XCTAssertFalse(tip.waitForExistence(timeout: 3), "the tip showed on the first visit")

        companies.tap()
        news.tap()
        XCTAssertTrue(tip.waitForExistence(timeout: 5), "the tip did not show on the second visit")
    }
}

private extension XCUIElement {
    /// Waits for the element's label, for an adjustable element that updates in place.
    func waitForLabel(_ label: String, timeout: TimeInterval = 3) -> Bool {
        let expectation = XCTNSPredicateExpectation(
            predicate: NSPredicate(format: "label == %@", label), object: self)
        return XCTWaiter().wait(for: [expectation], timeout: timeout) == .completed
    }
}
