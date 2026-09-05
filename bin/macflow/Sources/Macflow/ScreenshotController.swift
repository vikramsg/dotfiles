import Foundation

final class ScreenshotController {
    private let capture: any ScreenshotCapturing
    private let preview: any ScreenshotPreviewing
    private let watcher: AutomaticPreviewController
    private let settleSeconds: Double

    init(
        capture: any ScreenshotCapturing,
        preview: any ScreenshotPreviewing,
        watcher: AutomaticPreviewController,
        settleSeconds: Double
    ) {
        self.capture = capture
        self.preview = preview
        self.watcher = watcher
        self.settleSeconds = settleSeconds
    }

    func takeScreenshot(
        displayID: UInt32?,
        path: String?,
        showPreview: Bool,
        completion: @escaping (Result<[String: Any], Error>) -> Void
    ) {
        let excludedWindowID = watcher.suspend()
        var suppressedPath: String?
        DispatchQueue.main.asyncAfter(deadline: .now() + settleSeconds) {
            self.capture.capture(
                displayID: displayID,
                path: path,
                excludingWindowIDs: Set([excludedWindowID].compactMap { $0 }),
                destinationResolved: { destination in
                    suppressedPath = destination.path
                    self.watcher.suppressNext(path: destination.path)
                }
            ) { result in
                DispatchQueue.main.async {
                    self.watcher.resume()
                    switch result {
                    case let .success(value):
                        if showPreview, let path = value["path"] as? String {
                            _ = self.preview.show(path: path, timeout: nil)
                        }
                    case .failure:
                        if let suppressedPath { self.watcher.cancelSuppression(path: suppressedPath) }
                    }
                    completion(result)
                }
            }
        }
    }
}
