import AppKit
import MacflowCore
import MacflowUI

final class FileShelfController {
    private let windows: WindowService
    private let screens: ScreenService
    private let hotKeys: HotKeyService
    private let theme: MacflowTheme
    private var panel: FileShelfPanel?
    private var watchers: [PathWatcherService] = []
    private var activeConfiguration: WorkflowConfiguration.Shelf?
    private var escapeHotKey: UInt32?
    private var focusSnapshot: FocusSnapshot?
    private var closeWork: DispatchWorkItem?
    private(set) var identifier: String?
    private(set) var paths: [String] = []

    init(windows: WindowService, screens: ScreenService, hotKeys: HotKeyService, theme: MacflowTheme) {
        self.windows = windows
        self.screens = screens
        self.hotKeys = hotKeys
        self.theme = theme
    }

    @discardableResult
    func show(configuration: WorkflowConfiguration.Shelf, allowsEmpty: Bool = true) -> Bool {
        hide(restoreFocus: false)
        guard let firstSource = configuration.sources.first else { return false }
        let initialItems = items(for: firstSource, configuration: configuration)
        guard allowsEmpty || !initialItems.isEmpty else { return false }

        focusSnapshot = windows.captureFocus()
        let targetScreen = focusSnapshot?.frame.flatMap(screens.containing)
            ?? NSScreen.screens.first.flatMap { screen in
                screens.all().first { $0.name == screen.localizedName }
            }
        guard let targetScreen,
              let appKitScreen = NSScreen.screens.first(where: { screen in
                  guard let number = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber else {
                      return false
                  }
                  return number.uint32Value == targetScreen.id
              })
        else { return false }

        let visible = appKitScreen.visibleFrame
        let width = min(configuration.width, visible.width - 40)
        let height = min(configuration.height, visible.height - 40)
        let panelFrame = NSRect(
            x: visible.midX - width / 2,
            y: visible.maxY - height - configuration.margin,
            width: width,
            height: height
        )
        let panel = FileShelfPanel(
            contentRect: panelFrame,
            configuration: configuration,
            theme: theme,
            onSelectSource: { [weak self] sourceID in self?.selectSource(sourceID) },
            onCompletedDrag: { [weak self] in
                guard configuration.closeAfterDrag else { return }
                self?.scheduleClose(delay: configuration.closeDelay, restoreFocus: configuration.restoreFocus)
            }
        )
        panel.orderFrontRegardless()
        self.panel = panel
        activeConfiguration = configuration
        identifier = UUID().uuidString
        if allowsEmpty {
            display(source: firstSource)
        } else {
            display(source: firstSource, items: initialItems)
        }
        startWatchers(configuration: configuration)

        do {
            escapeHotKey = try hotKeys.register(modifiers: [], key: "escape") { [weak self] in
                self?.hide(restoreFocus: configuration.restoreFocus)
            }
        } catch {
            NSLog("Could not register shelf Escape shortcut: \(error.localizedDescription)")
        }
        return true
    }

    func hide(restoreFocus: Bool = true) {
        closeWork?.cancel()
        closeWork = nil
        watchers.forEach { $0.stop() }
        watchers = []
        if let escapeHotKey { hotKeys.unregister(escapeHotKey) }
        escapeHotKey = nil
        panel?.orderOut(nil)
        panel?.close()
        panel = nil
        activeConfiguration = nil
        identifier = nil
        paths = []
        if restoreFocus { windows.restoreFocus(focusSnapshot) }
        focusSnapshot = nil
    }

    private func selectSource(_ sourceID: String) {
        guard let source = activeConfiguration?.sources.first(where: { $0.id == sourceID }) else { return }
        display(source: source)
    }

    private func display(source: WorkflowConfiguration.Shelf.Source) {
        guard let configuration = activeConfiguration else { return }
        let directory = directoryURL(source.directory)
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: directory.path, isDirectory: &isDirectory), isDirectory.boolValue else {
            paths = []
            panel?.display(message: "Directory unavailable", for: source.id)
            return
        }
        display(source: source, items: items(for: source, configuration: configuration))
    }

    private func display(source: WorkflowConfiguration.Shelf.Source, items: [FileCatalogItem]) {
        paths = items.map { $0.url.path }
        panel?.display(items: items, for: source.id)
    }

    private func items(
        for source: WorkflowConfiguration.Shelf.Source,
        configuration: WorkflowConfiguration.Shelf
    ) -> [FileCatalogItem] {
        FileCatalog.items(
            in: directoryURL(source.directory),
            supportedExtensions: Set(configuration.extensions.map { $0.lowercased() }),
            maximumCount: configuration.maxItems
        )
    }

    private func startWatchers(configuration: WorkflowConfiguration.Shelf) {
        var watchedPaths = Set<String>()
        for source in configuration.sources {
            let directory = directoryURL(source.directory)
            var isDirectory: ObjCBool = false
            guard FileManager.default.fileExists(atPath: directory.path, isDirectory: &isDirectory),
                  isDirectory.boolValue
            else {
                NSLog("Shelf directory is unavailable: \(directory.path)")
                continue
            }
            guard watchedPaths.insert(directory.path).inserted else { continue }
            let watcher = PathWatcherService(directory: directory, debounceSeconds: 0.2) { [weak self] in
                guard let self,
                      let selectedID = self.panel?.selectedSourceID,
                      let selected = self.activeConfiguration?.sources.first(where: { $0.id == selectedID }),
                      self.directoryURL(selected.directory).path == directory.path
                else { return }
                self.display(source: selected)
            }
            do {
                try watcher.start()
                watchers.append(watcher)
            } catch {
                NSLog("Could not watch shelf directory \(directory.path): \(error.localizedDescription)")
            }
        }
    }

    private func directoryURL(_ path: String) -> URL {
        URL(fileURLWithPath: NSString(string: path).expandingTildeInPath, isDirectory: true)
    }

    var json: [String: Any] {
        [
            "id": identifier ?? NSNull(),
            "visible": panel?.isVisible == true,
            "paths": paths,
            "frame": panel.map { ["x": $0.frame.minX, "y": $0.frame.minY, "width": $0.frame.width, "height": $0.frame.height] } ?? NSNull(),
        ]
    }

    private func scheduleClose(delay: Double, restoreFocus: Bool) {
        closeWork?.cancel()
        let work = DispatchWorkItem { [weak self] in self?.hide(restoreFocus: restoreFocus) }
        closeWork = work
        DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: work)
    }
}
