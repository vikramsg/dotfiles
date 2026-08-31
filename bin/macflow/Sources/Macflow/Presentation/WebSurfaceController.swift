import AppKit
import MacflowCore
import MacflowUI

enum WebSurfaceCapabilityError: LocalizedError {
    case unknownAction(String)
    case invalidPayload(String)
    case unavailablePath(String)
    case missingDocument(String)

    var errorDescription: String? {
        switch self {
        case let .unknownAction(action): return "Unknown web surface action: \(action)"
        case let .invalidPayload(action): return "Invalid payload for web surface action: \(action)"
        case let .unavailablePath(path): return "Path is unavailable: \(path)"
        case let .missingDocument(path): return "Web surface document is unavailable: \(path)"
        }
    }
}

final class WebSurfaceController {
    private let configurationDirectory: URL
    private let theme: MacflowTheme
    private let session: SurfaceSession
    private var panel: WebSurfacePanel?
    private var activeConfiguration: WorkflowConfiguration.Surface?
    private var closeWork: DispatchWorkItem?

    init(
        configurationURL: URL,
        windows: WindowService,
        screens: ScreenService,
        hotKeys: HotKeyService,
        theme: MacflowTheme
    ) {
        configurationDirectory = configurationURL.deletingLastPathComponent().standardizedFileURL
        session = SurfaceSession(windows: windows, screens: screens, hotKeys: hotKeys)
        self.theme = theme
    }

    @discardableResult
    func show(configuration: WorkflowConfiguration.Surface) -> Bool {
        hide(restoreFocus: false, preserveFocus: true)
        let documentURL = configurationDirectory
            .appendingPathComponent(configuration.document)
            .standardizedFileURL
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: documentURL.path, isDirectory: &isDirectory),
              !isDirectory.boolValue
        else {
            NSLog("Macflow: \(WebSurfaceCapabilityError.missingDocument(documentURL.path).localizedDescription)")
            session.hide(restoreFocus: true)
            return false
        }

        activeConfiguration = configuration
        do {
            let shown = try session.show(
                width: configuration.width,
                height: configuration.height,
                margin: configuration.margin,
                activates: configuration.activates,
                onEscape: { [weak self] in self?.hide() }
            ) { [weak self] frame in
                let panel = try WebSurfacePanel(
                    contentRect: frame,
                    documentURL: documentURL,
                    surfaceConfiguration: configuration.configuration.mapValues(\.foundationObject),
                    theme: self?.theme ?? BuiltInThemeCatalog.system,
                    activates: configuration.activates,
                    requestHandler: { [weak self] panel, request in
                        try self?.handle(request, panel: panel)
                    },
                    onCompletedDrag: { [weak self] in self?.completedDrag() }
                )
                return panel
            }
            panel = shown as? WebSurfacePanel
            if panel == nil {
                activeConfiguration = nil
                session.hide(restoreFocus: true)
                return false
            }
            return true
        } catch {
            NSLog("Could not show web surface: \(error.localizedDescription)")
            activeConfiguration = nil
            session.hide(restoreFocus: true)
            return false
        }
    }

    func hide(restoreFocus: Bool? = nil, preserveFocus: Bool = false) {
        closeWork?.cancel()
        closeWork = nil
        let shouldRestore = restoreFocus ?? activeConfiguration?.restoreFocus ?? true
        panel = nil
        activeConfiguration = nil
        session.hide(restoreFocus: shouldRestore, preserveFocus: preserveFocus)
    }

    private func handle(_ request: WebSurfaceRequest, panel: WebSurfacePanel?) throws -> Any? {
        switch request.action {
        case "files.list":
            return try listFiles(request.payload, panel: panel)
        case "files.open":
            let url = try fileURL(request.payload, action: request.action)
            guard NSWorkspace.shared.open(url) else {
                throw WebSurfaceCapabilityError.unavailablePath(url.path)
            }
            return true
        case "files.reveal":
            let url = try fileURL(request.payload, action: request.action)
            NSWorkspace.shared.activateFileViewerSelecting([url])
            return true
        case "files.prepareDrag":
            let url = try fileURL(request.payload, action: request.action)
            panel?.prepareFileDrag(url)
            return true
        case "surface.dismiss":
            DispatchQueue.main.async { [weak self] in self?.hide() }
            return true
        case "diagnostics.log":
            guard let message = request.payload["message"] as? String else {
                throw WebSurfaceCapabilityError.invalidPayload(request.action)
            }
            NSLog("Web surface: \(message)")
            return true
        default:
            throw WebSurfaceCapabilityError.unknownAction(request.action)
        }
    }

    private func listFiles(_ payload: [String: Any], panel: WebSurfacePanel?) throws -> [[String: Any]] {
        guard let path = payload["directory"] as? String,
              let extensions = payload["extensions"] as? [String],
              let limitNumber = payload["limit"] as? NSNumber,
              limitNumber.intValue > 0
        else { throw WebSurfaceCapabilityError.invalidPayload("files.list") }
        let directory = expandedURL(path, isDirectory: true)
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: directory.path, isDirectory: &isDirectory),
              isDirectory.boolValue
        else { throw WebSurfaceCapabilityError.unavailablePath(directory.path) }

        let items = FileCatalog.items(
            in: directory,
            supportedExtensions: Set(extensions.map { $0.lowercased() }),
            maximumCount: min(limitNumber.intValue, 100)
        )
        let registeredFiles = panel?.registerFiles(items.map(\.url)) ?? [:]
        return items.map { item in
            [
                "name": item.url.lastPathComponent,
                "path": item.url.path,
                "modifiedAt": item.modificationDate.timeIntervalSince1970,
                "thumbnail": registeredFiles[item.url.path] ?? NSNull(),
            ]
        }
    }

    private func fileURL(_ payload: [String: Any], action: String) throws -> URL {
        guard let path = payload["path"] as? String else {
            throw WebSurfaceCapabilityError.invalidPayload(action)
        }
        let url = expandedURL(path, isDirectory: false)
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory),
              !isDirectory.boolValue
        else { throw WebSurfaceCapabilityError.unavailablePath(url.path) }
        return url
    }

    private func expandedURL(_ path: String, isDirectory: Bool) -> URL {
        URL(
            fileURLWithPath: NSString(string: path).expandingTildeInPath,
            isDirectory: isDirectory
        ).standardizedFileURL
    }

    private func completedDrag() {
        guard let configuration = activeConfiguration, configuration.closeAfterDrag else { return }
        closeWork?.cancel()
        let work = DispatchWorkItem { [weak self] in self?.hide() }
        closeWork = work
        DispatchQueue.main.asyncAfter(deadline: .now() + configuration.closeDelay, execute: work)
    }
}
