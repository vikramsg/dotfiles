import AppKit
import MacflowCore
import MacflowUI

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
        let screenshotDirectory = URL(
            fileURLWithPath: NSString(string: configuration.screenshots.directory).expandingTildeInPath,
            isDirectory: true
        )
        let theme = try BuiltInThemeCatalog.resolve(configuration.appearance.theme)
        let token = try RuntimeFiles.prepare(port: configuration.server.port)
        let applications = ApplicationService()
        let windows = WindowService(applications: applications)
        let screens = ScreenService()
        let hotKeys = try HotKeyService()
        let overlay = ImageOverlayController(configuration: configuration.screenshots.preview, theme: theme)
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
        let shelf = FileShelfController(windows: windows, screens: screens, hotKeys: hotKeys, theme: theme)
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
        guard let configuration = configuration.shelves[name] else {
            return report("Unknown shelf: \(name)")
        }
        if !shelf.show(configuration: configuration) {
            report("Could not show shelf: \(name)")
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
