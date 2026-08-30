import Foundation
import XCTest
@testable import MacWorkflowCore

final class MacWorkflowCoreTests: XCTestCase {
    func testExactHalfSplitWithoutGap() {
        let frames = LayoutGeometry.columns(
            in: Frame(x: 0, y: 25, width: 1200, height: 800),
            ratios: [0.5, 0.5],
            gap: 0
        )
        XCTAssertEqual(frames, [
            Frame(x: 0, y: 25, width: 600, height: 800),
            Frame(x: 600, y: 25, width: 600, height: 800),
        ])
    }

    func testSplitSubtractsOneInnerGap() {
        let frames = LayoutGeometry.columns(
            in: Frame(x: 100, y: 20, width: 1000, height: 700),
            ratios: [0.65, 0.35],
            gap: 10
        )
        XCTAssertEqual(frames[0].width, 643.5)
        XCTAssertEqual(frames[1].x, 753.5)
        XCTAssertEqual(frames[1].width, 346.5)
    }

    func testXDGPaths() {
        let environment = ["HOME": "/Users/test", "XDG_CONFIG_HOME": "/custom/config"]
        XCTAssertEqual(
            ConfigurationLoader.workflowURL(environment: environment).path,
            "/custom/config/mac-workflow/config.json"
        )
    }

    func testHTTPParserWaitsForCompleteBody() {
        let incomplete = Data("POST /v1/test HTTP/1.1\r\nContent-Length: 5\r\n\r\n123".utf8)
        XCTAssertNil(HTTPParser.parse(incomplete))
        let complete = Data("POST /v1/test?a=b HTTP/1.1\r\nContent-Length: 5\r\n\r\n12345".utf8)
        let request = HTTPParser.parse(complete)
        XCTAssertEqual(request?.method, "POST")
        XCTAssertEqual(request?.path, "/v1/test")
        XCTAssertEqual(request?.queryItems, ["a": "b"])
        XCTAssertEqual(String(data: request?.body ?? Data(), encoding: .utf8), "12345")

        let malformedQuery = HTTPParser.parse(Data("GET /v1/windows?= HTTP/1.1\r\n\r\n".utf8))
        XCTAssertEqual(malformedQuery?.queryItems, [:])
    }

    func testHTTPURLBuilderHandlesIPv6Loopback() {
        XCTAssertEqual(
            HTTPURLBuilder.make(host: "::1", port: 17421, path: "/v1/health")?.absoluteString,
            "http://[::1]:17421/v1/health"
        )
        XCTAssertEqual(
            HTTPURLBuilder.make(host: "127.0.0.1", port: 17421, path: "/v1/health")?.absoluteString,
            "http://127.0.0.1:17421/v1/health"
        )
    }

    func testHTTPParserRejectsUnsafeContentLengths() {
        for value in ["-1", String(Int.max), "1048577", "invalid"] {
            let data = Data("POST / HTTP/1.1\r\nContent-Length: \(value)\r\n\r\n".utf8)
            XCTAssertEqual(HTTPParser.rejectionReason(data), "Invalid Content-Length")
            XCTAssertNil(HTTPParser.parse(data))
        }

        let duplicate = Data(
            "POST / HTTP/1.1\r\nContent-Length: 0\r\nContent-Length: 1048577\r\n\r\n".utf8
        )
        XCTAssertEqual(HTTPParser.rejectionReason(duplicate), "Invalid Content-Length")
        XCTAssertNil(HTTPParser.parse(duplicate))
    }

    func testRepositoryConfigurationDecodes() throws {
        let source = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("config.json")
        let configuration = try ConfigurationLoader.loadWorkflow(from: source)
        XCTAssertEqual(configuration.applications["ghostty"]?.bundleID, "com.mitchellh.ghostty")
        XCTAssertEqual(configuration.server.host, "127.0.0.1")
        XCTAssertEqual(configuration.hotkeys.first?.action.layout, "ghostty_full")
        XCTAssertEqual(configuration.hotkeys.last?.action.type, .showFileShelf)
        XCTAssertNoThrow(try configuration.validate())
    }

    func testConfigurationRejectsUnknownLayoutAction() throws {
        let source = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("config.json")
        let text = try String(contentsOf: source, encoding: .utf8)
            .replacingOccurrences(
                of: "\"layout\": \"ghostty_full\"",
                with: "\"layout\": \"missing\""
            )
        let configuration = try JSONDecoder().decode(WorkflowConfiguration.self, from: Data(text.utf8))
        XCTAssertThrowsError(try configuration.validate()) { error in
            XCTAssertEqual(error as? WorkflowValidationError, .invalidAction(0))
        }
    }

    func testConfigurationRejectsNonLoopbackServer() throws {
        let source = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("config.json")
        let text = try String(contentsOf: source, encoding: .utf8)
            .replacingOccurrences(of: "\"127.0.0.1\"", with: "\"0.0.0.0\"")
        let configuration = try JSONDecoder().decode(WorkflowConfiguration.self, from: Data(text.utf8))
        XCTAssertThrowsError(try configuration.validate()) { error in
            XCTAssertEqual(error as? WorkflowValidationError, .invalidServerHost("0.0.0.0"))
        }
    }

