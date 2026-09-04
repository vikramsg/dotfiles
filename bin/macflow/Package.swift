// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "macflow",
    platforms: [.macOS(.v14)],
    products: [
        .library(name: "MacflowCore", targets: ["MacflowCore"]),
        .library(name: "MacflowUI", targets: ["MacflowUI"]),
        .executable(name: "macflow", targets: ["Macflow"]),
    ],
    dependencies: [
        .package(url: "https://github.com/apple/swift-argument-parser", from: "1.8.2"),
    ],
    targets: [
        .target(name: "MacflowCore"),
        .target(name: "MacflowUI", dependencies: ["MacflowCore"]),
        .target(
            name: "MacflowCLI",
            dependencies: [
                "MacflowCore",
                .product(name: "ArgumentParser", package: "swift-argument-parser"),
            ]
        ),
        .executableTarget(name: "Macflow", dependencies: ["MacflowCLI", "MacflowCore", "MacflowUI"]),
        .testTarget(
            name: "MacflowCLITests",
            dependencies: ["MacflowCLI"]
        ),
        .testTarget(
            name: "MacflowCoreTests",
            dependencies: ["MacflowCore"]
        ),
        .testTarget(
            name: "MacflowUITests",
            dependencies: ["MacflowCore", "MacflowUI"]
        ),
    ],
    swiftLanguageModes: [.v5]
)
