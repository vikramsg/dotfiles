// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "MacWorkflowPermissions",
    platforms: [.macOS(.v14)],
    products: [
        .library(name: "MacWorkflowCore", targets: ["MacWorkflowCore"]),
        .executable(
            name: "MacWorkflowPermissions",
            targets: ["MacWorkflowPermissions"]
        ),
        .executable(name: "mac-workflow", targets: ["MacWorkflowCLI"]),
    ],
    targets: [
        .target(name: "MacWorkflowCore"),
        .executableTarget(
            name: "MacWorkflowPermissions",
            dependencies: ["MacWorkflowCore"]
        ),
        .executableTarget(
            name: "MacWorkflowCLI",
            dependencies: ["MacWorkflowCore"]
        ),
        .testTarget(
            name: "MacWorkflowCoreTests",
            dependencies: ["MacWorkflowCore"]
        ),
    ]
)
