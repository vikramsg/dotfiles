import Foundation
import XCTest
@testable import MacflowCore

final class FileCatalogTests: XCTestCase {
    func testCatalogFiltersUnsupportedEntriesAndSortsNewestFirst() {
        let candidates = [
            ScreenshotCandidate(url: URL(fileURLWithPath: "/shots/older.png"), modificationDate: Date(timeIntervalSince1970: 10), regularFile: true),
            ScreenshotCandidate(url: URL(fileURLWithPath: "/shots/newer.JPG"), modificationDate: Date(timeIntervalSince1970: 30), regularFile: true),
            ScreenshotCandidate(url: URL(fileURLWithPath: "/shots/newest.txt"), modificationDate: Date(timeIntervalSince1970: 40), regularFile: true),
            ScreenshotCandidate(url: URL(fileURLWithPath: "/shots/folder.png"), modificationDate: Date(timeIntervalSince1970: 50), regularFile: false),
        ]
        XCTAssertEqual(
            FileCatalog.sortedItems(candidates: candidates, supportedExtensions: ["png", "jpg"])
                .map(\.url.lastPathComponent),
            ["newer.JPG", "older.png"]
        )
    }
}
