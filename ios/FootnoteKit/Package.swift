// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "FootnoteKit",
    platforms: [.iOS(.v18), .macOS(.v15)],
    products: [
        .library(name: "FootnoteKit", targets: ["FootnoteKit"]),
    ],
    targets: [
        .target(name: "FootnoteKit"),
        // The typed-question router against the on-device model, on contracts/typed-questions.json
        // (D108): `swift run --package-path ios/FootnoteKit question-router-eval`.
        .executableTarget(name: "question-router-eval", dependencies: ["FootnoteKit"]),
        .testTarget(
            name: "FootnoteKitTests",
            dependencies: ["FootnoteKit"],
            resources: [.copy("Contracts"), .copy("Fixtures")]
        ),
    ]
)
