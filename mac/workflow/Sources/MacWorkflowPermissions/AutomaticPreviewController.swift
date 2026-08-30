import Foundation
import MacWorkflowCore

final class AutomaticPreviewController {
    private let overlay: ImageOverlayController
    private let directory: URL
    private let supportedExtensions: Set<String>
    private let debounceSeconds: Double
    private var watcher: PathWatcherService?
    private var presentationState = ScreenshotPresentationState()
    private var failedCandidate: (path: String, modification: Date, attempts: Int)?
    private var suspensionGate = SuspensionGate()

    init(
        directory: URL,
        configuration: WorkflowConfiguration.Screenshots,
        overlay: ImageOverlayController
    ) {
        self.directory = directory
        self.overlay = overlay
        supportedExtensions = Set(configuration.extensions.map { $0.lowercased() })
        debounceSeconds = configuration.debounceSeconds
    }

    func start() throws {
        let watcher = PathWatcherService(
            directory: directory,
            debounceSeconds: debounceSeconds
        ) { [weak self] in
            _ = self?.showLatest(force: false)
        }
        self.watcher = watcher
        try watcher.start()
    }

    func stop() {
        watcher?.stop()
        watcher = nil
    }

    func latest() -> URL? {
        newestCandidate()?.url
    }

    func suppressNext(path: String) {
        guard ScreenshotFiles.isDirectChild(path: path, of: directory) else { return }
        let modification = try? URL(fileURLWithPath: path)
            .resourceValues(forKeys: [.contentModificationDateKey])
            .contentModificationDate
        presentationState.suppressNext(path: path, existingModificationDate: modification)
    }

    func cancelSuppression(path: String) {
        presentationState.cancelSuppression(path: path)
    }

    func suspend() {
        suspensionGate.suspend()
        overlay.hide()
    }

    func resume() {
        suspensionGate.resume()
    }

    @discardableResult
    func showLatest(force: Bool = true) -> Bool {
        guard !suspensionGate.isSuspended else { return false }
        guard let candidate = newestCandidate() else { return false }
        let url = candidate.url
        let modification = candidate.modificationDate
        if !presentationState.shouldShow(path: url.path, modificationDate: modification, force: force) {
            return false
        }
        guard overlay.show(path: url.path) else {
            let attempts: Int
            if failedCandidate?.path == url.path, failedCandidate?.modification == modification {
                attempts = (failedCandidate?.attempts ?? 0) + 1
            } else {
                attempts = 1
            }
            failedCandidate = (url.path, modification, attempts)
            if attempts < 3 { watcher?.schedule(delay: 0.2) }
            return false
        }
        failedCandidate = nil
        presentationState.markHandled(path: url.path, modificationDate: modification)
        return true
    }

    private func newestCandidate() -> ScreenshotCandidate? {
        let candidates = FileCatalog.items(
            in: directory,
            supportedExtensions: supportedExtensions
        ).map {
            ScreenshotCandidate(url: $0.url, modificationDate: $0.modificationDate, regularFile: true)
        }
        for candidate in candidates {
            _ = presentationState.consumeSuppression(
                path: candidate.url.path,
                modificationDate: candidate.modificationDate
            )
        }
        return ScreenshotFiles.newest(candidates: candidates, supportedExtensions: supportedExtensions)
    }

    deinit { stop() }
}
