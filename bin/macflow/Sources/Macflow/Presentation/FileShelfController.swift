import AppKit
import MacflowCore
import MacflowUI

final class FileShelfController {
    private let theme: MacflowTheme
    private let session: SurfaceSession
    private var panel: FileShelfPanel?
    private var watchers: [PathWatcherService] = []
    private var activeConfiguration: WorkflowConfiguration.Shelf?
    private var closeWork: DispatchWorkItem?
    private(set) var identifier: String?
    private(set) var paths: [String] = []

    init(windows: WindowService, screens: ScreenService, hotKeys: HotKeyService, theme: MacflowTheme) {
        session = SurfaceSession(windows: windows, screens: screens, hotKeys: hotKeys)
        self.theme = theme
    }

    @discardableResult
    func show(configuration: WorkflowConfiguration.Shelf, allowsEmpty: Bool = true) -> Bool {
        hide(restoreFocus: false, preserveFocus: true)
        guard let firstSource = configuration.sources.first else {
            session.hide(restoreFocus: true)
            return false
        }
        let initialItems = items(for: firstSource, configuration: configuration)
        guard allowsEmpty || !initialItems.isEmpty else {
            session.hide(restoreFocus: true)
            return false
        }

        let shown: NSPanel?
        do {
            shown = try session.show(
                width: configuration.width,
                height: configuration.height,
                margin: configuration.margin,
                activates: false,
                onEscape: { [weak self] in self?.hide(restoreFocus: configuration.restoreFocus) }
            ) { [weak self] panelFrame in
                FileShelfPanel(
                    contentRect: panelFrame,
                    configuration: configuration,
                    theme: self?.theme ?? BuiltInThemeCatalog.system,
                    onSelectSource: { [weak self] sourceID in self?.selectSource(sourceID) },
                    onCompletedDrag: { [weak self] in
                        guard configuration.closeAfterDrag else { return }
                        self?.scheduleClose(delay: configuration.closeDelay, restoreFocus: configuration.restoreFocus)
                    }
                )
            }
        } catch {
            NSLog("Could not show file shelf: \(error.localizedDescription)")
            session.hide(restoreFocus: true)
            return false
        }
        guard let panel = shown as? FileShelfPanel else {
            session.hide(restoreFocus: true)
            return false
        }
        self.panel = panel
        activeConfiguration = configuration
        identifier = UUID().uuidString
        if allowsEmpty {
            display(source: firstSource)
        } else {
            display(source: firstSource, items: initialItems)
        }
        startWatchers(configuration: configuration)

        return true
    }

    func hide(restoreFocus: Bool = true, preserveFocus: Bool = false) {
        closeWork?.cancel()
        closeWork = nil
        watchers.forEach { $0.stop() }
        watchers = []
        panel = nil
        activeConfiguration = nil
        identifier = nil
        paths = []
        session.hide(restoreFocus: restoreFocus, preserveFocus: preserveFocus)
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
            "visible": session.isVisible,
            "paths": paths,
            "frame": session.frame.map { ["x": $0.minX, "y": $0.minY, "width": $0.width, "height": $0.height] } ?? NSNull(),
        ]
    }

    private func scheduleClose(delay: Double, restoreFocus: Bool) {
        closeWork?.cancel()
        let work = DispatchWorkItem { [weak self] in self?.hide(restoreFocus: restoreFocus) }
        closeWork = work
        DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: work)
    }
}
