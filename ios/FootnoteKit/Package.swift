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
        .testTarget(
            name: "FootnoteKitTests",
            dependencies: ["FootnoteKit"],
            resources: [.copy("Contracts"), .copy("Fixtures")]
        ),
    ]
)
