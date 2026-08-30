import Foundation

public enum LayoutOperation: Codable, Equatable {
    case setFrame(application: String, frame: Frame)
    case raise(application: String)
    case wait(seconds: Double)
    case focus(application: String)

    private enum CodingKeys: String, CodingKey {
        case type, application, frame, seconds
    }

    private enum OperationType: String, Codable {
        case setFrame = "set_frame"
        case raise
        case wait
        case focus
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let type = try container.decode(OperationType.self, forKey: .type)
        switch type {
        case .setFrame:
            self = .setFrame(
                application: try container.decode(String.self, forKey: .application),
                frame: try container.decode(Frame.self, forKey: .frame)
            )
        case .raise:
            self = .raise(application: try container.decode(String.self, forKey: .application))
        case .wait:
            self = .wait(seconds: try container.decode(Double.self, forKey: .seconds))
        case .focus:
            self = .focus(application: try container.decode(String.self, forKey: .application))
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        switch self {
        case let .setFrame(application, frame):
            try container.encode(OperationType.setFrame, forKey: .type)
            try container.encode(application, forKey: .application)
            try container.encode(frame, forKey: .frame)
        case let .raise(application):
            try container.encode(OperationType.raise, forKey: .type)
            try container.encode(application, forKey: .application)
        case let .wait(seconds):
            try container.encode(OperationType.wait, forKey: .type)
            try container.encode(seconds, forKey: .seconds)
        case let .focus(application):
            try container.encode(OperationType.focus, forKey: .type)
            try container.encode(application, forKey: .application)
        }
    }
}

public struct LayoutPlan: Codable, Equatable {
    public let operations: [LayoutOperation]

    public init(operations: [LayoutOperation]) {
        self.operations = operations
    }
}

public enum LayoutPlanningError: LocalizedError, Equatable {
    case missingApplication
    case focusNotInLayout(String)
    case invalidColumnGeometry

    public var errorDescription: String? {
        switch self {
        case .missingApplication: return "Layout requires at least one application"
        case let .focusNotInLayout(application): return "Layout focus is not a participant: \(application)"
        case .invalidColumnGeometry: return "Layout column geometry does not match its applications"
        }
    }
}

public enum LayoutPlanner {
    public static let activationSettleSeconds = 0.2

    public static func plan(
        layout: WorkflowConfiguration.Layout,
        screen: Frame
    ) throws -> LayoutPlan {
        guard !layout.applications.isEmpty else {
            throw LayoutPlanningError.missingApplication
        }
        guard layout.applications.contains(layout.focus) else {
            throw LayoutPlanningError.focusNotInLayout(layout.focus)
        }

        let frames: [Frame]
        switch layout.type {
        case .maximize:
            frames = [LayoutGeometry.maximize(in: screen)]
        case .columns:
            frames = LayoutGeometry.columns(
                in: screen,
                ratios: layout.ratios ?? Array(repeating: 1, count: layout.applications.count),
                gap: layout.gap ?? 0
            )
        }
        guard frames.count == layout.applications.count else {
            throw LayoutPlanningError.invalidColumnGeometry
        }

        var operations = zip(layout.applications, frames).map {
            LayoutOperation.setFrame(application: $0, frame: $1)
        }
        for application in layout.applications where application != layout.focus {
            operations.append(.raise(application: application))
            operations.append(.wait(seconds: activationSettleSeconds))
        }
        operations.append(.focus(application: layout.focus))
        return LayoutPlan(operations: operations)
    }
}
