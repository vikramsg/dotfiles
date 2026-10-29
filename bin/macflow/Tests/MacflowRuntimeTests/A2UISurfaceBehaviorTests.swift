import Foundation
import MacflowCore
import Testing
@testable import Macflow

@Suite(.serialized) @MainActor
struct A2UISurfaceBehaviorTests {
    @Test func surfaceLifecycleThroughHTTP() async throws {
        let (runtime, directory) = try startRuntime()
        defer {
            runtime.stop()
            try? FileManager.default.removeItem(at: directory)
        }
        try await eventually { (runtime.httpPort ?? 0) != 0 }
        let port = try #require(runtime.httpPort)

        let payload = Data(
            """
            [
              {"version":"v0.9.1","createSurface":{"surfaceId":"demo","surface":{"width":400,"height":200}}},
              {"version":"v0.9.1","updateComponents":{"surfaceId":"demo","components":[{"id":"root","component":"Text","text":"Hello"}]}}
            ]
            """.utf8
        )
        let created = try await requestRawBody(
            port: port, path: "/v1/ui", body: payload, contentType: "application/a2ui+json"
        )
        #expect(created.status == 200)

        let listed = try await request(port: port, path: "/v1/ui")
        let surfaces = try #require(listed.body["surfaces"] as? [[String: Any]])
        #expect(surfaces.contains { $0["surfaceId"] as? String == "demo" })

        let dismissed = try await request(port: port, method: "DELETE", path: "/v1/ui/demo")
        #expect(dismissed.status == 200)

        let after = try await request(port: port, path: "/v1/ui")
        let remaining = (after.body["surfaces"] as? [[String: Any]]) ?? []
        #expect(!remaining.contains { $0["surfaceId"] as? String == "demo" })
    }

    @Test func invalidPayloadIsRejectedWithoutCreatingASurface() async throws {
        let (runtime, directory) = try startRuntime()
        defer {
            runtime.stop()
            try? FileManager.default.removeItem(at: directory)
        }
        try await eventually { (runtime.httpPort ?? 0) != 0 }
        let port = try #require(runtime.httpPort)

        let payload = Data(
            #"{"version":"v0.9.1","updateComponents":{"surfaceId":"bad","components":[{"id":"root","component":"Spaceship"}]}}"#.utf8
        )
        let reply = try await requestRawBody(
            port: port, path: "/v1/ui", body: payload, contentType: "application/a2ui+json"
        )
        #expect(reply.status == 422)

        let after = try await request(port: port, path: "/v1/ui")
        let surfaces = (after.body["surfaces"] as? [[String: Any]]) ?? []
        #expect(surfaces.isEmpty)
    }
}

@MainActor
private func startRuntime() throws -> (AutomationRuntime, URL) {
    let directory = try testDirectory()
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    let configurationURL = directory.appendingPathComponent("config.json")
    try JSONEncoder().encode(runtimeConfiguration(directory: directory)).write(to: configurationURL)
    let runtime = try AutomationRuntime(
        configurationURL: configurationURL,
        token: "test-token",
        hotKeys: HotKeyService(createEventTap: { _ in nil })
    )
    try runtime.start()
    return (runtime, directory)
}
