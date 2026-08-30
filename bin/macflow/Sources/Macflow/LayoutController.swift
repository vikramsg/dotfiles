import AppKit
import MacflowCore

final class LayoutController {
    private let windows: WindowService
    private let screens: ScreenService
    private let applicationService: ApplicationService
    private let applications: [String: WorkflowConfiguration.Application]
    private let layouts: [String: WorkflowConfiguration.Layout]

    init(
        applications: [String: WorkflowConfiguration.Application],
        layouts: [String: WorkflowConfiguration.Layout],
        applicationService: ApplicationService,
        windows: WindowService,
        screens: ScreenService
    ) {
        self.applications = applications
        self.layouts = layouts
        self.applicationService = applicationService
        self.windows = windows
        self.screens = screens
    }

    func apply(layout identifier: String, completion: @escaping (Result<Void, Error>) -> Void) {
        guard let layout = layouts[identifier] else {
            completion(.failure(NSError(
                domain: "MacWorkflow.Layout",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: "Unknown layout: \(identifier)"]
            )))
            return
        }
        resolveWindows(for: layout.applications, index: 0, resolved: [:]) { [weak self] result in
            guard let self else { return }
            switch result {
            case let .failure(error): completion(.failure(error))
            case let .success(resolved):
                do {
                    try self.arrange(layout: layout, windows: resolved, completion: completion)
                } catch {
                    completion(.failure(error))
                }
            }
        }
    }

    private func resolveWindows(
        for aliases: [String],
        index: Int,
        resolved: [String: WindowRecord],
        completion: @escaping (Result<[String: WindowRecord], Error>) -> Void
    ) {
        guard index < aliases.count else {
            completion(.success(resolved))
            return
        }
        let alias = aliases[index]
        guard let app = applications[alias] else {
            completion(.failure(NSError(
                domain: "MacWorkflow.Layout",
                code: 2,
                userInfo: [NSLocalizedDescriptionKey: "Unknown application: \(alias)"]
            )))
            return
        }
        ensureWindow(bundleID: app.bundleID) { [weak self] result in
            guard let self else { return }
            switch result {
            case let .failure(error): completion(.failure(error))
            case let .success(window):
                var next = resolved
                next[alias] = window
                self.resolveWindows(for: aliases, index: index + 1, resolved: next, completion: completion)
            }
        }
    }

    private func ensureWindow(bundleID: String, completion: @escaping (Result<WindowRecord, Error>) -> Void) {
        if let window = windows.targetWindow(bundleID: bundleID) {
            completion(.success(window))
            return
        }
        let wasRunning = applicationService.running(bundleID: bundleID) != nil
        applicationService.launch(bundleID: bundleID) { [weak self] result in
            guard let self else { return }
            switch result {
            case let .failure(error): completion(.failure(error))
            case .success:
                if wasRunning {
                    self.windows.createWindow(bundleID: bundleID)
                    self.pollForWindow(bundleID: bundleID, attempts: 40, completion: completion)
                } else {
                    self.pollForWindow(bundleID: bundleID, attempts: 10) { firstResult in
                        if case .success = firstResult {
                            completion(firstResult)
                        } else {
                            self.windows.createWindow(bundleID: bundleID)
                            self.pollForWindow(bundleID: bundleID, attempts: 40, completion: completion)
                        }
                    }
                }
            }
        }
    }

    private func pollForWindow(
        bundleID: String,
        attempts: Int,
        completion: @escaping (Result<WindowRecord, Error>) -> Void
    ) {
        if let window = windows.targetWindow(bundleID: bundleID) {
            completion(.success(window))
        } else if attempts == 0 {
            completion(.failure(AutomationError.windowNotFound(bundleID)))
        } else {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [weak self] in
                self?.pollForWindow(bundleID: bundleID, attempts: attempts - 1, completion: completion)
            }
        }
    }

    private func arrange(
        layout: WorkflowConfiguration.Layout,
        windows resolved: [String: WindowRecord],
        completion: @escaping (Result<Void, Error>) -> Void
    ) throws {
        guard let firstAlias = layout.applications.first, let firstWindow = resolved[firstAlias] else {
            throw AutomationError.windowNotFound("layout")
        }
        let targetAlias = layout.targetScreenApplication ?? firstAlias
        let targetWindow = resolved[targetAlias] ?? firstWindow
        guard let screen = screens.containing(targetWindow.frame) else {
            throw AutomationError.windowNotFound("screen")
        }

        let plan = try LayoutPlanner.plan(layout: layout, screen: screen.visibleFrame.workflowFrame)
        execute(plan.operations, index: 0, windows: resolved, completion: completion)
    }

    private func execute(
        _ operations: [LayoutOperation],
        index: Int,
        windows resolved: [String: WindowRecord],
        completion: @escaping (Result<Void, Error>) -> Void
    ) {
        guard index < operations.count else {
            completion(.success(()))
            return
        }

        do {
            let operation = operations[index]
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
                DispatchQueue.main.asyncAfter(deadline: .now() + seconds) { [weak self] in
                    self?.execute(operations, index: index + 1, windows: resolved, completion: completion)
                }
                return
            case let .focus(alias):
                guard let window = resolved[alias] else {
                    throw AutomationError.windowNotFound(alias)
                }
                try windows.focus(window)
            }
            execute(operations, index: index + 1, windows: resolved, completion: completion)
        } catch {
            completion(.failure(error))
        }
    }
}
