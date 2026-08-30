import AppKit
import ApplicationServices
import CoreGraphics
import Foundation

enum AutomationError: LocalizedError {
    case applicationNotFound(String)
    case applicationNotRunning(String)
    case accessibilityRequired
    case windowNotFound(String)
    case accessibility(AXError, String)
    case invalidFrame

    var errorDescription: String? {
        switch self {
        case let .applicationNotFound(bundleID): return "Application is not installed: \(bundleID)"
        case let .applicationNotRunning(bundleID): return "Application is not running: \(bundleID)"
        case .accessibilityRequired: return "Accessibility permission is required"
        case let .windowNotFound(identifier): return "Window not found: \(identifier)"
        case let .accessibility(error, operation): return "Accessibility operation \(operation) failed: \(error.rawValue)"
        case .invalidFrame: return "Frame must have positive width and height"
        }
    }
}

struct WindowRecord {
    let pid: pid_t
    let index: Int
    let element: AXUIElement
    let title: String
    let frame: CGRect
    let minimized: Bool
    let standard: Bool
    let onScreen: Bool
    let main: Bool

    var identifier: String { "\(pid):\(index)" }

    var json: [String: Any] {
        [
            "id": identifier,
            "pid": pid,
            "index": index,
            "title": title,
            "frame": frame.dictionary,
            "minimized": minimized,
            "standard": standard,
            "on_screen": onScreen,
            "main": main,
        ]
    }
}

struct FocusSnapshot {
    let application: NSRunningApplication
    let window: AXUIElement?
    let frame: CGRect?
}

final class WindowService {
    private let applications: ApplicationService

    init(applications: ApplicationService) {
        self.applications = applications
    }

    func windows(bundleID: String) throws -> [WindowRecord] {
        guard PermissionService.accessibility() else { throw AutomationError.accessibilityRequired }
        guard let app = applications.running(bundleID: bundleID) else {
            throw AutomationError.applicationNotRunning(bundleID)
        }
        return try windows(pid: app.processIdentifier)
    }

    func windows(pid: pid_t) throws -> [WindowRecord] {
        let application = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(application, 2)
        let elements: [AXUIElement] = try copy(application, kAXWindowsAttribute as CFString)
        let mainWindow: AXUIElement? = try? copy(application, kAXMainWindowAttribute as CFString)
        let visibleWindows = onScreenWindows()

        return elements.enumerated().compactMap { index, element in
            guard let frame = try? frame(of: element) else { return nil }
            let role: String = (try? copy(element, kAXRoleAttribute as CFString)) ?? ""
            let subrole: String = (try? copy(element, kAXSubroleAttribute as CFString)) ?? ""
            let minimized: Bool = (try? copy(element, kAXMinimizedAttribute as CFString)) ?? false
            let title: String = (try? copy(element, kAXTitleAttribute as CFString)) ?? ""
            let number: NSNumber? = try? copy(element, "AXWindowNumber" as CFString)
            return WindowRecord(
                pid: pid,
                index: index,
                element: element,
                title: title,
                frame: frame,
                minimized: minimized,
                standard: role == (kAXWindowRole as String) && subrole == (kAXStandardWindowSubrole as String),
                onScreen: number.map { visibleWindows.ids.contains(CGWindowID($0.uint32Value)) }
                    ?? visibleWindows.framesByPID[pid, default: []].contains(where: { approximatelyEqual($0, frame) }),
                main: mainWindow.map { CFEqual($0, element) } ?? false
            )
        }
    }

    func window(identifier: String) throws -> WindowRecord {
        let parts = identifier.split(separator: ":")
        guard parts.count == 2, let pid = pid_t(parts[0]), let index = Int(parts[1]) else {
            throw AutomationError.windowNotFound(identifier)
        }
        guard let window = try windows(pid: pid).first(where: { $0.index == index }) else {
            throw AutomationError.windowNotFound(identifier)
        }
        return window
    }

    func targetWindow(bundleID: String) -> WindowRecord? {
        guard let windows = try? windows(bundleID: bundleID) else { return nil }
        let candidates = windows.filter { $0.standard && !$0.minimized && $0.onScreen }
        return candidates.first(where: \.main) ?? candidates.first
    }

    func setFrame(_ frame: CGRect, for window: WindowRecord) throws {
        guard frame.width > 0, frame.height > 0 else { throw AutomationError.invalidFrame }
        var origin = frame.origin
        var size = frame.size
        guard let position = AXValueCreate(.cgPoint, &origin),
              let dimensions = AXValueCreate(.cgSize, &size)
        else { throw AutomationError.invalidFrame }
        try set(window.element, kAXPositionAttribute as CFString, position)
        try set(window.element, kAXSizeAttribute as CFString, dimensions)
    }

