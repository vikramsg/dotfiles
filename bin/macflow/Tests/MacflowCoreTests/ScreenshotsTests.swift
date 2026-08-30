import Foundation
import XCTest
@testable import MacflowCore

final class ScreenshotsTests: XCTestCase {
    func testNewestReturnsNewestSupportedRegularFile() {
        let candidates = [
            ScreenshotCandidate(url: URL(fileURLWithPath: "/shots/new.txt"), modificationDate: Date(timeIntervalSince1970: 30), regularFile: true),
            ScreenshotCandidate(url: URL(fileURLWithPath: "/shots/old.png"), modificationDate: Date(timeIntervalSince1970: 10), regularFile: true),
            ScreenshotCandidate(url: URL(fileURLWithPath: "/shots/new.JPG"), modificationDate: Date(timeIntervalSince1970: 20), regularFile: true),
            ScreenshotCandidate(url: URL(fileURLWithPath: "/shots/folder.png"), modificationDate: Date(timeIntervalSince1970: 40), regularFile: false),
        ]
        XCTAssertEqual(
            ScreenshotFiles.newest(candidates: candidates, supportedExtensions: ["png", "jpg"])?.url.path,
            "/shots/new.JPG"
        )
    }

    func testPreviewSizePreservesAspectRatio() {
        XCTAssertEqual(
            ScreenshotFiles.previewSize(imageWidth: 1600, imageHeight: 900, maxWidth: 360, maxHeight: 260),
            Frame(x: 0, y: 0, width: 360, height: 202.5)
        )
        XCTAssertEqual(
            ScreenshotFiles.previewSize(imageWidth: 900, imageHeight: 1600, maxWidth: 360, maxHeight: 260),
            Frame(x: 0, y: 0, width: 146.25, height: 260)
        )
    }

    func testSuppressionIsConsumedOnceWhileManualShowStillWorks() {
        var state = ScreenshotPresentationState()
        let date = Date(timeIntervalSince1970: 10)
        let path = "/screenshots/capture.png"

        state.suppressNext(path: path, existingModificationDate: nil)
        XCTAssertTrue(state.consumeSuppression(path: path, modificationDate: date))
        XCTAssertFalse(state.consumeSuppression(path: path, modificationDate: date))
        XCTAssertFalse(state.shouldShow(path: path, modificationDate: date, force: false))
        XCTAssertTrue(state.shouldShow(path: path, modificationDate: date, force: true))
    }

    func testSuppressionWaitsForNewVersionOfExistingPath() {
        var state = ScreenshotPresentationState()
        let oldDate = Date(timeIntervalSince1970: 10)
        let newDate = Date(timeIntervalSince1970: 20)
        let path = "/screenshots/capture.png"

        state.suppressNext(path: path, existingModificationDate: oldDate)
        XCTAssertFalse(state.consumeSuppression(path: path, modificationDate: oldDate))
        XCTAssertTrue(state.consumeSuppression(path: path, modificationDate: newDate))
        XCTAssertFalse(state.shouldShow(path: path, modificationDate: newDate, force: false))
    }

    func testDirectChildDetectionRejectsOutsideAndNestedPaths() {
        let directory = URL(fileURLWithPath: "/screenshots", isDirectory: true)
        XCTAssertTrue(ScreenshotFiles.isDirectChild(path: "/screenshots/capture.png", of: directory))
        XCTAssertFalse(ScreenshotFiles.isDirectChild(path: "/other/capture.png", of: directory))
        XCTAssertFalse(ScreenshotFiles.isDirectChild(path: "/screenshots/nested/capture.png", of: directory))
    }
}
