import Foundation

public struct FileShelfState: Equatable {
    public let sourceIDs: [String]
    public private(set) var selectedSourceID: String

    public init?(sourceIDs: [String]) {
        guard let first = sourceIDs.first, Set(sourceIDs).count == sourceIDs.count else { return nil }
        self.sourceIDs = sourceIDs
        selectedSourceID = first
    }

    @discardableResult
    public mutating func select(_ sourceID: String) -> Bool {
        guard sourceIDs.contains(sourceID) else { return false }
        selectedSourceID = sourceID
        return true
    }
}
