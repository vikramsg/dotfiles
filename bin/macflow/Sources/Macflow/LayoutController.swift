import AppKit
import MacflowCore

protocol LayoutApplications {
    func running(bundleID: String) -> NSRunningApplication?
    func launch(bundleID: String, completion: @escaping (Result<NSRunningApplication, Error>) -> Void)
}

protocol LayoutWindows {
    func targetWindow(bundleID: String) -> WindowRecord?
    func createWindow(bundleID: String)
    func setFrame(_ frame: CGRect, for window: WindowRecord) throws
    func raise(_ window: WindowRecord) throws
    func focus(_ window: WindowRecord) throws
}

protocol LayoutScreens {
    func containing(_ frame: CGRect) -> ScreenRecord?
}

extension ApplicationService: LayoutApplications {}
extension WindowService: LayoutWindows {}
extension ScreenService: LayoutScreens {}

@MainActor
final class LayoutController {
    private let windows: any LayoutWindows
    private let screens: any LayoutScreens
    private let applicationService: any LayoutApplications
    private let applications: [String: WorkflowConfiguration.Application]
    private let layouts: [String: WorkflowConfiguration.Layout]

    init(
        applications: [String: WorkflowConfiguration.Application],
        layouts: [String: WorkflowConfiguration.Layout],
        applicationService: any LayoutApplications,
        windows: any LayoutWindows,
        screens: any LayoutScreens
    ) {
        self.applications = applications
        self.layouts = layouts
        self.applicationService = applicationService
        self.windows = windows
        self.screens = screens
    }

    func apply(layout identifier: String) async throws {
        guard let layout = layouts[identifier] else {
            throw NSError(
                domain: "MacWorkflow.Layout",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: "Unknown layout: \(identifier)"]
            )
        }
        let resolved = try await resolveWindows(for: layout.applications)
        try await arrange(layout: layout, windows: resolved)
    }

    private func resolveWindows(for aliases: [String]) async throws -> [String: WindowRecord] {
        var resolved: [String: WindowRecord] = [:]
        for alias in aliases {
            guard let app = applications[alias] else {
                throw NSError(
                    domain: "MacWorkflow.Layout", code: 2,
                    userInfo: [NSLocalizedDescriptionKey: "Unknown application: \(alias)"]
                )
            }
            resolved[alias] = try await ensureWindow(bundleID: app.bundleID)
        }
        return resolved
    }

    private func ensureWindow(bundleID: String) async throws -> WindowRecord {
        if let window = windows.targetWindow(bundleID: bundleID) {
            return window
        }
        let wasRunning = applicationService.running(bundleID: bundleID) != nil
        let _: NSRunningApplication = try await withCheckedThrowingContinuation { continuation in
            applicationService.launch(bundleID: bundleID) { continuation.resume(with: $0) }
        }
        if !wasRunning {
            do {
                return try await pollForWindow(bundleID: bundleID, attempts: 10)
            } catch AutomationError.windowNotFound {
                // Some applications launch without creating a window.
            }
        }
        windows.createWindow(bundleID: bundleID)
        return try await pollForWindow(bundleID: bundleID, attempts: 40)
    }

    private func pollForWindow(bundleID: String, attempts: Int) async throws -> WindowRecord {
        for attempt in 0...attempts {
            try Task.checkCancellation()
            if let window = windows.targetWindow(bundleID: bundleID) { return window }
            if attempt < attempts { try await Task.sleep(for: .milliseconds(100)) }
        }
        throw AutomationError.windowNotFound(bundleID)
    }

    private func arrange(
        layout: WorkflowConfiguration.Layout,
        windows resolved: [String: WindowRecord]
    ) async throws {
        guard let firstAlias = layout.applications.first, let firstWindow = resolved[firstAlias] else {
            throw AutomationError.windowNotFound("layout")
        }
        let targetAlias = layout.targetScreenApplication ?? firstAlias
        let targetWindow = resolved[targetAlias] ?? firstWindow
        guard let screen = screens.containing(targetWindow.frame) else {
            throw AutomationError.windowNotFound("screen")
        }

        let plan = try LayoutPlanner.plan(layout: layout, screen: screen.visibleFrame.workflowFrame)
        try await execute(plan.operations, windows: resolved)
    }

    private func execute(
        _ operations: [LayoutOperation],
        windows resolved: [String: WindowRecord]
    ) async throws {
        for operation in operations {
            try Task.checkCancellation()
            switch operation {
            case let .setFrame(alias, frame):
                guard let window = resolved[alias] else {
                    throw AutomationError.windowNotFound(alias)
                }
                try windows.setFrame(
                    CGRect(x: frame.x, y: frame.y, width: frame.width, height: frame.height),
                    for: window
                )
            case let .raise(alias):
                guard let window = resolved[alias] else {
                    throw AutomationError.windowNotFound(alias)
                }
                try windows.raise(window)
            case let .wait(seconds):
                try await Task.sleep(for: .seconds(seconds))
            case let .focus(alias):
                guard let window = resolved[alias] else {
                    throw AutomationError.windowNotFound(alias)
                }
                try windows.focus(window)
            }
        }
    }
}
