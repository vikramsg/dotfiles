import AppKit
import MacflowCore
import MacflowUI
import Testing
@testable import Macflow

@Suite(.serialized) @MainActor
struct ScreenshotBehaviorTests {
    @Test func defaultCaptureIsCleanAndDoesNotCreateAnAutomaticPreview() async throws {
        let fixture = try ScreenshotFixture()
        defer { fixture.stop() }
        _ = fixture.preview.show(path: "/previous.png", timeout: nil)

        let reply = try await fixture.capture(preview: false)

        #expect(reply.status == 200)
        #expect(fixture.camera.capturedPreview == false)
        #expect(reply.body["path"] as? String == fixture.camera.destination.path)
        try await Task.sleep(for: .milliseconds(100))
        #expect(fixture.preview.path == nil)
        try await fixture.expectNextExternalImageIsPreviewed()
    }

    @Test func requestedPreviewDisplaysTheCapturedFile() async throws {
        let fixture = try ScreenshotFixture()
        defer { fixture.stop() }
        let reply = try await fixture.capture(preview: true)
        #expect(reply.status == 200)
        #expect(fixture.preview.path == fixture.camera.destination.path)
        #expect(fixture.camera.capturedPreview == false)
    }

    @Test(arguments: [false, true])
    func failedCaptureDoesNotDisableFutureAutomaticPreviews(failBeforeDestination: Bool) async throws {
        let fixture = try ScreenshotFixture()
        defer { fixture.stop() }
        fixture.camera.failure = failBeforeDestination ? .beforeDestination : .afterDestination
        let reply = try await fixture.capture(preview: false)
        #expect(reply.status == 422)
        #expect(reply.body["error"] != nil)
        // Reusing the failed destination also proves it is not left suppressed.
        try Data("external image".utf8).write(to: fixture.camera.destination)
        try await eventually { fixture.preview.path == fixture.camera.destination.path }
    }
}

@MainActor
private final class ScreenshotFixture {
    let directory: URL
    let preview = Preview()
    let camera: Camera
    let watcher: AutomaticPreviewController
    let server: HTTPServer

    init() throws {
        directory = try testDirectory()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let configuration = try runtimeConfiguration(directory: directory)
        camera = Camera(destination: directory.appendingPathComponent("capture.png"), preview: preview)
        watcher = AutomaticPreviewController(directory: directory, configuration: configuration.screenshots, overlay: preview)
        let applications = ApplicationService()
        let windows = WindowService(applications: applications)
        let screens = ScreenService()
        server = HTTPServer(
            configuration: configuration.server, token: "test-token", applications: applications,
            windows: windows, screens: screens, preview: preview,
            screenshots: ScreenshotController(capture: camera, preview: preview, watcher: watcher, settleSeconds: 0.01),
            shelf: FileShelfController(windows: windows, screens: screens, hotKeys: HotKeyService(), theme: BuiltInThemeCatalog.system),
            hotKeyStatus: { HotKeyStatus(eventTapEnabled: false, secureInputEnabled: false) }
        )
        try watcher.start()
        try server.start()
    }

    func capture(preview: Bool) async throws -> APIReply {
        try await eventually { (self.server.port ?? 0) != 0 }
        return try await request(port: server.port!, method: "POST", path: "/v1/screenshots", body: ["show_preview": preview])
    }

    func expectNextExternalImageIsPreviewed() async throws {
        let external = directory.appendingPathComponent("external.png")
        try Data("external image".utf8).write(to: external)
        try await eventually { self.preview.path == external.path }
    }

    func stop() {
        server.stop()
        watcher.stop()
        try? FileManager.default.removeItem(at: directory)
    }
}

private final class Preview: ScreenshotPreviewing {
    var path: String?
    var windowID: CGWindowID? { path == nil ? nil : 42 }
    var json: [String: Any] { ["visible": path != nil, "path": path ?? NSNull()] }
    func show(path: String, timeout: Double?) -> Bool { self.path = path; return true }
    func hide() { path = nil }
}

private final class Camera: ScreenshotCapturing {
    enum Failure: Error { case beforeDestination, afterDestination }
    let destination: URL
    let preview: Preview
    var failure: Failure?
    var capturedPreview: Bool?

    init(destination: URL, preview: Preview) { self.destination = destination; self.preview = preview }

    func capture(
        displayID: UInt32?, path: String?, excludingWindowIDs: Set<CGWindowID>,
        destinationResolved: @escaping (URL) -> Void,
        completion: @escaping (Result<[String: Any], Error>) -> Void
    ) {
        do {
            if failure == .beforeDestination { throw Failure.beforeDestination }
            destinationResolved(destination)
            if failure == .afterDestination { throw Failure.afterDestination }
            capturedPreview = preview.windowID.map { !excludingWindowIDs.contains($0) } ?? false
            try Data("captured image".utf8).write(to: destination)
            completion(.success(["path": destination.path, "display_id": NSNumber(value: displayID ?? 1), "width": 100, "height": 100]))
        } catch {
            completion(.failure(error))
        }
    }
}
