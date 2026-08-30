import CoreGraphics
import Darwin
import Foundation
import ImageIO
import MacflowCore
import ScreenCaptureKit
import UniformTypeIdentifiers

enum ScreenshotCaptureError: LocalizedError {
    case invalidDestination(String)
    case encodingFailed(String)

    var errorDescription: String? {
        switch self {
        case let .invalidDestination(path): return "Invalid PNG destination: \(path)"
        case let .encodingFailed(path): return "Could not encode screenshot: \(path)"
        }
    }
}

final class ScreenshotCaptureService {
    private let defaultDirectory: URL
    private let allocator = CapturePathAllocator()

    init(defaultDirectory: URL) {
        self.defaultDirectory = defaultDirectory
    }

    func capture(
        displayID requestedDisplayID: UInt32?,
        path requestedPath: String?,
        excludingWindowIDs: Set<CGWindowID> = [],
        destinationResolved: @escaping (URL) -> Void = { _ in },
        completion: @escaping (Result<[String: Any], Error>) -> Void
    ) {
        Task {
            do {
                let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: false)
                let availableIDs = content.displays.map(\.displayID)
                let displayID = try CapturePlanning.selectDisplay(
                    requestedID: requestedDisplayID,
                    availableIDs: availableIDs,
                    mainID: CGMainDisplayID()
                )
                guard let display = content.displays.first(where: { $0.displayID == displayID }) else {
                    throw CapturePlanningError.displayNotFound(displayID)
                }
                let (destination, reserved) = try resolveDestination(requestedPath)
                defer {
                    if reserved { allocator.release(destination) }
                }
                await MainActor.run { destinationResolved(destination) }
                let excludedWindows = content.windows.filter { excludingWindowIDs.contains($0.windowID) }
                let filter = SCContentFilter(display: display, excludingWindows: excludedWindows)
                let configuration = SCStreamConfiguration()
                configuration.width = display.width
                configuration.height = display.height
                configuration.showsCursor = false
                configuration.capturesAudio = false
                let image = try await SCScreenshotManager.captureImage(
                    contentFilter: filter,
                    configuration: configuration
                )
                try writePNG(image, to: destination)
                completion(.success([
                    "path": destination.path,
                    "display_id": displayID,
                    "width": image.width,
                    "height": image.height,
                ]))
            } catch {
                completion(.failure(error))
            }
        }
    }

    private func resolveDestination(_ requestedPath: String?) throws -> (URL, Bool) {
        if requestedPath == nil {
            try FileManager.default.createDirectory(at: defaultDirectory, withIntermediateDirectories: true)
        }
        let destination = requestedPath.map { URL(fileURLWithPath: $0).standardizedFileURL }
            ?? allocator.reserve(
                directory: defaultDirectory,
                date: Date(),
                fileExists: FileManager.default.fileExists(atPath:)
            )
        let reserved = requestedPath == nil
        guard destination.pathExtension.lowercased() == "png",
              FileManager.default.fileExists(atPath: destination.deletingLastPathComponent().path),
              FileManager.default.isWritableFile(atPath: destination.deletingLastPathComponent().path)
        else {
            if reserved { allocator.release(destination) }
            throw ScreenshotCaptureError.invalidDestination(destination.path)
        }
        return (destination, reserved)
    }

    private func writePNG(_ image: CGImage, to destination: URL) throws {
        let temporary = destination.deletingLastPathComponent()
            .appendingPathComponent(".\(destination.lastPathComponent).\(UUID().uuidString).partial")
        defer { try? FileManager.default.removeItem(at: temporary) }
        guard let writer = CGImageDestinationCreateWithURL(
            temporary as CFURL,
            UTType.png.identifier as CFString,
            1,
            nil
        ) else {
            throw ScreenshotCaptureError.encodingFailed(destination.path)
        }
        CGImageDestinationAddImage(writer, image, nil)
        guard CGImageDestinationFinalize(writer) else {
            throw ScreenshotCaptureError.encodingFailed(destination.path)
        }
        guard rename(temporary.path, destination.path) == 0 else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
        }
    }
}
