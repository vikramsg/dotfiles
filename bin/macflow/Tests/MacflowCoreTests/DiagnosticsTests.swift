import Foundation
import Testing

@testable import MacflowCore

@Suite struct DiagnosticsTests {
    @Test func statusPayloadsUseTheHTTPContract() throws {
        let permissions = PermissionStatus(accessibility: true, screenRecording: false)
        let hotKeys = HotKeyStatus(eventTapEnabled: true, secureInputEnabled: false)

        #expect(permissions.json == ["accessibility": true, "screen_recording": false])
        #expect(hotKeys.json == ["event_tap_enabled": true, "secure_input_enabled": false])

        let permissionData = try JSONSerialization.data(withJSONObject: permissions.json)
        let hotKeyData = try JSONSerialization.data(withJSONObject: hotKeys.json)
        #expect(try JSONDecoder().decode(PermissionStatus.self, from: permissionData) == permissions)
        #expect(try JSONDecoder().decode(HotKeyStatus.self, from: hotKeyData) == hotKeys)
    }

    @Test func healthyDoctorReportShowsEveryPassingCheck() {
        let report = DoctorReport(
            permissions: PermissionStatus(accessibility: true, screenRecording: true),
            hotKeys: HotKeyStatus(eventTapEnabled: true, secureInputEnabled: false)
        )

        #expect(report.passed)
        #expect(
            DoctorRenderer.render(report, color: false)
                == """
                ✓ service reachable
                ✓ accessibility granted
                ✓ screen recording granted
                ✓ global shortcut listener enabled
                ✓ secure input disabled
                """
        )
    }

    @Test func doctorRequestsPermissionThenHotKeyStatus() throws {
        var requests: [DoctorHTTPRequest] = []
        let report = DoctorCommand.run { request in
            requests.append(request)
            switch request.path {
            case "/v1/permissions":
                return try JSONEncoder().encode(PermissionStatus(accessibility: true, screenRecording: true))
            case "/v1/hotkeys":
                return try JSONEncoder().encode(HotKeyStatus(eventTapEnabled: true, secureInputEnabled: false))
            default:
                throw TestFailure.unexpectedRequest
            }
        }

        #expect(requests == [
            DoctorHTTPRequest(method: "GET", path: "/v1/permissions"),
            DoctorHTTPRequest(method: "GET", path: "/v1/hotkeys"),
        ])
        #expect(report.passed)
    }

    @Test func doctorReportsUnavailableServiceAndStopsRequesting() {
        var requests: [DoctorHTTPRequest] = []
        let report = DoctorCommand.run { request in
            requests.append(request)
            throw TestFailure.serviceUnavailable
        }

        #expect(requests == [DoctorHTTPRequest(method: "GET", path: "/v1/permissions")])
        #expect(!report.passed)
        #expect(DoctorRenderer.render(report, color: false).contains("✗ service unreachable"))
    }

    @Test func doctorReportsInvalidPermissionStatusAsAServiceResponseFailure() {
        var requestCount = 0
        let report = DoctorCommand.run { _ in
            requestCount += 1
            return Data("not json".utf8)
        }

        let output = DoctorRenderer.render(report, color: false)
        #expect(requestCount == 1)
        #expect(!report.passed)
        #expect(output.contains("✓ service reachable"))
        #expect(output.contains("✗ permission status unavailable"))
    }

    @Test func doctorKeepsKnownPermissionResultsWhenHotKeyStatusIsInvalid() throws {
        let report = DoctorCommand.run { request in
            if request.path == "/v1/permissions" {
                return try JSONEncoder().encode(
                    PermissionStatus(accessibility: true, screenRecording: false)
                )
            }
            return Data("not json".utf8)
        }

        let output = DoctorRenderer.render(report, color: false)
        #expect(!report.passed)
        #expect(output.contains("✓ accessibility granted"))
        #expect(output.contains("✗ screen recording not granted"))
        #expect(output.contains("✗ hotkey status unavailable"))
    }

    @Test func doctorReportsActionableFailures() {
        let report = DoctorReport(
            permissions: PermissionStatus(accessibility: false, screenRecording: false),
            hotKeys: HotKeyStatus(eventTapEnabled: false, secureInputEnabled: true)
        )

        #expect(!report.passed)
        let expected = [
            "✓ service reachable",
            "✗ accessibility not granted",
            "  help: Run `macflow permissions request accessibility`.",
            "✗ screen recording not granted",
            "  help: Run `macflow permissions request screen-recording`.",
            "✗ global shortcut listener disabled",
            "  help: Restart Macflow and run `macflow doctor` again.",
            "✗ secure input enabled",
            "  help: Global shortcuts are blocked by macOS.",
            "        Close password prompts and restart likely password-manager/browser apps.",
        ].joined(separator: "\n")
        #expect(DoctorRenderer.render(report, color: false) == expected)
    }

    @Test func doctorUsesTerminalColorsOnlyWhenRequested() {
        let report = DoctorReport(checks: [
            DoctorCheck(passed: true, message: "service reachable"),
            DoctorCheck(
                passed: false, message: "secure input enabled", help: ["Close password prompts."]),
        ])

        let colored = DoctorRenderer.render(report, color: true)
        #expect(colored.contains("\u{001B}[32m✓ service reachable\u{001B}[0m"))
        #expect(colored.contains("\u{001B}[31m✗ secure input enabled\u{001B}[0m"))
        #expect(colored.contains("  \u{001B}[36mhelp:\u{001B}[0m Close password prompts."))
        #expect(!DoctorRenderer.render(report, color: false).contains("\u{001B}"))
    }

    @Test func doctorDisablesColorOutsideInteractiveTerminals() {
        #expect(DoctorRenderer.shouldUseColor(isTerminal: true, environment: ["TERM": "xterm-256color"]))
        #expect(!DoctorRenderer.shouldUseColor(isTerminal: false, environment: ["TERM": "xterm-256color"]))
        #expect(!DoctorRenderer.shouldUseColor(isTerminal: true, environment: ["NO_COLOR": ""]))
        #expect(!DoctorRenderer.shouldUseColor(isTerminal: true, environment: ["TERM": "dumb"]))
    }
}

private enum TestFailure: Error {
    case serviceUnavailable
    case unexpectedRequest
}
