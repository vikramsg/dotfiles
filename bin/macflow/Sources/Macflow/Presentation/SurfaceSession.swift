import AppKit

final class SurfaceSession {
    private let windows: WindowService
    private let screens: ScreenService
    private let hotKeys: HotKeyService
    private var panel: NSPanel?
    private var escapeHotKey: UInt32?
    private var focusSnapshot: FocusSnapshot?

    init(windows: WindowService, screens: ScreenService, hotKeys: HotKeyService) {
        self.windows = windows
        self.screens = screens
        self.hotKeys = hotKeys
    }

    var frame: NSRect? { panel?.frame }
    var isVisible: Bool { panel?.isVisible == true }

    func show(
        width: Double,
        height: Double,
        margin: Double,
        activates: Bool,
        onEscape: @escaping () -> Void,
        makePanel: (NSRect) throws -> NSPanel
    ) throws -> NSPanel? {
        if focusSnapshot == nil {
            focusSnapshot = windows.captureFocus()
        }
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
        else {
            focusSnapshot = nil
            return nil
        }

        let visible = appKitScreen.visibleFrame
        let panelWidth = max(1, min(width, visible.width - 40))
        let panelHeight = max(1, min(height, visible.height - 40))
        let y = max(visible.minY, visible.maxY - panelHeight - margin)
        let panelFrame = NSRect(
            x: visible.midX - panelWidth / 2,
            y: y,
            width: panelWidth,
            height: panelHeight
        )
        let panel: NSPanel
        do {
            panel = try makePanel(panelFrame)
        } catch {
            focusSnapshot = nil
            throw error
        }
        self.panel = panel
        if activates {
            NSApplication.shared.activate()
            panel.makeKeyAndOrderFront(nil)
        } else {
            panel.orderFrontRegardless()
        }
        do {
            escapeHotKey = try hotKeys.register(modifiers: [], key: "escape", callback: onEscape)
        } catch {
            NSLog("Could not register surface Escape shortcut: \(error.localizedDescription)")
        }
        return panel
    }

    func hide(restoreFocus: Bool, preserveFocus: Bool = false) {
        if let escapeHotKey { hotKeys.unregister(escapeHotKey) }
        escapeHotKey = nil
        panel?.orderOut(nil)
        panel?.close()
        panel = nil
        if restoreFocus {
            windows.restoreFocus(focusSnapshot)
            focusSnapshot = nil
        } else if !preserveFocus {
            focusSnapshot = nil
        }
    }
}