    func raise(_ window: WindowRecord) throws {
        if window.minimized {
            try unminimize(window)
        }
        if let app = NSRunningApplication(processIdentifier: window.pid) {
            app.activate()
        }
        let application = AXUIElementCreateApplication(window.pid)
        try set(application, kAXFrontmostAttribute as CFString, kCFBooleanTrue)
        let result = AXUIElementPerformAction(window.element, kAXRaiseAction as CFString)
        if result != .success { throw AutomationError.accessibility(result, "raise") }
    }

    func focus(_ window: WindowRecord) throws {
        try raise(window)
        try set(window.element, kAXFocusedAttribute as CFString, kCFBooleanTrue)
    }

    func unminimize(_ window: WindowRecord) throws {
        try set(window.element, kAXMinimizedAttribute as CFString, kCFBooleanFalse)
    }

    func createWindow(bundleID: String) {
        guard let app = applications.running(bundleID: bundleID) else { return }
        app.activate()
        let source = CGEventSource(stateID: .combinedSessionState)
        let down = CGEvent(keyboardEventSource: source, virtualKey: 45, keyDown: true)
        let up = CGEvent(keyboardEventSource: source, virtualKey: 45, keyDown: false)
        down?.flags = .maskCommand
        up?.flags = .maskCommand
        down?.post(tap: .cghidEventTap)
        up?.post(tap: .cghidEventTap)
    }

    func captureFocus() -> FocusSnapshot? {
        guard let application = NSWorkspace.shared.frontmostApplication else { return nil }
        let appElement = AXUIElementCreateApplication(application.processIdentifier)
        let window: AXUIElement? = try? copy(appElement, kAXFocusedWindowAttribute as CFString)
        return FocusSnapshot(
            application: application,
            window: window,
            frame: window.flatMap { try? frame(of: $0) }
        )
    }

    func restoreFocus(_ snapshot: FocusSnapshot?) {
        guard let snapshot else { return }
        snapshot.application.activate()
        let application = AXUIElementCreateApplication(snapshot.application.processIdentifier)
        try? set(application, kAXFrontmostAttribute as CFString, kCFBooleanTrue)
        if let window = snapshot.window {
            AXUIElementPerformAction(window, kAXRaiseAction as CFString)
            try? set(window, kAXFocusedAttribute as CFString, kCFBooleanTrue)
        }
    }

    private func frame(of element: AXUIElement) throws -> CGRect {
        let position: AXValue = try copy(element, kAXPositionAttribute as CFString)
        let size: AXValue = try copy(element, kAXSizeAttribute as CFString)
        var point = CGPoint.zero
        var dimensions = CGSize.zero
        guard AXValueGetValue(position, .cgPoint, &point), AXValueGetValue(size, .cgSize, &dimensions) else {
            throw AutomationError.invalidFrame
        }
        return CGRect(origin: point, size: dimensions)
    }

    private func copy<T>(_ element: AXUIElement, _ attribute: CFString) throws -> T {
        var value: CFTypeRef?
        let result = AXUIElementCopyAttributeValue(element, attribute, &value)
        guard result == .success else { throw AutomationError.accessibility(result, attribute as String) }
        guard let typed = value as? T else { throw AutomationError.accessibility(.failure, attribute as String) }
        return typed
    }

    private func set(_ element: AXUIElement, _ attribute: CFString, _ value: CFTypeRef) throws {
        let result = AXUIElementSetAttributeValue(element, attribute, value)
        guard result == .success else { throw AutomationError.accessibility(result, attribute as String) }
    }

    private func approximatelyEqual(_ left: CGRect, _ right: CGRect) -> Bool {
        abs(left.minX - right.minX) < 2
            && abs(left.minY - right.minY) < 2
            && abs(left.width - right.width) < 2
            && abs(left.height - right.height) < 2
    }

    private func onScreenWindows() -> (ids: Set<CGWindowID>, framesByPID: [pid_t: [CGRect]]) {
        let options: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
        guard let windows = CGWindowListCopyWindowInfo(options, kCGNullWindowID) as? [[String: Any]] else {
            return ([], [:])
        }
        let ids = Set(windows.compactMap {
            ($0[kCGWindowNumber as String] as? NSNumber).map { CGWindowID($0.uint32Value) }
        })
        var framesByPID: [pid_t: [CGRect]] = [:]
        for window in windows {
            guard let ownerPID = window[kCGWindowOwnerPID as String] as? NSNumber,
                  let bounds = window[kCGWindowBounds as String] as? [String: Any],
                  let x = bounds["X"] as? Double,
                  let y = bounds["Y"] as? Double,
                  let width = bounds["Width"] as? Double,
                  let height = bounds["Height"] as? Double
            else { continue }
            framesByPID[pid_t(ownerPID.int32Value), default: []].append(
                CGRect(x: x, y: y, width: width, height: height)
            )
        }
        return (ids, framesByPID)
    }
}
