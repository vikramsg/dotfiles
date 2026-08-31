import Testing
@testable import MacflowCore

@Suite struct PermissionCommandTests {
    @Test func testStatusCommandBuildsReadOnlyRequest() throws {
        let command = try #require(try PermissionCommand.parse(arguments: ["permissions"]))
        #expect(command == .status)
        #expect(
            command.httpRequest
                == PermissionHTTPRequest(method: "GET", path: "/v1/permissions", permission: nil)
        )
        #expect(command.httpRequest.body == nil)
    }

    @Test func testAccessibilityCommandBuildsGenericRequest() throws {
        let command = try #require(
            try PermissionCommand.parse(arguments: ["request-permission", "accessibility"])
        )
        #expect(command == .request(.accessibility))
        #expect(command.httpRequest.method == "POST")
        #expect(command.httpRequest.path == "/v1/permissions/request")
        #expect(command.httpRequest.body?["permission"] as? String == "accessibility")
    }

    @Test func testScreenRecordingCommandConvertsCLINameToAPIName() throws {
        let command = try #require(
            try PermissionCommand.parse(arguments: ["request-permission", "screen-recording"])
        )
        #expect(command == .request(.screenRecording))
        #expect(command.httpRequest.body?["permission"] as? String == "screen_recording")
    }

    @Test func testRequestCommandRejectsMissingUnknownAndExtraArguments() {
        do {
            _ = try PermissionCommand.parse(arguments: ["request-permission"])
            Issue.record("Expected missing permission to fail")
        } catch {
            #expect(error as? PermissionCommandError == .missingPermission)
        }
        do {
            _ = try PermissionCommand.parse(arguments: ["request-permission", "camera"])
            Issue.record("Expected unsupported permission to fail")
        } catch {
            #expect(error as? PermissionCommandError == .unsupportedPermission("camera"))
        }
        do {
            _ = try PermissionCommand.parse(arguments: ["request-permission", "accessibility", "extra"])
            Issue.record("Expected extra arguments to fail")
        } catch {
            #expect(error as? PermissionCommandError == .invalidArguments)
        }
    }

    @Test func testRemovedCommandsAreNotRecognizedAsPermissionCommands() throws {
        #expect(try PermissionCommand.parse(arguments: ["request-accessibility"]) == nil)
        #expect(try PermissionCommand.parse(arguments: ["request-screen-recording"]) == nil)
    }

    @Test func testHandlerDispatchesAccessibilityExactlyOnce() throws {
        var requested: [PermissionKind] = []
        let result = try PermissionRequestHandler.handle(body: ["permission": "accessibility"]) {
            requested.append($0)
            return true
        }
        #expect(requested == [.accessibility])
        #expect(result == PermissionRequestResult(permission: .accessibility, granted: true))
        #expect(result.json["permission"] as? String == "accessibility")
        #expect(result.json["granted"] as? Bool == true)
    }

    @Test func testHandlerDispatchesScreenRecordingExactlyOnce() throws {
        var requested: [PermissionKind] = []
        let result = try PermissionRequestHandler.handle(body: ["permission": "screen_recording"]) {
            requested.append($0)
            return false
        }
        #expect(requested == [.screenRecording])
        #expect(result == PermissionRequestResult(permission: .screenRecording, granted: false))
    }

    @Test func testHandlerRejectsMissingAndUnknownPermissionsWithoutDispatching() {
        var requestCount = 0
        let requester: (PermissionKind) -> Bool = { _ in
            requestCount += 1
            return true
        }

        do {
            _ = try PermissionRequestHandler.handle(body: [:], request: requester)
            Issue.record("Expected missing permission to fail")
        } catch {
            #expect(error as? PermissionCommandError == .missingPermission)
        }
        do {
            _ = try PermissionRequestHandler.handle(body: ["permission": "camera"], request: requester)
            Issue.record("Expected unsupported permission to fail")
        } catch {
            #expect(error as? PermissionCommandError == .unsupportedPermission("camera"))
        }
        #expect(requestCount == 0)
    }
}
