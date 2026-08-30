// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "macflow",
    platforms: [.macOS(.v14)],
    products: [
        .library(name: "MacflowCore", targets: ["MacflowCore"]),
        .executable(name: "macflow", targets: ["Macflow"]),
    ],
    targets: [
        .target(name: "MacflowCore"),
        .executableTarget(name: "Macflow", dependencies: ["MacflowCore"]),
        .testTarget(
            name: "MacflowCoreTests",
            dependencies: ["MacflowCore"]
        ),
    ]
)
