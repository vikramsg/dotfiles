import Foundation
import Testing

@testable import MacflowCLI

@Suite struct CLITests {
    @Test func generatedHelpDescribesRootAndNestedCommands() {
        let root = MacflowCommand.helpMessage()
        let doctor = MacflowCommand.helpMessage(for: MacflowCommand.Doctor.self)
        let permissions = MacflowCommand.helpMessage(for: MacflowCommand.Permissions.self)
        let request = MacflowCommand.helpMessage(for: MacflowCommand.Permissions.Request.self)
        let screenshot = MacflowCommand.helpMessage(for: MacflowCommand.Screenshot.self)

        #expect(root.contains("USAGE: macflow <subcommand>"))
        #expect(root.contains("doctor"))
        #expect(root.contains("permissions"))
        #expect(doctor.contains("USAGE: macflow doctor"))
        #expect(doctor.contains("global shortcut health"))
        #expect(permissions.contains("USAGE: macflow permissions [<subcommand>]"))
        #expect(permissions.contains("request"))
        #expect(request.contains("USAGE: macflow permissions request <permission>"))
        #expect(request.contains("Permission to request:"))
        #expect(request.contains("screen-recording"))
        #expect(request.contains("-h, --help"))
        #expect(screenshot.contains("--display"))
        #expect(screenshot.contains("--path"))
        #expect(screenshot.contains("--preview"))
    }

    @Test func missingPermissionProducesContextualHelp() {
        do {
            _ = try MacflowCommand.parseAsRoot(["permissions", "request"])
            Issue.record("Expected a missing permission error")
        } catch {
            let message = MacflowCommand.fullMessage(for: error)
            #expect(message.contains("Missing expected argument '<permission>'"))
            #expect(message.contains("Usage: macflow permissions request <permission>"))
            #expect(message.contains("macflow permissions request --help"))
        }
    }

    @Test func typedArgumentsRejectUnsupportedValues() {
        let permissionError = parsingError(["permissions", "request", "camera"])
        #expect(permissionError.contains("The value 'camera' is invalid for '<permission>'"))
        #expect(permissionError.contains("accessibility"))
        #expect(permissionError.contains("screen-recording"))

        let buttonError = parsingError(["click", "middle", "20", "30"])
        #expect(buttonError.contains("The value 'middle' is invalid for '<button>'"))

        let coordinateError = parsingError(["frame", "window", "left", "2", "800", "600"])
        #expect(coordinateError.contains("The value 'left' is invalid for '<x>'"))
    }

    @Test func readCommandsBuildExpectedRequests() throws {
        try expectRequest(["health"], method: "GET", path: "/v1/health", authenticated: false)
        try expectRequest(["permissions"], method: "GET", path: "/v1/permissions")
        try expectRequest(["applications"], method: "GET", path: "/v1/applications")
        try expectRequest(
            ["windows", "com.example.Editor"],
            method: "GET",
            path: "/v1/windows?bundle_id=com.example.Editor"
        )
        try expectRequest(["screens"], method: "GET", path: "/v1/screens")
        try expectRequest(["overlays"], method: "GET", path: "/v1/overlays")
        try expectRequest(["shelves"], method: "GET", path: "/v1/file-shelves")
    }

    @Test func actionCommandsBuildExpectedRequests() throws {
        try expectRequest(
            ["permissions", "request", "accessibility"],
            method: "POST",
            path: "/v1/permissions/request",
            body: ["permission": "accessibility"]
        )
        try expectRequest(
            ["permissions", "request", "screen-recording"],
            method: "POST",
            path: "/v1/permissions/request",
            body: ["permission": "screen_recording"]
        )
        try expectRequest(
            ["launch", "com.example.Editor"],
            method: "POST",
            path: "/v1/applications/launch",
            body: ["bundle_id": "com.example.Editor"]
        )
        try expectRequest(["focus", "window 1"], method: "POST", path: "/v1/windows/window%201/focus")
        try expectRequest(
            ["unminimize", "window 1"],
            method: "POST",
            path: "/v1/windows/window%201/unminimize"
        )
        try expectRequest(["hide-overlays"], method: "DELETE", path: "/v1/overlays")
        try expectRequest(
            ["shelf", "/tmp/screenshots"],
            method: "POST",
            path: "/v1/file-shelves",
            body: ["directory": "/tmp/screenshots"]
        )
        try expectRequest(
            ["close-shelf", "shelf 1"],
            method: "DELETE",
            path: "/v1/file-shelves/shelf%201"
        )
    }

    @Test func inputCommandsPreserveTypedArgumentsAndDefaults() throws {
        try expectRequest(
            ["frame", "window", "1", "2", "800", "600"],
            method: "PUT",
            path: "/v1/windows/window",
            body: ["frame": ["x": 1.0, "y": 2.0, "width": 800.0, "height": 600.0]]
        )
        try expectRequest(
            ["overlay", "/tmp/image.png", "4.5"],
            method: "POST",
            path: "/v1/overlays/image",
            body: ["path": "/tmp/image.png", "timeout_seconds": 4.5]
        )
        try expectRequest(
            ["keystroke", "h", "cmd", "shift"],
            method: "POST",
            path: "/v1/input/keystroke",
            body: ["key": "h", "modifiers": ["cmd", "shift"]]
        )
        try expectRequest(
            ["click", "right", "20", "30"],
            method: "POST",
            path: "/v1/input/click",
            body: ["button": "right", "x": 20.0, "y": 30.0]
        )
        try expectRequest(
            ["drag", "1", "2", "3", "4"],
            method: "POST",
            path: "/v1/input/drag",
            body: [
                "from": ["x": 1.0, "y": 2.0],
                "to": ["x": 3.0, "y": 4.0],
                "duration": 0.5,
            ]
        )
        try expectRequest(
            ["screenshot", "--display", "42", "--path", "/tmp/capture.png", "--preview"],
            method: "POST",
            path: "/v1/screenshots",
            body: ["display_id": UInt32(42), "path": "/tmp/capture.png", "show_preview": true]
        )
    }

    private func expectRequest(
        _ arguments: [String],
        method: String,
        path: String,
        body: [String: Any]? = nil,
        authenticated: Bool = true
    ) throws {
        let command = try MacflowCommand.parseAsRoot(arguments)
        let requestCommand = try #require(command as? any HTTPCommand)
        let request = try requestCommand.requestPlan()

        #expect(request.method == method)
        #expect(request.path == path)
        #expect(request.authenticated == authenticated)
        #expect(NSDictionary(dictionary: request.body ?? [:]).isEqual(to: body ?? [:]))
    }


    private func parsingError(_ arguments: [String]) -> String {
        do {
            _ = try MacflowCommand.parseAsRoot(arguments)
            Issue.record("Expected arguments to be rejected: \(arguments)")
            return ""
        } catch {
            return MacflowCommand.fullMessage(for: error)
        }
    }
}
