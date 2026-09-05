import AppKit
import MacflowCore
import Testing
@testable import Macflow

@Suite(.serialized) @MainActor
struct LayoutBehaviorTests {
    @Test func columnsArrangeParticipantsWithoutTouchingOtherWindows() async throws {
        let desktop = Desktop()
        let untouched = desktop.frames[3]
        let controller = try controller(desktop, type: "columns")

        try await controller.apply(layout: "work")

        #expect(desktop.frames[1] == CGRect(x: 0, y: 25, width: 496, height: 775))
        #expect(desktop.frames[2] == CGRect(x: 504, y: 25, width: 496, height: 775))
        #expect(desktop.focusedWindow == 1)
        #expect(desktop.frames[3] == untouched)
    }

    @Test func maximizeLeavesOtherApplicationsAlone() async throws {
        let desktop = Desktop()
        let otherFrames = [desktop.frames[2], desktop.frames[3]]
        try await controller(desktop, type: "maximize").apply(layout: "work")
        #expect(desktop.frames[1] == desktop.screen.visibleFrame)
        #expect(desktop.focusedWindow == 1)
        #expect([desktop.frames[2], desktop.frames[3]] == otherFrames)
    }

    @Test func missingCurrentSpaceWindowIsCreatedWithoutMovingAnotherSpacesWindow() async throws {
        let desktop = Desktop()
        desktop.currentSpaceWindows.removeValue(forKey: "example.first")
        let otherSpaceFrame = desktop.frames[1]

        try await controller(desktop, type: "maximize").apply(layout: "work")

        let created = try #require(desktop.currentSpaceWindows["example.first"])
        #expect(created != 1)
        #expect(desktop.frames[created] == desktop.screen.visibleFrame)
        #expect(desktop.frames[1] == otherSpaceFrame)
        #expect(desktop.focusedWindow == created)
    }

    @Test func stoppedApplicationIsLaunchedAndItsWindowArranged() async throws {
        let desktop = Desktop()
        desktop.runningApplications.remove("example.first")
        desktop.currentSpaceWindows.removeValue(forKey: "example.first")
        try await controller(desktop, type: "maximize").apply(layout: "work")
        let window = try #require(desktop.currentSpaceWindows["example.first"])
        #expect(desktop.runningApplications.contains("example.first"))
        #expect(desktop.frames[window] == desktop.screen.visibleFrame)
        #expect(desktop.focusedWindow == window)
    }

    @Test func failedWindowMutationIsReportedWithoutStealingFocus() async throws {
        let desktop = Desktop()
        desktop.rejectFrameChanges = true
        let previousFocus = desktop.focusedWindow
        let previousFrames = desktop.frames
        let controller = try controller(desktop, type: "columns")
        await #expect(throws: DesktopFailure.refused) { try await controller.apply(layout: "work") }
        #expect(desktop.focusedWindow == previousFocus)
        #expect(desktop.frames == previousFrames)
    }

    private func controller(_ desktop: Desktop, type: String) throws -> LayoutController {
        let aliases = type == "columns" ? ["first", "second"] : ["first"]
        let layout = WorkflowConfiguration.Layout(
            type: type == "columns" ? .columns : .maximize,
            applications: aliases, ratios: [1, 1], focus: "first", gap: 8
        )
        let apps = try JSONDecoder().decode(
            [String: WorkflowConfiguration.Application].self,
            from: Data(#"{"first":{"bundle_id":"example.first"},"second":{"bundle_id":"example.second"}}"#.utf8)
        )
        return LayoutController(
            applications: apps, layouts: ["work": layout],
            applicationService: desktop, windows: desktop, screens: desktop
        )
    }
}

private enum DesktopFailure: Error { case refused }

private final class Desktop: LayoutApplications, LayoutWindows, LayoutScreens {
    var runningApplications: Set<String> = ["example.first", "example.second"]
    var currentSpaceWindows: [String: Int32] = ["example.first": 1, "example.second": 2]
    var frames: [Int32: CGRect] = [
        1: CGRect(x: 40, y: 50, width: 400, height: 300),
        2: CGRect(x: 60, y: 70, width: 400, height: 300),
        3: CGRect(x: 80, y: 90, width: 400, height: 300),
    ]
    var focusedWindow: Int32 = 3
    var rejectFrameChanges = false
    let screen = ScreenRecord(
        id: 1, name: "Test", frame: CGRect(x: 0, y: 0, width: 1000, height: 800),
        visibleFrame: CGRect(x: 0, y: 25, width: 1000, height: 775), main: true
    )

    func running(bundleID: String) -> NSRunningApplication? {
        runningApplications.contains(bundleID) ? .current : nil
    }

    func launch(bundleID: String, completion: @escaping (Result<NSRunningApplication, Error>) -> Void) {
        if runningApplications.insert(bundleID).inserted { createWindow(bundleID: bundleID) }
        completion(.success(.current))
    }

    func targetWindow(bundleID: String) -> WindowRecord? {
        guard let id = currentSpaceWindows[bundleID], let frame = frames[id] else { return nil }
        return WindowRecord(
            pid: id, index: 0, element: AXUIElementCreateApplication(id), title: bundleID,
            frame: frame, minimized: false, standard: true, onScreen: true, main: focusedWindow == id
        )
    }

    func createWindow(bundleID: String) {
        let id = (frames.keys.max() ?? 0) + 1
        frames[id] = CGRect(x: 0, y: 25, width: 100, height: 100)
        currentSpaceWindows[bundleID] = id
    }

    func setFrame(_ frame: CGRect, for window: WindowRecord) throws {
        if rejectFrameChanges { throw DesktopFailure.refused }
        frames[window.pid] = frame
    }

    func raise(_ window: WindowRecord) throws { focusedWindow = window.pid }
    func focus(_ window: WindowRecord) throws { focusedWindow = window.pid }
    func containing(_ frame: CGRect) -> ScreenRecord? { screen }
}
