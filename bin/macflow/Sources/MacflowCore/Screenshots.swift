import Foundation

public struct ScreenshotCandidate: Equatable {
    public let url: URL
    public let modificationDate: Date
    public let regularFile: Bool

    public init(url: URL, modificationDate: Date, regularFile: Bool) {
        self.url = url
        self.modificationDate = modificationDate
        self.regularFile = regularFile
    }
}

public enum ScreenshotFiles {
    public static func isDirectChild(path: String, of directory: URL) -> Bool {
        URL(fileURLWithPath: path).standardizedFileURL.deletingLastPathComponent()
            == directory.standardizedFileURL
    }

    public static func newest(
        candidates: [ScreenshotCandidate],
        supportedExtensions: Set<String>
    ) -> ScreenshotCandidate? {
        candidates
            .filter { $0.regularFile && supportedExtensions.contains($0.url.pathExtension.lowercased()) }
            .max { left, right in
                if left.modificationDate == right.modificationDate {
                    return left.url.path < right.url.path
                }
                return left.modificationDate < right.modificationDate
            }
    }

    public static func previewSize(imageWidth: Double, imageHeight: Double, maxWidth: Double, maxHeight: Double) -> Frame {
        guard imageWidth > 0, imageHeight > 0, maxWidth > 0, maxHeight > 0 else {
            return Frame(x: 0, y: 0, width: 0, height: 0)
        }
        let scale = min(maxWidth / imageWidth, maxHeight / imageHeight, 1)
        return Frame(x: 0, y: 0, width: imageWidth * scale, height: imageHeight * scale)
    }
}

public struct ScreenshotPresentationState {
    private struct Suppression {
        let existingModificationDate: Date?
    }

    private var suppressions: [String: Suppression] = [:]
    private var handledVersions: [String: Date] = [:]

    public init() {}

    public mutating func suppressNext(path: String, existingModificationDate: Date?) {
        suppressions[path] = Suppression(existingModificationDate: existingModificationDate)
    }

    public mutating func cancelSuppression(path: String) {
        suppressions.removeValue(forKey: path)
    }

    @discardableResult
    public mutating func consumeSuppression(path: String, modificationDate: Date) -> Bool {
        guard let suppression = suppressions[path] else { return false }
        if suppression.existingModificationDate == modificationDate { return false }
        suppressions.removeValue(forKey: path)
        markHandled(path: path, modificationDate: modificationDate)
        return true
    }

    public mutating func shouldShow(path: String, modificationDate: Date, force: Bool) -> Bool {
        if force {
            suppressions.removeValue(forKey: path)
            return true
        }
        return handledVersions[path] != modificationDate
    }

    public mutating func markHandled(path: String, modificationDate: Date) {
        handledVersions[path] = modificationDate
        if handledVersions.count > 128,
           let oldest = handledVersions.min(by: { $0.value < $1.value })?.key {
            handledVersions.removeValue(forKey: oldest)
        }
    }
}
