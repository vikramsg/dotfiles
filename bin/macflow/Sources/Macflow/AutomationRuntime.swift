import AppKit
import MacflowCore
import MacflowUI

@MainActor
final class AutomationRuntime {
    private let startupConfiguration: WorkflowConfiguration
    private let windows: WindowService
    private let screens: ScreenService
    private let hotKeys: HotKeyService
    private let overlay: ImageOverlayController
    private let automaticPreview: AutomaticPreviewController
    private let layout: LayoutController
    private let ui: A2UISurfaceController
    private let capture: ScreenshotCaptureService
    private let server: HTTPServer

    init(
        configurationURL: URL = ConfigurationLoader.workflowURL(),
        token: String? = nil,
        hotKeys: HotKeyService = HotKeyService(),
        permissions: PermissionAccess = .live
    ) throws {
        let configuration = try ConfigurationLoader.loadWorkflow(from: configurationURL)
        try configuration.validate()
        let screenshotDirectory = URL(
            fileURLWithPath: NSString(string: configuration.screenshots.directory).expandingTildeInPath,
            isDirectory: true
        )
        let theme = try BuiltInThemeCatalog.resolve(configuration.appearance.theme)
        let token = try token ?? RuntimeFiles.prepare(port: configuration.server.port)
        let applications = ApplicationService()
        let windows = WindowService(applications: applications)
        let screens = ScreenService()
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
        let ui = A2UISurfaceController(windows: windows, screens: screens, hotKeys: hotKeys, theme: theme)
        let capture = ScreenshotCaptureService(defaultDirectory: screenshotDirectory)
        let server = HTTPServer(
            configuration: configuration.server,
            token: token,
            applications: applications,
            windows: windows,
            screens: screens,
            preview: overlay,
            screenshots: ScreenshotController(
                capture: capture, preview: overlay, watcher: automaticPreview,
                settleSeconds: configuration.screenshots.captureSettleSeconds
            ),
            ui: ui,
            hotKeyStatus: { hotKeys.status },
            permissions: permissions
        )
        self.startupConfiguration = configuration
        self.windows = windows
        self.screens = screens
        self.hotKeys = hotKeys
        self.overlay = overlay
        self.automaticPreview = automaticPreview
        self.layout = layout
        self.ui = ui
        self.capture = capture
        self.server = server
    }

    func start() throws {
        do {
            try hotKeys.start()
        } catch {
            NSLog("Global shortcuts unavailable: \(error.localizedDescription)")
        }
        for binding in startupConfiguration.hotkeys {
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
        NSLog("Macflow started on \(startupConfiguration.server.host):\(startupConfiguration.server.port)")
    }

    var httpPort: UInt16? { server.port }

    func stop() {
        ui.dismissAll(restoreFocus: false)
        server.stop()
        automaticPreview.stop()
        hotKeys.stop()
    }

    private func execute(_ action: WorkflowConfiguration.Action) {
        switch action.type {
        case .applyLayout:
            guard let identifier = action.layout else { return report("apply_layout requires layout") }
            Task {
                do {
                    try await layout.apply(layout: identifier)
                } catch {
                    report(error.localizedDescription)
                }
            }
        }
    }

    private func report(_ message: String) {
        NSLog("Macflow: \(message)")
        NSSound.beep()
    }
}
