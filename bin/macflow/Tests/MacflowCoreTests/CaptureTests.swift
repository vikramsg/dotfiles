import Foundation
import XCTest
@testable import MacflowCore

final class CaptureTests: XCTestCase {
    func testDisplaySelectionUsesMainDisplayByDefaultAndHonorsValidRequest() throws {
        XCTAssertEqual(
            try CapturePlanning.selectDisplay(requestedID: nil, availableIDs: [10, 20], mainID: 20),
            20
        )
        XCTAssertEqual(
            try CapturePlanning.selectDisplay(requestedID: 10, availableIDs: [10, 20], mainID: 20),
            10
        )
        XCTAssertThrowsError(
            try CapturePlanning.selectDisplay(requestedID: 30, availableIDs: [10, 20], mainID: 20)
        ) { error in
            XCTAssertEqual(error as? CapturePlanningError, .displayNotFound(30))
        }
    }

    func testDestinationAddsSuffixWhenTimestampedPathExists() {
        let directory = URL(fileURLWithPath: "/screenshots", isDirectory: true)
        let date = Date(timeIntervalSince1970: 0)
        let timeZone = TimeZone(secondsFromGMT: 0)!
        let first = CapturePlanning.destination(
            directory: directory,
            date: date,
            timeZone: timeZone,
            fileExists: { _ in false }
        )
        XCTAssertEqual(first.path, "/screenshots/Screenshot 1970-01-01 at 00.00.00.png")

        let second = CapturePlanning.destination(
            directory: directory,
            date: date,
            timeZone: timeZone,
            fileExists: { $0 == first.path }
        )
        XCTAssertEqual(second.path, "/screenshots/Screenshot 1970-01-01 at 00.00.00-2.png")
    }

    func testAllocatorReservesUniqueConcurrentPaths() {
        let allocator = CapturePathAllocator()
        let directory = URL(fileURLWithPath: "/screenshots", isDirectory: true)
        let date = Date(timeIntervalSince1970: 0)
        let timeZone = TimeZone(secondsFromGMT: 0)!
        let lock = NSLock()
        var paths: [String] = []

        DispatchQueue.concurrentPerform(iterations: 10) { _ in
            let url = allocator.reserve(
                directory: directory,
                date: date,
                timeZone: timeZone,
                fileExists: { _ in false }
            )
            lock.lock()
            paths.append(url.path)
            lock.unlock()
        }

        XCTAssertEqual(Set(paths).count, 10)
    }
}
