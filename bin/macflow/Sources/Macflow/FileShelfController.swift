import AppKit
import MacflowCore

final class FileShelfController {
    private let windows: WindowService
    private let screens: ScreenService
    private let hotKeys: HotKeyService
    private var panel: FileShelfPanel?
    private var escapeHotKey: UInt32?
    private var focusSnapshot: FocusSnapshot?
    private var closeWork: DispatchWorkItem?
    private(set) var identifier: String?
    private(set) var paths: [String] = []

    init(windows: WindowService, screens: ScreenService, hotKeys: HotKeyService) {
        self.windows = windows
        self.screens = screens
        self.hotKeys = hotKeys
    }

    @discardableResult
    func show(directory: URL, configuration: WorkflowConfiguration.Shelf) -> Bool {
        hide(restoreFocus: false)
        let items = FileCatalog.items(
            in: directory,
            supportedExtensions: Set(configuration.extensions.map { $0.lowercased() }),
            maximumCount: configuration.maxItems
        )
        guard !items.isEmpty else { return false }

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
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.level = .floating
        panel.hidesOnDeactivate = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        let container = NSView(frame: NSRect(origin: .zero, size: panelFrame.size))
        container.wantsLayer = true
        container.layer?.backgroundColor = NSColor.windowBackgroundColor.withAlphaComponent(0.96).cgColor
        container.layer?.cornerRadius = 14
        container.layer?.masksToBounds = true

        let scroll = NSScrollView(frame: NSRect(origin: .zero, size: panelFrame.size))
        scroll.drawsBackground = false
        scroll.hasHorizontalScroller = true
        scroll.hasVerticalScroller = false
        scroll.autohidesScrollers = true
        scroll.borderType = .noBorder

        let thumbnailHeight = height - configuration.margin * 2
        let contentWidth = max(
            width,
            configuration.margin * 2
                + Double(items.count) * configuration.thumbnailWidth
                + Double(max(0, items.count - 1)) * configuration.spacing
        )
        let document = FlippedShelfView(frame: NSRect(x: 0, y: 0, width: contentWidth, height: height))
        for (index, item) in items.enumerated() {
            guard let image = NSImage(contentsOf: item.url) else { continue }
            let x = configuration.margin + Double(index) * (configuration.thumbnailWidth + configuration.spacing)
            let view = FileThumbnailView(
                frame: NSRect(
                    x: x,
                    y: configuration.margin,
                    width: configuration.thumbnailWidth,
                    height: thumbnailHeight
                ),
                fileURL: item.url,
                image: image
            ) { [weak self] in
                guard configuration.closeAfterDrag else { return }
                self?.scheduleClose(delay: configuration.closeDelay, restoreFocus: configuration.restoreFocus)
            }
            document.addSubview(view)
        }
        scroll.documentView = document
        container.addSubview(scroll)
        panel.contentView = container
        panel.orderFrontRegardless()
        self.panel = panel
        identifier = UUID().uuidString
        paths = items.map { $0.url.path }

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
        if let escapeHotKey { hotKeys.unregister(escapeHotKey) }
        escapeHotKey = nil
        panel?.orderOut(nil)
        panel?.close()
        panel = nil
        identifier = nil
        paths = []
        if restoreFocus { windows.restoreFocus(focusSnapshot) }
        focusSnapshot = nil
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
