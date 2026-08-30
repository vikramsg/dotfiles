import Foundation

public enum CapturePlanningError: LocalizedError, Equatable {
    case displayNotFound(UInt32)

    public var errorDescription: String? {
        switch self {
        case let .displayNotFound(id): return "Display not found: \(id)"
        }
    }
}

public enum CapturePlanning {
    public static func selectDisplay(
        requestedID: UInt32?,
        availableIDs: [UInt32],
        mainID: UInt32
    ) throws -> UInt32 {
        guard let requestedID else { return mainID }
        guard availableIDs.contains(requestedID) else {
            throw CapturePlanningError.displayNotFound(requestedID)
        }
        return requestedID
    }

    public static func destination(
        directory: URL,
        date: Date,
        timeZone: TimeZone = .current,
        fileExists: (String) -> Bool
    ) -> URL {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = timeZone
        formatter.dateFormat = "yyyy-MM-dd 'at' HH.mm.ss"
        let stem = "Screenshot \(formatter.string(from: date))"
        var candidate = directory.appendingPathComponent(stem).appendingPathExtension("png")
        var suffix = 2
        while fileExists(candidate.path) {
            candidate = directory.appendingPathComponent("\(stem)-\(suffix)").appendingPathExtension("png")
            suffix += 1
        }
        return candidate
    }
}

public final class CapturePathAllocator: @unchecked Sendable {
    private let lock = NSLock()
    private var reserved: Set<String> = []

    public init() {}

    public func reserve(
        directory: URL,
        date: Date,
        timeZone: TimeZone = .current,
        fileExists: (String) -> Bool
    ) -> URL {
        lock.lock()
        defer { lock.unlock() }
        let destination = CapturePlanning.destination(
            directory: directory,
            date: date,
            timeZone: timeZone,
            fileExists: { fileExists($0) || self.reserved.contains($0) }
        )
        reserved.insert(destination.path)
        return destination
    }

    public func release(_ destination: URL) {
        lock.lock()
        reserved.remove(destination.path)
        lock.unlock()
    }
}
