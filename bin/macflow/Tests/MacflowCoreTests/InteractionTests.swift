import XCTest
@testable import MacflowCore

final class InteractionTests: XCTestCase {
    func testKnownKeysResolveAndUnknownKeysDoNot() {
        XCTAssertEqual(KeyCodeResolver.resolve("g"), 5)
        XCTAssertEqual(KeyCodeResolver.resolve("escape"), 53)
        XCTAssertNil(KeyCodeResolver.resolve("not-a-key"))
    }

    func testDragDurationBoundaries() throws {
        XCTAssertEqual(try InputValidation.dragDelayMicroseconds(duration: 60, steps: 20), 3_000_000)
        XCTAssertThrowsError(try InputValidation.dragDelayMicroseconds(duration: 60.001, steps: 20))
        XCTAssertThrowsError(try InputValidation.dragDelayMicroseconds(duration: -.infinity, steps: 20))
    }

    func testOverlappingSuspensionsRemainSuspendedUntilAllResume() {
        var gate = SuspensionGate()
        gate.suspend()
        gate.suspend()
        gate.resume()
        XCTAssertTrue(gate.isSuspended)
        gate.resume()
        XCTAssertFalse(gate.isSuspended)
    }
}
