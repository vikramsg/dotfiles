import XCTest
@testable import MacflowCore

final class PermissionCommandTests: XCTestCase {
    func testStatusCommandBuildsReadOnlyRequest() throws {
        let command = try XCTUnwrap(PermissionCommand.parse(arguments: ["permissions"]))
        XCTAssertEqual(command, .status)
        XCTAssertEqual(
            command.httpRequest,
            PermissionHTTPRequest(method: "GET", path: "/v1/permissions", permission: nil)
        )
        XCTAssertNil(command.httpRequest.body)
    }

    func testAccessibilityCommandBuildsGenericRequest() throws {
        let command = try XCTUnwrap(
            PermissionCommand.parse(arguments: ["request-permission", "accessibility"])
        )
        XCTAssertEqual(command, .request(.accessibility))
        XCTAssertEqual(command.httpRequest.method, "POST")
        XCTAssertEqual(command.httpRequest.path, "/v1/permissions/request")
        XCTAssertEqual(command.httpRequest.body?["permission"] as? String, "accessibility")
    }

    func testScreenRecordingCommandConvertsCLINameToAPIName() throws {
        let command = try XCTUnwrap(
            PermissionCommand.parse(arguments: ["request-permission", "screen-recording"])
        )
        XCTAssertEqual(command, .request(.screenRecording))
        XCTAssertEqual(command.httpRequest.body?["permission"] as? String, "screen_recording")
    }

    func testRequestCommandRejectsMissingUnknownAndExtraArguments() {
        XCTAssertThrowsError(try PermissionCommand.parse(arguments: ["request-permission"])) { error in
            XCTAssertEqual(error as? PermissionCommandError, .missingPermission)
        }
        XCTAssertThrowsError(try PermissionCommand.parse(arguments: ["request-permission", "camera"])) { error in
            XCTAssertEqual(error as? PermissionCommandError, .unsupportedPermission("camera"))
        }
        XCTAssertThrowsError(
            try PermissionCommand.parse(arguments: ["request-permission", "accessibility", "extra"])
        ) { error in
            XCTAssertEqual(error as? PermissionCommandError, .invalidArguments)
        }
    }

    func testRemovedCommandsAreNotRecognizedAsPermissionCommands() throws {
        XCTAssertNil(try PermissionCommand.parse(arguments: ["request-accessibility"]))
        XCTAssertNil(try PermissionCommand.parse(arguments: ["request-screen-recording"]))
    }

    func testHandlerDispatchesAccessibilityExactlyOnce() throws {
        var requested: [PermissionKind] = []
        let result = try PermissionRequestHandler.handle(body: ["permission": "accessibility"]) {
            requested.append($0)
            return true
        }
        XCTAssertEqual(requested, [.accessibility])
        XCTAssertEqual(result, PermissionRequestResult(permission: .accessibility, granted: true))
        XCTAssertEqual(result.json["permission"] as? String, "accessibility")
        XCTAssertEqual(result.json["granted"] as? Bool, true)
    }

    func testHandlerDispatchesScreenRecordingExactlyOnce() throws {
        var requested: [PermissionKind] = []
        let result = try PermissionRequestHandler.handle(body: ["permission": "screen_recording"]) {
            requested.append($0)
            return false
        }
        XCTAssertEqual(requested, [.screenRecording])
        XCTAssertEqual(result, PermissionRequestResult(permission: .screenRecording, granted: false))
    }

    func testHandlerRejectsMissingAndUnknownPermissionsWithoutDispatching() {
        var requestCount = 0
        let requester: (PermissionKind) -> Bool = { _ in
            requestCount += 1
            return true
        }

        XCTAssertThrowsError(try PermissionRequestHandler.handle(body: [:], request: requester)) { error in
            XCTAssertEqual(error as? PermissionCommandError, .missingPermission)
        }
        XCTAssertThrowsError(
            try PermissionRequestHandler.handle(body: ["permission": "camera"], request: requester)
        ) { error in
            XCTAssertEqual(error as? PermissionCommandError, .unsupportedPermission("camera"))
        }
        XCTAssertEqual(requestCount, 0)
    }
}