    func testNewestSupportedScreenshot() {
        let candidates = [
            ScreenshotCandidate(url: URL(fileURLWithPath: "/shots/new.txt"), modificationDate: Date(timeIntervalSince1970: 30), regularFile: true),
            ScreenshotCandidate(url: URL(fileURLWithPath: "/shots/old.png"), modificationDate: Date(timeIntervalSince1970: 10), regularFile: true),
            ScreenshotCandidate(url: URL(fileURLWithPath: "/shots/new.JPG"), modificationDate: Date(timeIntervalSince1970: 20), regularFile: true),
            ScreenshotCandidate(url: URL(fileURLWithPath: "/shots/folder.png"), modificationDate: Date(timeIntervalSince1970: 40), regularFile: false),
        ]
        XCTAssertEqual(
            ScreenshotFiles.newest(candidates: candidates, supportedExtensions: ["png", "jpg"])?.url.path,
            "/shots/new.JPG"
        )
    }

    func testPreviewSizePreservesAspectRatio() {
        XCTAssertEqual(
            ScreenshotFiles.previewSize(imageWidth: 1600, imageHeight: 900, maxWidth: 360, maxHeight: 260),
            Frame(x: 0, y: 0, width: 360, height: 202.5)
        )
        XCTAssertEqual(
            ScreenshotFiles.previewSize(imageWidth: 900, imageHeight: 1600, maxWidth: 360, maxHeight: 260),
            Frame(x: 0, y: 0, width: 146.25, height: 260)
        )
    }

    func testCaptureDisplaySelection() throws {
        XCTAssertEqual(
            try CapturePlanning.selectDisplay(requestedID: nil, availableIDs: [10, 20], mainID: 20),
            20
        )
        XCTAssertEqual(
            try CapturePlanning.selectDisplay(requestedID: 10, availableIDs: [10, 20], mainID: 20),
            10
        )
        XCTAssertThrowsError(
            try CapturePlanning.selectDisplay(requestedID: 30, availableIDs: [10, 20], mainID: 20)
        ) { error in
            XCTAssertEqual(error as? CapturePlanningError, .displayNotFound(30))
        }
    }

    func testCaptureDestinationAndCollision() {
        let directory = URL(fileURLWithPath: "/screenshots", isDirectory: true)
        let date = Date(timeIntervalSince1970: 0)
        let timeZone = TimeZone(secondsFromGMT: 0)!
        let first = CapturePlanning.destination(
            directory: directory,
            date: date,
            timeZone: timeZone,
            fileExists: { _ in false }
        )
        XCTAssertEqual(first.path, "/screenshots/Screenshot 1970-01-01 at 00.00.00.png")

        let second = CapturePlanning.destination(
            directory: directory,
            date: date,
            timeZone: timeZone,
            fileExists: { $0 == first.path }
        )
        XCTAssertEqual(second.path, "/screenshots/Screenshot 1970-01-01 at 00.00.00-2.png")
    }

    func testCaptureAllocatorReservesUniqueConcurrentPaths() {
        let allocator = CapturePathAllocator()
        let directory = URL(fileURLWithPath: "/screenshots", isDirectory: true)
        let date = Date(timeIntervalSince1970: 0)
        let timeZone = TimeZone(secondsFromGMT: 0)!
        let lock = NSLock()
        var paths: [String] = []

        DispatchQueue.concurrentPerform(iterations: 10) { _ in
            let url = allocator.reserve(
                directory: directory,
                date: date,
                timeZone: timeZone,
                fileExists: { _ in false }
            )
            lock.lock()
            paths.append(url.path)
            lock.unlock()
        }

        XCTAssertEqual(Set(paths).count, 10)
    }

    func testScreenshotSuppressionIsInMemoryAndManualShowStillWorks() {
        var state = ScreenshotPresentationState()
        let date = Date(timeIntervalSince1970: 10)
        let path = "/screenshots/capture.png"

        state.suppressNext(path: path, existingModificationDate: nil)
        XCTAssertTrue(state.consumeSuppression(path: path, modificationDate: date))
        XCTAssertFalse(state.consumeSuppression(path: path, modificationDate: date))
        XCTAssertFalse(state.shouldShow(path: path, modificationDate: date, force: false))
        XCTAssertTrue(state.shouldShow(path: path, modificationDate: date, force: true))
    }

    func testSuppressionWaitsForNewVersionOfExistingPath() {
        var state = ScreenshotPresentationState()
        let oldDate = Date(timeIntervalSince1970: 10)
        let newDate = Date(timeIntervalSince1970: 20)
        let path = "/screenshots/capture.png"

        state.suppressNext(path: path, existingModificationDate: oldDate)
        XCTAssertFalse(state.consumeSuppression(path: path, modificationDate: oldDate))
        XCTAssertTrue(state.consumeSuppression(path: path, modificationDate: newDate))
        XCTAssertFalse(state.shouldShow(path: path, modificationDate: newDate, force: false))
    }

