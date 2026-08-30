import Foundation

public enum PermissionKind: Equatable {
    case accessibility
    case screenRecording

    public init(cliArgument: String) throws {
        switch cliArgument {
        case "accessibility": self = .accessibility
        case "screen-recording": self = .screenRecording
        default: throw PermissionCommandError.unsupportedPermission(cliArgument)
        }
    }

    public init(apiValue: String) throws {
        switch apiValue {
        case "accessibility": self = .accessibility
        case "screen_recording": self = .screenRecording
        default: throw PermissionCommandError.unsupportedPermission(apiValue)
        }
    }

    public var cliArgument: String {
        switch self {
        case .accessibility: return "accessibility"
        case .screenRecording: return "screen-recording"
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
    case invalidArguments
    case missingPermission
    case unsupportedPermission(String)

    public var errorDescription: String? {
        switch self {
        case .invalidArguments:
            return "Invalid permission command arguments"
        case .missingPermission:
            return "request-permission requires accessibility or screen-recording"
        case let .unsupportedPermission(permission):
            return "Unsupported permission: \(permission)"
        }
    }
}

public struct PermissionHTTPRequest: Equatable {
    public let method: String
    public let path: String
    public let permission: PermissionKind?

    public var body: [String: Any]? {
        permission.map { ["permission": $0.apiValue] }
    }
}

public enum PermissionCommand: Equatable {
    case status
    case request(PermissionKind)

    public static func parse(arguments: [String]) throws -> PermissionCommand? {
        switch arguments.first {
        case "permissions":
            guard arguments.count == 1 else { throw PermissionCommandError.invalidArguments }
            return .status
        case "request-permission":
            guard arguments.count > 1 else { throw PermissionCommandError.missingPermission }
            guard arguments.count == 2 else { throw PermissionCommandError.invalidArguments }
            return .request(try PermissionKind(cliArgument: arguments[1]))
        default:
            return nil
        }
    }

    public var httpRequest: PermissionHTTPRequest {
        switch self {
        case .status:
            return PermissionHTTPRequest(method: "GET", path: "/v1/permissions", permission: nil)
        case let .request(permission):
            return PermissionHTTPRequest(
                method: "POST",
                path: "/v1/permissions/request",
                permission: permission
            )
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
