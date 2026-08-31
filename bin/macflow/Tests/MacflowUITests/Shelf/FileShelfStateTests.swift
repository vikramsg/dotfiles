import XCTest
@testable import MacflowUI

final class FileShelfStateTests: XCTestCase {
    func testSelectionStartsAtFirstSourceAndChangesOnlyToKnownSource() throws {
        var state = try XCTUnwrap(FileShelfState(sourceIDs: ["local", "remote"]))
        XCTAssertEqual(state.selectedSourceID, "local")

        XCTAssertTrue(state.select("remote"))
        XCTAssertEqual(state.selectedSourceID, "remote")

        XCTAssertFalse(state.select("missing"))
        XCTAssertEqual(state.selectedSourceID, "remote")
    }
}
