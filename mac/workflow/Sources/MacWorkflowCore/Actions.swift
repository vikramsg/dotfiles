import Darwin
import Foundation

public enum AutomationActionType: String, Codable, Equatable {
    case applyLayout = "apply_layout"
    case showFileShelf = "show_file_shelf"
}

public enum LayoutType: String, Codable, Equatable {
    case maximize
    case columns
}

public enum WorkflowValidationError: LocalizedError, Equatable {
    case invalidServerHost(String)
    case invalidLayout(String)
    case invalidAction(Int)
    case invalidShelf(String)

    public var errorDescription: String? {
        switch self {
        case let .invalidServerHost(host): return "Server host must be loopback, got: \(host)"
        case let .invalidLayout(name): return "Invalid layout configuration: \(name)"
        case let .invalidAction(index): return "Invalid hotkey action at index \(index)"
        case let .invalidShelf(name): return "Invalid shelf configuration: \(name)"
        }
    }
}

public enum InputValidationError: LocalizedError, Equatable {
    case invalidDragDuration(Double)

    public var errorDescription: String? {
        switch self {
        case let .invalidDragDuration(duration): return "Invalid drag duration: \(duration)"
        }
    }
}

public enum InputValidation {
    public static let maximumDragDuration = 60.0

    public static func dragDelayMicroseconds(duration: Double, steps: Int) throws -> useconds_t {
        guard duration.isFinite, duration >= 0, duration <= maximumDragDuration, steps > 0 else {
            throw InputValidationError.invalidDragDuration(duration)
        }
        return useconds_t(duration * 1_000_000 / Double(steps))
    }
}