    func testDirectChildDetectionRejectsOutsideAndNestedPaths() {
        let directory = URL(fileURLWithPath: "/screenshots", isDirectory: true)
        XCTAssertTrue(ScreenshotFiles.isDirectChild(path: "/screenshots/capture.png", of: directory))
        XCTAssertFalse(ScreenshotFiles.isDirectChild(path: "/other/capture.png", of: directory))
        XCTAssertFalse(ScreenshotFiles.isDirectChild(path: "/screenshots/nested/capture.png", of: directory))
    }

    func testGenericKeyResolutionAndValidationVocabulary() {
        XCTAssertNotNil(KeyCodeResolver.resolve("g"))
        XCTAssertNotNil(KeyCodeResolver.resolve("escape"))
        XCTAssertNil(KeyCodeResolver.resolve("not-a-key"))
        XCTAssertTrue(KeyCodeResolver.supportedModifiers.contains("cmd"))
    }

    func testDragDurationBoundaries() throws {
        XCTAssertEqual(try InputValidation.dragDelayMicroseconds(duration: 60, steps: 20), 3_000_000)
        XCTAssertThrowsError(try InputValidation.dragDelayMicroseconds(duration: 60.001, steps: 20))
        XCTAssertThrowsError(try InputValidation.dragDelayMicroseconds(duration: -.infinity, steps: 20))
    }

    func testOverlappingSuspensionsRemainSuspendedUntilAllResume() {
        var gate = SuspensionGate()
        gate.suspend()
        gate.suspend()
        gate.resume()
        XCTAssertTrue(gate.isSuspended)
        gate.resume()
        XCTAssertFalse(gate.isSuspended)
    }

    func testExistingTokenPermissionsAreRepaired() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let token = directory.appendingPathComponent("token")
        try "secret".write(to: token, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: token.path)

        try SecureFilePermissions.ensureOwnerReadWrite(token)

        let attributes = try FileManager.default.attributesOfItem(atPath: token.path)
        XCTAssertEqual((attributes[.posixPermissions] as? NSNumber)?.intValue, 0o600)
    }

    func testPathWatcherReopensAfterDirectoryReplacement() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        let watched = root.appendingPathComponent("watched", isDirectory: true)
        let moved = root.appendingPathComponent("moved", isDirectory: true)
        try FileManager.default.createDirectory(at: watched, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }

        let first = expectation(description: "initial write observed")
        let replacement = expectation(description: "replacement write observed")
        let lock = NSLock()
        var sawFirst = false
        var sawReplacement = false
        let queue = DispatchQueue(label: "PathWatcherServiceTests")
        let watcher = PathWatcherService(directory: watched, debounceSeconds: 0.05, queue: queue) {
            lock.lock()
            defer { lock.unlock() }
            if FileManager.default.fileExists(atPath: watched.appendingPathComponent("second").path), !sawReplacement {
                sawReplacement = true
                replacement.fulfill()
            } else if FileManager.default.fileExists(atPath: watched.appendingPathComponent("first").path), !sawFirst {
                sawFirst = true
                first.fulfill()
            }
        }
        try watcher.start()
        try Data("first".utf8).write(to: watched.appendingPathComponent("first"))
        wait(for: [first], timeout: 2)

        try FileManager.default.moveItem(at: watched, to: moved)
        try FileManager.default.createDirectory(at: watched, withIntermediateDirectories: true)
        Thread.sleep(forTimeInterval: 0.2)
        try Data("second".utf8).write(to: watched.appendingPathComponent("second"))
        wait(for: [replacement], timeout: 2)
        watcher.stop()
    }

    func testExplicitPreviewCaptureEventIsHandledOnce() {
        var state = ScreenshotPresentationState()
        let date = Date(timeIntervalSince1970: 10)
        let path = "/screenshots/capture.png"
        state.suppressNext(path: path, existingModificationDate: nil)
        XCTAssertTrue(state.consumeSuppression(path: path, modificationDate: date))
        XCTAssertFalse(state.shouldShow(path: path, modificationDate: date, force: false))
    }

    func testFileCatalogFiltersAndSortsNewestFirst() {
        let candidates = [
            ScreenshotCandidate(url: URL(fileURLWithPath: "/shots/older.png"), modificationDate: Date(timeIntervalSince1970: 10), regularFile: true),
            ScreenshotCandidate(url: URL(fileURLWithPath: "/shots/newer.JPG"), modificationDate: Date(timeIntervalSince1970: 30), regularFile: true),
            ScreenshotCandidate(url: URL(fileURLWithPath: "/shots/newest.txt"), modificationDate: Date(timeIntervalSince1970: 40), regularFile: true),
            ScreenshotCandidate(url: URL(fileURLWithPath: "/shots/folder.png"), modificationDate: Date(timeIntervalSince1970: 50), regularFile: false),
        ]
        XCTAssertEqual(
            FileCatalog.sortedItems(candidates: candidates, supportedExtensions: ["png", "jpg"]).map(\.url.lastPathComponent),
            ["newer.JPG", "older.png"]
        )
    }
}
