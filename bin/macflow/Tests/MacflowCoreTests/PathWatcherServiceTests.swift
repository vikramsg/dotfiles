import Foundation
import Testing
@testable import MacflowCore

@Suite struct PathWatcherServiceIntegrationTests {
    @Test func testWatcherObservesWriteAfterDirectoryReplacement() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        let watched = root.appendingPathComponent("watched", isDirectory: true)
        let moved = root.appendingPathComponent("moved", isDirectory: true)
        try FileManager.default.createDirectory(at: watched, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }

        let lock = NSLock()
        var sawFirst = false
        var sawReplacement = false
        let queue = DispatchQueue(label: "PathWatcherServiceTests")
        let watcher = PathWatcherService(directory: watched, debounceSeconds: 0.05, queue: queue) {
            lock.lock()
            defer { lock.unlock() }
            if FileManager.default.fileExists(atPath: watched.appendingPathComponent("second").path), !sawReplacement {
                sawReplacement = true
            } else if FileManager.default.fileExists(atPath: watched.appendingPathComponent("first").path), !sawFirst {
                sawFirst = true
            }
        }
        try watcher.start()
        defer { watcher.stop() }
        try Data("first".utf8).write(to: watched.appendingPathComponent("first"))
        #expect(waitForEvent(timeout: 2, lock: lock) { sawFirst })

        try FileManager.default.moveItem(at: watched, to: moved)
        try FileManager.default.createDirectory(at: watched, withIntermediateDirectories: true)
        let deadline = Date().addingTimeInterval(2)
        repeat {
            try Data("second".utf8).write(to: watched.appendingPathComponent("second"), options: .atomic)
            if lock.withLock({ sawReplacement }) { break }
            RunLoop.current.run(until: Date().addingTimeInterval(0.05))
        } while Date() < deadline
        #expect(waitForEvent(timeout: 2, lock: lock) { sawReplacement })
    }

    private func waitForEvent(timeout: TimeInterval, lock: NSLock, condition: () -> Bool) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        repeat {
            if lock.withLock(condition) { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.05))
        } while Date() < deadline
        return lock.withLock(condition)
    }
}
