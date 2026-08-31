import AppKit
import Testing
@testable import MacflowUI

@Suite(.serialized)
@MainActor
struct WebSurfacePanelTests {
    @Test
    func userDocumentReceivesConfigurationThemeAndBridgeReplies() async throws {
        _ = NSApplication.shared
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let document = directory.appendingPathComponent("index.html")
        try """
        <!doctype html>
        <html><body><script>
        window.addEventListener("DOMContentLoaded", async () => {
          const reply = await window.macflow.files.list({ directory: "/example" });
          document.body.dataset.result = JSON.stringify({
            configured: window.macflow.configuration.value,
            reply,
            accent: getComputedStyle(document.documentElement).getPropertyValue("--macflow-accent").trim()
          });
          await window.macflow.surface.dismiss();
        });
        </script></body></html>
        """.write(to: document, atomically: true, encoding: .utf8)

        var requestedDirectory: String?
        var unexpectedActions: [String] = []
        var didDismiss = false
        let panel = try WebSurfacePanel(
            contentRect: NSRect(x: 0, y: 0, width: 640, height: 320),
            documentURL: document,
            surfaceConfiguration: ["value": "from-config"],
            theme: BuiltInThemeCatalog.tokyoNight,
            activates: false,
            requestHandler: { _, request in
                switch request.action {
                case "files.list":
                    requestedDirectory = request.payload["directory"] as? String
                    return [["name": "image.png", "thumbnail": "macflow-file://asset/example"]]
                case "surface.dismiss":
                    didDismiss = true
                    return true
                default:
                    unexpectedActions.append(request.action)
                    return nil
                }
            },
            onCompletedDrag: {}
        )
        defer { panel.close() }

        let dismissed = await waitUntil(timeout: 5) { didDismiss }
        try #require(dismissed)
        #expect(requestedDirectory == "/example")
        #expect(unexpectedActions.isEmpty)

        let evaluatedValue = try await panel.webView.evaluateJavaScript("document.body.dataset.result")
        let result = try #require(evaluatedValue as? String)
        #expect(result.contains("from-config"))
        #expect(result.contains("\"name\":\"image.png\""))
        #expect(result.contains("122, 162, 247"))
        #expect(panel.loadedDocumentURL?.standardizedFileURL == document.standardizedFileURL)
    }

    @Test
    func closedPanelIsReleased() throws {
        _ = NSApplication.shared
        let document = try makeDocument("<!doctype html><html><body></body></html>")
        defer { try? FileManager.default.removeItem(at: document.deletingLastPathComponent()) }
        weak var releasedPanel: WebSurfacePanel?

        try autoreleasepool {
            var panel: WebSurfacePanel? = try WebSurfacePanel(
                contentRect: NSRect(x: 0, y: 0, width: 320, height: 160),
                documentURL: document,
                surfaceConfiguration: [:],
                theme: BuiltInThemeCatalog.system,
                activates: false,
                requestHandler: { _, _ in nil },
                onCompletedDrag: {}
            )
            releasedPanel = panel
            panel?.close()
            panel = nil
        }

        try #require(waitOnRunLoop(timeout: 2) { releasedPanel == nil })
    }

    private func makeDocument(_ contents: String) throws -> URL {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let document = directory.appendingPathComponent("index.html")
        try contents.write(to: document, atomically: true, encoding: .utf8)
        return document
    }

    private func waitUntil(timeout: TimeInterval, condition: @escaping @MainActor () -> Bool) async -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while !condition() && Date() < deadline {
            try? await Task.sleep(nanoseconds: 10_000_000)
        }
        return condition()
    }

    private func waitOnRunLoop(timeout: TimeInterval, condition: @escaping () -> Bool) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while !condition() && Date() < deadline {
            RunLoop.main.run(until: min(deadline, Date().addingTimeInterval(0.01)))
        }
        return condition()
    }
}
