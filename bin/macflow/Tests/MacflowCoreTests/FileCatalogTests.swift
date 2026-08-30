import Foundation
import XCTest
@testable import MacflowCore

final class FileCatalogTests: XCTestCase {
    func testCatalogFiltersUnsupportedEntriesAndSortsNewestFirst() {
        let candidates = [
            ScreenshotCandidate(url: URL(fileURLWithPath: "/shots/older.png"), modificationDate: Date(timeIntervalSince1970: 10), regularFile: true),
            ScreenshotCandidate(url: URL(fileURLWithPath: "/shots/newer.JPG"), modificationDate: Date(timeIntervalSince1970: 30), regularFile: true),
            ScreenshotCandidate(url: URL(fileURLWithPath: "/shots/newest.png"), modificationDate: Date(timeIntervalSince1970: 40), regularFile: true),
            ScreenshotCandidate(url: URL(fileURLWithPath: "/shots/newest.txt"), modificationDate: Date(timeIntervalSince1970: 40), regularFile: true),
            ScreenshotCandidate(url: URL(fileURLWithPath: "/shots/folder.png"), modificationDate: Date(timeIntervalSince1970: 50), regularFile: false),
        ]
        XCTAssertEqual(
            FileCatalog.sortedItems(
                candidates: candidates,
                supportedExtensions: ["png", "jpg"],
                maximumCount: 2
            )
                .map(\.url.lastPathComponent),
            ["newest.png", "newer.JPG"]
        )
    }

    func testCatalogReturnsAllSupportedFilesWhenBelowMaximum() {
        let candidates = [
            ScreenshotCandidate(url: URL(fileURLWithPath: "/shots/older.png"), modificationDate: Date(timeIntervalSince1970: 10), regularFile: true),
            ScreenshotCandidate(url: URL(fileURLWithPath: "/shots/newer.png"), modificationDate: Date(timeIntervalSince1970: 20), regularFile: true),
        ]
        XCTAssertEqual(
            FileCatalog.sortedItems(
                candidates: candidates,
                supportedExtensions: ["png"],
                maximumCount: 5
            ).map(\.url.lastPathComponent),
            ["newer.png", "older.png"]
        )
    }
}
