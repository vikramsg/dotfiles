import Foundation
import Testing
@testable import MacflowCore

@Suite struct ScreenshotsTests {
    @Test func testNewestReturnsNewestSupportedRegularFile() {
        let candidates = [
            ScreenshotCandidate(url: URL(fileURLWithPath: "/shots/new.txt"), modificationDate: Date(timeIntervalSince1970: 30), regularFile: true),
            ScreenshotCandidate(url: URL(fileURLWithPath: "/shots/old.png"), modificationDate: Date(timeIntervalSince1970: 10), regularFile: true),
            ScreenshotCandidate(url: URL(fileURLWithPath: "/shots/new.JPG"), modificationDate: Date(timeIntervalSince1970: 20), regularFile: true),
            ScreenshotCandidate(url: URL(fileURLWithPath: "/shots/folder.png"), modificationDate: Date(timeIntervalSince1970: 40), regularFile: false),
        ]
        #expect(
            ScreenshotFiles.newest(candidates: candidates, supportedExtensions: ["png", "jpg"])?.url.path
                == "/shots/new.JPG"
        )
    }

    @Test func testPreviewSizePreservesAspectRatio() {
        #expect(
            ScreenshotFiles.previewSize(imageWidth: 1600, imageHeight: 900, maxWidth: 360, maxHeight: 260)
                == Frame(x: 0, y: 0, width: 360, height: 202.5)
        )
        #expect(
            ScreenshotFiles.previewSize(imageWidth: 900, imageHeight: 1600, maxWidth: 360, maxHeight: 260)
                == Frame(x: 0, y: 0, width: 146.25, height: 260)
        )
    }

    @Test func testSuppressionIsConsumedOnceWhileManualShowStillWorks() {
        var state = ScreenshotPresentationState()
        let date = Date(timeIntervalSince1970: 10)
        let path = "/screenshots/capture.png"

        state.suppressNext(path: path, existingModificationDate: nil)
        let firstSuppression = state.consumeSuppression(path: path, modificationDate: date)
        let secondSuppression = state.consumeSuppression(path: path, modificationDate: date)
        let automaticShow = state.shouldShow(path: path, modificationDate: date, force: false)
        let manualShow = state.shouldShow(path: path, modificationDate: date, force: true)
        #expect(firstSuppression)
        #expect(!secondSuppression)
        #expect(!automaticShow)
        #expect(manualShow)
    }

    @Test func testSuppressionWaitsForNewVersionOfExistingPath() {
        var state = ScreenshotPresentationState()
        let oldDate = Date(timeIntervalSince1970: 10)
        let newDate = Date(timeIntervalSince1970: 20)
        let path = "/screenshots/capture.png"

        state.suppressNext(path: path, existingModificationDate: oldDate)
        let oldSuppression = state.consumeSuppression(path: path, modificationDate: oldDate)
        let newSuppression = state.consumeSuppression(path: path, modificationDate: newDate)
        let automaticShow = state.shouldShow(path: path, modificationDate: newDate, force: false)
        #expect(!oldSuppression)
        #expect(newSuppression)
        #expect(!automaticShow)
    }

    @Test func testDirectChildDetectionRejectsOutsideAndNestedPaths() {
        let directory = URL(fileURLWithPath: "/screenshots", isDirectory: true)
        #expect(ScreenshotFiles.isDirectChild(path: "/screenshots/capture.png", of: directory))
        #expect(!ScreenshotFiles.isDirectChild(path: "/other/capture.png", of: directory))
        #expect(!ScreenshotFiles.isDirectChild(path: "/screenshots/nested/capture.png", of: directory))
    }
}
