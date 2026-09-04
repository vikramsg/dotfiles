import Foundation

public enum PermissionKind: Equatable {
    case accessibility
    case screenRecording

    public init(apiValue: String) throws {
        switch apiValue {
        case "accessibility": self = .accessibility
        case "screen_recording": self = .screenRecording
        default: throw PermissionCommandError.unsupportedPermission(apiValue)
        }
    }

    public var apiValue: String {
        switch self {
        case .accessibility: return "accessibility"
        case .screenRecording: return "screen_recording"
        }
    }
}

public enum PermissionCommandError: LocalizedError, Equatable {
    case missingPermission
    case unsupportedPermission(String)

    public var errorDescription: String? {
        switch self {
        case .missingPermission:
            return "permission is required"
        case let .unsupportedPermission(permission):
            return "Unsupported permission: \(permission)"
        }
    }
}

public struct PermissionRequestResult: Equatable {
    public let permission: PermissionKind
    public let granted: Bool

    public var json: [String: Any] {
        ["permission": permission.apiValue, "granted": granted]
    }
}

public enum PermissionRequestHandler {
    public static func handle(
        body: [String: Any],
        request: (PermissionKind) -> Bool
    ) throws -> PermissionRequestResult {
        guard let value = body["permission"] as? String else {
            throw PermissionCommandError.missingPermission
        }
        let permission = try PermissionKind(apiValue: value)
        return PermissionRequestResult(permission: permission, granted: request(permission))
    }
}
