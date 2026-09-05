import Foundation
import MacflowCore
import Testing
@testable import Macflow

@Suite(.serialized) @MainActor
struct StartupBehaviorTests {
    @Test func unavailableHotkeysDoNotPreventPermissionRecoveryThroughHTTP() async throws {
        let directory = try testDirectory()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let configurationURL = directory.appendingPathComponent("config.json")
        try JSONEncoder().encode(runtimeConfiguration(directory: directory)).write(to: configurationURL)
        var accessibility = false
        let permissions = PermissionAccess(
            status: { PermissionStatus(accessibility: accessibility, screenRecording: false) },
            request: { permission in
                if permission == .accessibility { accessibility = true }
                return accessibility
            }
        )
        let runtime = try AutomationRuntime(
            configurationURL: configurationURL, token: "test-token",
            hotKeys: HotKeyService(createEventTap: { _ in nil }), permissions: permissions
        )
        defer { runtime.stop() }
        try runtime.start()
        try await eventually { (runtime.httpPort ?? 0) != 0 }
        let port = try #require(runtime.httpPort)

        let health = try await request(port: port, path: "/v1/health")
        #expect(health.status == 200)
        #expect(health.body["ok"] as? Bool == true)
        let denied = try await request(port: port, path: "/v1/permissions")
        #expect(denied.status == 200)
        #expect(denied.body["accessibility"] as? Bool == false)
        let hotkeys = try await request(port: port, path: "/v1/hotkeys")
        #expect(hotkeys.status == 200)
        #expect(hotkeys.body["event_tap_enabled"] as? Bool == false)

        let approval = try await request(
            port: port, method: "POST", path: "/v1/permissions/request", body: ["permission": "accessibility"]
        )
        #expect(approval.status == 200)
        let granted = try await request(port: port, path: "/v1/permissions")
        #expect(granted.body["accessibility"] as? Bool == true)
    }
}
