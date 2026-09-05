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
        #expect(root.contains("ui"))
        #expect(root.contains("system"))
        #expect(doctor.contains("USAGE: macflow system doctor"))
        #expect(doctor.contains("global shortcut health"))
        #expect(permissions.contains("USAGE: macflow system permissions [<subcommand>]"))
        #expect(permissions.contains("request"))
        #expect(request.contains("USAGE: macflow system permissions request <permission>"))
        #expect(request.contains("Permission to request:"))
        #expect(request.contains("screen-recording"))
        #expect(request.contains("-h, --help"))
        #expect(screenshot.contains("--display"))
        #expect(screenshot.contains("--path"))
        #expect(screenshot.contains("--preview"))
    }

    @Test func missingPermissionProducesContextualHelp() {
        do {
            _ = try MacflowCommand.parseAsRoot(["system", "permissions", "request"])
            Issue.record("Expected a missing permission error")
        } catch {
            let message = MacflowCommand.fullMessage(for: error)
            #expect(message.contains("Missing expected argument '<permission>'"))
            #expect(message.contains("Usage: macflow system permissions request <permission>"))
            #expect(message.contains("macflow system permissions request --help"))
        }
    }

    @Test func typedArgumentsRejectUnsupportedValues() {
        let permissionError = parsingError(["system", "permissions", "request", "camera"])
        #expect(permissionError.contains("The value 'camera' is invalid for '<permission>'"))
        #expect(permissionError.contains("accessibility"))
        #expect(permissionError.contains("screen-recording"))

        let buttonError = parsingError(["input", "click", "middle", "20", "30"])
        #expect(buttonError.contains("The value 'middle' is invalid for '<button>'"))

        let coordinateError = parsingError(["window", "frame", "window", "left", "2", "800", "600"])
        #expect(coordinateError.contains("The value 'left' is invalid for '<x>'"))
    }

    @Test func readCommandsBuildExpectedRequests() throws {
        try expectRequest(["system", "health"], method: "GET", path: "/v1/health", authenticated: false)
        try expectRequest(["system", "permissions"], method: "GET", path: "/v1/permissions")
        try expectRequest(["app", "list"], method: "GET", path: "/v1/applications")
        try expectRequest(
            ["window", "list", "com.example.Editor"],
            method: "GET",
            path: "/v1/windows?bundle_id=com.example.Editor"
        )
        try expectRequest(["screen", "list"], method: "GET", path: "/v1/screens")
        try expectRequest(["ui", "overlay", "list"], method: "GET", path: "/v1/overlays")
        try expectRequest(["ui", "shelf", "list"], method: "GET", path: "/v1/file-shelves")
    }

    @Test func actionCommandsBuildExpectedRequests() throws {
        try expectRequest(
            ["system", "permissions", "request", "accessibility"],
            method: "POST",
            path: "/v1/permissions/request",
            body: ["permission": "accessibility"]
        )
        try expectRequest(
            ["system", "permissions", "request", "screen-recording"],
            method: "POST",
            path: "/v1/permissions/request",
            body: ["permission": "screen_recording"]
        )
        try expectRequest(
            ["app", "launch", "com.example.Editor"],
            method: "POST",
            path: "/v1/applications/launch",
            body: ["bundle_id": "com.example.Editor"]
        )
        try expectRequest(["window", "focus", "window 1"], method: "POST", path: "/v1/windows/window%201/focus")
        try expectRequest(
            ["window", "unminimize", "window 1"],
            method: "POST",
            path: "/v1/windows/window%201/unminimize"
        )
        try expectRequest(["ui", "overlay", "hide"], method: "DELETE", path: "/v1/overlays")
        try expectRequest(
            ["ui", "shelf", "show", "/tmp/screenshots"],
            method: "POST",
            path: "/v1/file-shelves",
            body: ["directory": "/tmp/screenshots"]
        )
        try expectRequest(
            ["ui", "shelf", "close", "shelf 1"],
            method: "DELETE",
            path: "/v1/file-shelves/shelf%201"
        )
    }

    @Test func inputCommandsPreserveTypedArgumentsAndDefaults() throws {
        try expectRequest(
            ["window", "frame", "window", "1", "2", "800", "600"],
            method: "PUT",
            path: "/v1/windows/window",
            body: ["frame": ["x": 1.0, "y": 2.0, "width": 800.0, "height": 600.0]]
        )
        try expectRequest(
            ["ui", "overlay", "show", "/tmp/image.png", "4.5"],
            method: "POST",
            path: "/v1/overlays/image",
            body: ["path": "/tmp/image.png", "timeout_seconds": 4.5]
        )
        try expectRequest(
            ["input", "keystroke", "h", "cmd", "shift"],
            method: "POST",
            path: "/v1/input/keystroke",
            body: ["key": "h", "modifiers": ["cmd", "shift"]]
        )
        try expectRequest(
            ["input", "click", "right", "20", "30"],
            method: "POST",
            path: "/v1/input/click",
            body: ["button": "right", "x": 20.0, "y": 30.0]
        )
        try expectRequest(
            ["input", "drag", "1", "2", "3", "4"],
            method: "POST",
            path: "/v1/input/drag",
            body: [
                "from": ["x": 1.0, "y": 2.0],
                "to": ["x": 3.0, "y": 4.0],
                "duration": 0.5,
            ]
        )
        try expectRequest(
            ["screenshot", "capture", "--display", "42", "--path", "/tmp/capture.png", "--preview"],
            method: "POST",
            path: "/v1/screenshots",
            body: ["display_id": UInt32(42), "path": "/tmp/capture.png", "show_preview": true]
        )
    }

    @Test func captureDoesNotRequestUIUnlessAsked() throws {
        try expectRequest(["screenshot", "capture"], method: "POST", path: "/v1/screenshots", body: [:])
        try expectRequest(
            ["screenshot", "capture", "--preview"], method: "POST", path: "/v1/screenshots",
            body: ["show_preview": true]
        )
    }

    @Test(arguments: [
        ["app"], ["window"], ["screen"], ["input"], ["screenshot"],
        ["ui"], ["ui", "overlay"], ["ui", "shelf"], ["system"],
    ])
    func groupsOfferHelpWithoutPerformingAnAction(arguments: [String]) throws {
        var command = try MacflowCommand.parseAsRoot(arguments)
        do {
            try command.run()
            Issue.record("Expected group help")
        } catch {
            #expect(MacflowCommand.exitCode(for: error).rawValue == 0)
            let help = MacflowCommand.fullMessage(for: error)
            #expect(help.contains("macflow " + arguments.joined(separator: " ")))
            #expect(help.contains("SUBCOMMANDS:"))
        }
    }

    @Test(arguments: ["overlay", "shelf", "screenshot"])
    func invalidActionArgumentsPointToTheNestedHelp(group: String) {
        let arguments = group == "screenshot" ? [group, "capture", "--display", "unknown"] : ["ui", group, "show"]
        let message = parsingError(arguments)
        let command = group == "screenshot" ? "screenshot capture" : "ui \(group) show"
        #expect(message.contains("macflow \(command) --help"))
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
