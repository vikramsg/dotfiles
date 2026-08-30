import AppKit
import Foundation

final class ApplicationService {
    func all() -> [[String: Any]] {
        NSWorkspace.shared.runningApplications
            .filter { $0.activationPolicy == .regular }
            .map {
                [
                    "pid": $0.processIdentifier,
                    "bundle_id": $0.bundleIdentifier ?? "",
                    "name": $0.localizedName ?? "",
                    "active": $0.isActive,
                    "hidden": $0.isHidden,
                ]
            }
    }

    func running(bundleID: String) -> NSRunningApplication? {
        NSWorkspace.shared.runningApplications.first {
            $0.bundleIdentifier == bundleID && $0.activationPolicy == .regular
        }
    }

    func launch(bundleID: String, completion: @escaping (Result<NSRunningApplication, Error>) -> Void) {
        if let running = running(bundleID: bundleID) {
            completion(.success(running))
            return
        }
        guard let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleID) else {
            completion(.failure(AutomationError.applicationNotFound(bundleID)))
            return
        }
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.activates = true
        NSWorkspace.shared.openApplication(at: url, configuration: configuration) { app, error in
            DispatchQueue.main.async {
                if let app {
                    completion(.success(app))
                } else {
                    completion(.failure(error ?? AutomationError.applicationNotFound(bundleID)))
                }
            }
        }
    }
}
