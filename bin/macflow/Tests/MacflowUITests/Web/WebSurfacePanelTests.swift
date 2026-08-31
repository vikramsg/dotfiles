import AppKit
import XCTest
@testable import MacflowUI

final class WebSurfacePanelTests: XCTestCase {
    func testUserDocumentReceivesConfigurationThemeAndBridgeReplies() throws {
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

        let pageReady = expectation(description: "page state ready")
        let panel = try WebSurfacePanel(
            contentRect: NSRect(x: 0, y: 0, width: 640, height: 320),
            documentURL: document,
            surfaceConfiguration: ["value": "from-config"],
            theme: BuiltInThemeCatalog.tokyoNight,
            activates: false,
            requestHandler: { _, request in
                switch request.action {
                case "files.list":
                    XCTAssertEqual(request.payload["directory"] as? String, "/example")
                    return [["name": "image.png", "thumbnail": "macflow-file://asset/example"]]
                case "surface.dismiss":
                    pageReady.fulfill()
                    return true
                default:
                    XCTFail("Unexpected bridge action: \(request.action)")
                    return nil
                }
            },
            onCompletedDrag: {}
        )
        defer { panel.close() }

        wait(for: [pageReady], timeout: 5)
        let evaluated = expectation(description: "page state")
        panel.webView.evaluateJavaScript("document.body.dataset.result") { value, error in
            XCTAssertNil(error)
            let result = value as? String
            XCTAssertTrue(result?.contains("from-config") == true)
            XCTAssertTrue(result?.contains("\"name\":\"image.png\"") == true)
            XCTAssertTrue(result?.contains("122, 162, 247") == true)
            evaluated.fulfill()
        }
        wait(for: [evaluated], timeout: 5)
        XCTAssertEqual(panel.loadedDocumentURL?.standardizedFileURL, document.standardizedFileURL)
    }

    func testClosedPanelIsReleased() throws {
        _ = NSApplication.shared
        let document = try makeDocument("<!doctype html><html><body></body></html>")
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

        let deadline = Date().addingTimeInterval(2)
        while releasedPanel != nil && RunLoop.current.run(mode: .default, before: deadline) && Date() < deadline {}
        XCTAssertNil(releasedPanel)
    }

    private func makeDocument(_ contents: String) throws -> URL {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let document = directory.appendingPathComponent("index.html")
        try contents.write(to: document, atomically: true, encoding: .utf8)
        addTeardownBlock { try? FileManager.default.removeItem(at: directory) }
        return document
    }
}
