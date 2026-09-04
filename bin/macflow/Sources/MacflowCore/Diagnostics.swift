import Foundation

public struct PermissionStatus: Codable, Equatable {
    public let accessibility: Bool
    public let screenRecording: Bool

    public init(accessibility: Bool, screenRecording: Bool) {
        self.accessibility = accessibility
        self.screenRecording = screenRecording
    }

    enum CodingKeys: String, CodingKey {
        case accessibility
        case screenRecording = "screen_recording"
    }

    public var json: [String: Bool] {
        [
            "accessibility": accessibility,
            "screen_recording": screenRecording,
        ]
    }
}

public struct HotKeyStatus: Codable, Equatable {
    public let eventTapEnabled: Bool
    public let secureInputEnabled: Bool

    public init(eventTapEnabled: Bool, secureInputEnabled: Bool) {
        self.eventTapEnabled = eventTapEnabled
        self.secureInputEnabled = secureInputEnabled
    }

    enum CodingKeys: String, CodingKey {
        case eventTapEnabled = "event_tap_enabled"
        case secureInputEnabled = "secure_input_enabled"
    }

    public var json: [String: Bool] {
        [
            "event_tap_enabled": eventTapEnabled,
            "secure_input_enabled": secureInputEnabled,
        ]
    }
}

public struct DoctorCheck: Equatable {
    public let passed: Bool
    public let message: String
    public let help: [String]

    public init(passed: Bool, message: String, help: [String] = []) {
        self.passed = passed
        self.message = message
        self.help = help
    }
}

public struct DoctorReport: Equatable {
    public let checks: [DoctorCheck]

    public init(checks: [DoctorCheck]) {
        self.checks = checks
    }

    public init(permissions: PermissionStatus, hotKeys: HotKeyStatus) {
        checks = [
            DoctorCheck(passed: true, message: "service reachable"),
            DoctorCheck(
                passed: permissions.accessibility,
                message: permissions.accessibility ? "accessibility granted" : "accessibility not granted",
                help: permissions.accessibility ? [] : ["Run `macflow permissions request accessibility`."]
            ),
            DoctorCheck(
                passed: permissions.screenRecording,
                message: permissions.screenRecording
                    ? "screen recording granted" : "screen recording not granted",
                help: permissions.screenRecording
                    ? [] : ["Run `macflow permissions request screen-recording`."]
            ),
            DoctorCheck(
                passed: hotKeys.eventTapEnabled,
                message: hotKeys.eventTapEnabled
                    ? "global shortcut listener enabled"
                    : "global shortcut listener disabled",
                help: hotKeys.eventTapEnabled ? [] : ["Restart Macflow and run `macflow doctor` again."]
            ),
            DoctorCheck(
                passed: !hotKeys.secureInputEnabled,
                message: hotKeys.secureInputEnabled ? "secure input enabled" : "secure input disabled",
                help: hotKeys.secureInputEnabled
                    ? [
                        "Global shortcuts are blocked by macOS.",
                        "Close password prompts and restart likely password-manager/browser apps.",
                    ]
                    : []
            ),
        ]
    }

    public var passed: Bool {
        checks.allSatisfy(\.passed)
    }
}

public struct DoctorHTTPRequest: Equatable {
    public let method: String
    public let path: String

    public init(method: String, path: String) {
        self.method = method
        self.path = path
    }
}

public enum DoctorCommand {
    public static func run(request: (DoctorHTTPRequest) throws -> Data) -> DoctorReport {
        let permissionData: Data
        do {
            permissionData = try request(DoctorHTTPRequest(method: "GET", path: "/v1/permissions"))
        } catch {
            return DoctorReport(checks: [
                DoctorCheck(
                    passed: false,
                    message: "service unreachable",
                    help: ["Could not read Macflow permissions: \(error.localizedDescription)"]
                ),
            ])
        }

        let permissions: PermissionStatus
        do {
            permissions = try JSONDecoder().decode(PermissionStatus.self, from: permissionData)
        } catch {
            return DoctorReport(checks: [
                DoctorCheck(passed: true, message: "service reachable"),
                DoctorCheck(
                    passed: false,
                    message: "permission status unavailable",
                    help: ["Macflow returned invalid permission status: \(error.localizedDescription)"]
                ),
            ])
        }

        let hotKeyData: Data
        do {
            hotKeyData = try request(DoctorHTTPRequest(method: "GET", path: "/v1/hotkeys"))
        } catch {
            return hotKeyFailure(permissions: permissions, message: error.localizedDescription)
        }

        let hotKeys: HotKeyStatus
        do {
            hotKeys = try JSONDecoder().decode(HotKeyStatus.self, from: hotKeyData)
        } catch {
            return hotKeyFailure(permissions: permissions, message: error.localizedDescription)
        }

        return DoctorReport(permissions: permissions, hotKeys: hotKeys)
    }

    private static func hotKeyFailure(permissions: PermissionStatus, message: String) -> DoctorReport {
        DoctorReport(checks: [
            DoctorCheck(passed: true, message: "service reachable"),
        ] + permissionChecks(permissions) + [
            DoctorCheck(
                passed: false,
                message: "hotkey status unavailable",
                help: ["Could not read Macflow hotkey status: \(message)"]
            ),
        ])
    }

    private static func permissionChecks(_ status: PermissionStatus) -> [DoctorCheck] {
        [
            DoctorCheck(
                passed: status.accessibility,
                message: status.accessibility ? "accessibility granted" : "accessibility not granted",
                help: status.accessibility ? [] : ["Run `macflow permissions request accessibility`."]
            ),
            DoctorCheck(
                passed: status.screenRecording,
                message: status.screenRecording ? "screen recording granted" : "screen recording not granted",
                help: status.screenRecording ? [] : ["Run `macflow permissions request screen-recording`."]
            ),
        ]
    }
}

public enum DoctorRenderer {
    public static func shouldUseColor(isTerminal: Bool, environment: [String: String]) -> Bool {
        isTerminal && environment["NO_COLOR"] == nil && environment["TERM"] != "dumb"
    }

    public static func render(_ report: DoctorReport, color: Bool) -> String {
        var lines: [String] = []
        for check in report.checks {
            let symbol = check.passed ? "✓" : "✗"
            let line = "\(symbol) \(check.message)"
            lines.append(color ? styled(line, code: check.passed ? 32 : 31) : line)
            for (index, guidance) in check.help.enumerated() {
                if index == 0 {
                    let marker = color ? styled("help:", code: 36) : "help:"
                    lines.append("  \(marker) \(guidance)")
                } else {
                    lines.append("        \(guidance)")
                }
            }
        }
        return lines.joined(separator: "\n")
    }

    private static func styled(_ value: String, code: Int) -> String {
        "\u{001B}[\(code)m\(value)\u{001B}[0m"
    }
}
