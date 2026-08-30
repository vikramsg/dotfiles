import Foundation
import XCTest
@testable import MacflowCore

final class PathWatcherServiceIntegrationTests: XCTestCase {
    func testWatcherObservesWriteAfterDirectoryReplacement() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        let watched = root.appendingPathComponent("watched", isDirectory: true)
        let moved = root.appendingPathComponent("moved", isDirectory: true)
        try FileManager.default.createDirectory(at: watched, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }

        let first = expectation(description: "initial write observed")
        let replacement = expectation(description: "replacement write observed")
        let lock = NSLock()
        var sawFirst = false
        var sawReplacement = false
        let queue = DispatchQueue(label: "PathWatcherServiceTests")
        let watcher = PathWatcherService(directory: watched, debounceSeconds: 0.05, queue: queue) {
            lock.lock()
            defer { lock.unlock() }
            if FileManager.default.fileExists(atPath: watched.appendingPathComponent("second").path), !sawReplacement {
                sawReplacement = true
                replacement.fulfill()
            } else if FileManager.default.fileExists(atPath: watched.appendingPathComponent("first").path), !sawFirst {
                sawFirst = true
                first.fulfill()
            }
        }
        try watcher.start()
        defer { watcher.stop() }
        try Data("first".utf8).write(to: watched.appendingPathComponent("first"))
        wait(for: [first], timeout: 2)

        try FileManager.default.moveItem(at: watched, to: moved)
        try FileManager.default.createDirectory(at: watched, withIntermediateDirectories: true)
        let deadline = Date().addingTimeInterval(2)
        repeat {
            try Data("second".utf8).write(to: watched.appendingPathComponent("second"), options: .atomic)
            if sawReplacement { break }
            RunLoop.current.run(until: Date().addingTimeInterval(0.05))
        } while Date() < deadline
        wait(for: [replacement], timeout: 2)
    }
}
