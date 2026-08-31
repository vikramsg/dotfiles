import Testing
@testable import MacflowUI

@Suite
struct FileShelfStateTests {
    @Test
    func selectionStartsAtFirstSourceAndChangesOnlyToKnownSource() throws {
        var state = try #require(FileShelfState(sourceIDs: ["local", "remote"]))
        #expect(state.selectedSourceID == "local")

        let selectedRemote = state.select("remote")
        #expect(selectedRemote)
        #expect(state.selectedSourceID == "remote")

        let selectedMissing = state.select("missing")
        #expect(!selectedMissing)
        #expect(state.selectedSourceID == "remote")
    }
}
