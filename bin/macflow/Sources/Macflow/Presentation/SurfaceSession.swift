import AppKit

final class SurfaceSession {
    private let windows: WindowService
    private let screens: ScreenService
    private var panel: NSPanel?
    private var focusSnapshot: FocusSnapshot?

    init(windows: WindowService, screens: ScreenService) {
        self.windows = windows
        self.screens = screens
    }

    var frame: NSRect? { panel?.frame }
    var isVisible: Bool { panel?.isVisible == true }

    func show(
        width: Double,
        height: Double,
        margin: Double,
        activates: Bool,
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
        return panel
    }

    func hide(restoreFocus: Bool, preserveFocus: Bool = false) {
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
