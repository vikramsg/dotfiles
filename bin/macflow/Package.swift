// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "macflow",
    platforms: [.macOS(.v14)],
    products: [
        .library(name: "MacflowCore", targets: ["MacflowCore"]),
        .library(name: "MacflowUI", targets: ["MacflowUI"]),
        .executable(name: "macflow", targets: ["Macflow"]),
    ],
    targets: [
        .target(name: "MacflowCore"),
        .target(name: "MacflowUI", dependencies: ["MacflowCore"]),
        .executableTarget(name: "Macflow", dependencies: ["MacflowCore", "MacflowUI"]),
        .testTarget(
            name: "MacflowCoreTests",
            dependencies: ["MacflowCore"]
        ),
        .testTarget(
            name: "MacflowUITests",
            dependencies: ["MacflowCore", "MacflowUI"]
        ),
    ]
)
