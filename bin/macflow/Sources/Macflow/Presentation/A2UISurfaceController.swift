import AppKit
import MacflowCore
import MacflowUI

final class A2UISurfaceController {
    private let windows: WindowService
    private let screens: ScreenService
    private let hotKeys: HotKeyService
    private let theme: MacflowTheme

    private var store = A2UISurfaceStore()
    private var sessions: [String: SurfaceSession] = [:]
    private var panels: [String: A2UIPanel] = [:]
    private var order: [String] = []
    private var escapeHotKey: UInt32?

    init(windows: WindowService, screens: ScreenService, hotKeys: HotKeyService, theme: MacflowTheme) {
        self.windows = windows
        self.screens = screens
        self.hotKeys = hotKeys
        self.theme = theme
    }

    var json: [[String: Any]] {
        store.ids.compactMap { store.surface(id: $0).map(descriptor) }
    }

    @discardableResult
    func apply(payload: Data) throws -> [[String: Any]] {
        let messages = try A2UIMessageDecoder.decode(payload)
        let touched = try store.apply(messages)
        for id in touched {
            if store.surface(id: id) == nil {
                dismiss(id: id, restoreFocus: true)
            } else {
                present(id: id)
            }
        }
        return touched.compactMap { store.surface(id: $0).map(descriptor) }
    }

    func dismiss(id: String, restoreFocus: Bool) {
        sessions[id]?.hide(restoreFocus: restoreFocus)
        sessions[id] = nil
        panels[id] = nil
        order.removeAll { $0 == id }
        store.remove(id: id)
        if sessions.isEmpty, let escapeHotKey {
            hotKeys.unregister(escapeHotKey)
            self.escapeHotKey = nil
        }
    }

    func dismissAll(restoreFocus: Bool) {
        for id in order.reversed() {
            dismiss(id: id, restoreFocus: restoreFocus)
        }
    }

    private func present(id: String) {
        guard let surface = store.surface(id: id) else { return }
        guard let node = try? A2UIResolver.resolve(surface) else {
            NSLog("Macflow: could not resolve A2UI surface \(id)")
            return
        }
        if let panel = panels[id] {
            panel.render(node)
            return
        }
        let session = SurfaceSession(windows: windows, screens: screens)
        do {
            let shown = try session.show(
                width: surface.properties.width,
                height: surface.properties.height,
                margin: surface.properties.margin,
                activates: surface.properties.activates
            ) { frame in
                A2UIPanel(
                    contentRect: frame,
                    theme: self.theme,
                    activates: surface.properties.activates,
                    onAction: { [weak self] action in self?.handle(action: action, surfaceId: id) },
                    onCompletedDrag: { [weak self] in self?.dismiss(id: id, restoreFocus: true) }
                )
            }
            guard let panel = shown as? A2UIPanel else { return }
            panel.render(node)
            sessions[id] = session
            panels[id] = panel
            if !order.contains(id) { order.append(id) }
            registerEscapeIfNeeded()
        } catch {
            NSLog("Macflow: could not show A2UI surface \(id): \(error.localizedDescription)")
        }
    }

    private func handle(action: A2UIAction, surfaceId: String) {
        switch action {
        case let .function(name, arguments):
            switch name {
            case "files.open":
                if let path = arguments["path"]?.stringValue { open(path) }
            case "files.reveal":
                if let path = arguments["path"]?.stringValue { reveal(path) }
            case "surface.dismiss":
                dismiss(id: surfaceId, restoreFocus: true)
            case "openUrl":
                if let value = arguments["url"]?.stringValue, let url = URL(string: value) {
                    NSWorkspace.shared.open(url)
                }
            default:
                break
            }
        case .event:
            break
        }
    }

    private func registerEscapeIfNeeded() {
        guard escapeHotKey == nil, !sessions.isEmpty else { return }
        do {
            escapeHotKey = try hotKeys.register(modifiers: [], key: "escape") { [weak self] in
                self?.dismissActive()
            }
        } catch {
            NSLog("Macflow: could not register surface Escape: \(error.localizedDescription)")
        }
    }

    private func dismissActive() {
        guard let id = order.last else { return }
        dismiss(id: id, restoreFocus: true)
    }

    private func open(_ path: String) {
        NSWorkspace.shared.open(URL(fileURLWithPath: NSString(string: path).expandingTildeInPath))
    }

    private func reveal(_ path: String) {
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: NSString(string: path).expandingTildeInPath)])
    }

    private func descriptor(_ surface: A2UISurface) -> [String: Any] {
        [
            "surfaceId": surface.id,
            "visible": panels[surface.id] != nil,
            "component_count": surface.components.count,
            "frame": sessions[surface.id]?.frame.map {
                ["x": $0.minX, "y": $0.minY, "width": $0.width, "height": $0.height]
            } ?? NSNull(),
        ]
    }
}
