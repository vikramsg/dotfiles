import AppKit
import MacflowCore

final class AutomationRuntime {
    private let configuration: WorkflowConfiguration
    private let windows: WindowService
    private let screens: ScreenService
    private let hotKeys: HotKeyService
    private let overlay: ImageOverlayController
    private let automaticPreview: AutomaticPreviewController
    private let layout: LayoutController
    private let shelf: FileShelfController
    private let capture: ScreenshotCaptureService
    private let server: HTTPServer

    init() throws {
        let configuration = try ConfigurationLoader.loadWorkflow()
        try configuration.validate()
        let screenshotConfiguration = try ConfigurationLoader.loadScreenshot(for: configuration)
        let screenshotDirectory = URL(
            fileURLWithPath: NSString(string: screenshotConfiguration.screenshotDirectory).expandingTildeInPath,
            isDirectory: true
        )
        let token = try RuntimeFiles.prepare(port: configuration.server.port)
        let applications = ApplicationService()
        let windows = WindowService(applications: applications)
        let screens = ScreenService()
        let hotKeys = try HotKeyService()
        let overlay = ImageOverlayController(configuration: configuration.screenshots.preview)
        let automaticPreview = AutomaticPreviewController(
            directory: screenshotDirectory,
            configuration: configuration.screenshots,
            overlay: overlay
        )
        let layout = LayoutController(
            applications: configuration.applications,
            layouts: configuration.layouts,
            applicationService: applications,
            windows: windows,
            screens: screens
        )
        let shelf = FileShelfController(windows: windows, screens: screens, hotKeys: hotKeys)
        let capture = ScreenshotCaptureService(defaultDirectory: screenshotDirectory)
        let server = HTTPServer(
            configuration: configuration.server,
            token: token,
            applications: applications,
            windows: windows,
            screens: screens,
            preview: overlay,
            capture: capture,
            watcher: automaticPreview,
            shelf: shelf,
            captureSettleSeconds: configuration.screenshots.captureSettleSeconds
        )
        self.configuration = configuration
        self.windows = windows
        self.screens = screens
        self.hotKeys = hotKeys
        self.overlay = overlay
        self.automaticPreview = automaticPreview
        self.layout = layout
        self.shelf = shelf
        self.capture = capture
        self.server = server
    }

    func start() throws {
        for binding in configuration.hotkeys {
            do {
                try hotKeys.register(
                    modifiers: binding.modifiers,
                    key: binding.key,
                    scope: binding.scope
                ) { [weak self] in
                    self?.execute(binding.action)
                }
            } catch {
                NSLog("Could not register hotkey \(binding.modifiers)+\(binding.key): \(error.localizedDescription)")
            }
        }
        try automaticPreview.start()
        try server.start()
        NSLog("Macflow started on \(configuration.server.host):\(configuration.server.port)")
    }

    func showFirstShelf() {
        guard let name = configuration.shelves.keys.sorted().first else {
            NSSound.beep()
            return
        }
        showShelf(named: name)
    }

    private func execute(_ action: WorkflowConfiguration.Action) {
        switch action.type {
        case .applyLayout:
            guard let identifier = action.layout else { return report("apply_layout requires layout") }
            layout.apply(layout: identifier) { [weak self] result in self?.report(result) }
        case .showFileShelf:
            guard let name = action.shelf else { return report("show_file_shelf requires shelf") }
            showShelf(named: name)
        }
    }

    private func showShelf(named name: String) {
        do {
            guard let configuration = configuration.shelves[name] else {
                return report("Unknown shelf: \(name)")
            }
            let path = try ConfigurationLoader.stringValue(
                configFile: configuration.directoryFrom,
                key: configuration.directoryKey
            )
            if !shelf.show(
                directory: URL(fileURLWithPath: NSString(string: path).expandingTildeInPath, isDirectory: true),
                configuration: configuration
            ) {
                report("No supported files available for shelf: \(name)")
            }
        } catch {
            report(error.localizedDescription)
        }
    }

    private func report(_ result: Result<Void, Error>) {
        if case let .failure(error) = result { report(error.localizedDescription) }
    }

    private func report(_ message: String) {
        NSLog("Macflow: \(message)")
        NSSound.beep()
    }
}
