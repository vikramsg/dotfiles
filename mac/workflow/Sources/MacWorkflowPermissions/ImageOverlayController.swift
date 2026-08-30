import AppKit
import MacWorkflowCore

final class OverlayImageView: NSImageView {
    var fileURL: URL?
    var dismiss: (() -> Void)?

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func mouseUp(with event: NSEvent) {
        guard let fileURL else { return }
        NSWorkspace.shared.open(fileURL)
        dismiss?()
    }

    override func rightMouseUp(with event: NSEvent) {
        guard let fileURL else { return }
        NSWorkspace.shared.activateFileViewerSelecting([fileURL])
        dismiss?()
    }
}

final class ImageOverlayPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}

final class ImageOverlayController {
    private var panel: ImageOverlayPanel?
    private var dismissal: DispatchWorkItem?
    private var configuration: WorkflowConfiguration.Screenshots.Preview
    private(set) var currentPath: String?

    init(configuration: WorkflowConfiguration.Screenshots.Preview) {
        self.configuration = configuration
    }

    func update(configuration: WorkflowConfiguration.Screenshots.Preview) {
        self.configuration = configuration
    }

    @discardableResult
    func show(path: String, timeout: Double? = nil) -> Bool {
        let url = URL(fileURLWithPath: path)
        guard FileManager.default.isReadableFile(atPath: url.path), let image = NSImage(contentsOf: url) else {
            return false
        }

        hide()
        let imageSize = image.size
        guard imageSize.width > 0, imageSize.height > 0 else { return false }
        let size = ScreenshotFiles.previewSize(
            imageWidth: imageSize.width,
            imageHeight: imageSize.height,
            maxWidth: configuration.width,
            maxHeight: configuration.maxHeight
        )

        let screen = NSScreen.screens.first(where: { $0.frame.contains(NSEvent.mouseLocation) }) ?? NSScreen.main
        guard let visibleFrame = screen?.visibleFrame else { return false }
        let frame = NSRect(
            x: visibleFrame.maxX - size.width - configuration.margin,
            y: visibleFrame.minY + configuration.margin,
            width: size.width,
            height: size.height
        )
        let panel = ImageOverlayPanel(
            contentRect: frame,
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

        let imageView = OverlayImageView(frame: NSRect(origin: .zero, size: frame.size))
        imageView.image = image
        imageView.imageScaling = .scaleProportionallyUpOrDown
        imageView.wantsLayer = true
        imageView.layer?.cornerRadius = configuration.cornerRadius
        imageView.layer?.masksToBounds = true
        imageView.layer?.borderWidth = 1
        imageView.layer?.borderColor = NSColor.white.withAlphaComponent(0.25).cgColor
        imageView.fileURL = url
        imageView.dismiss = { [weak self] in self?.hide() }
        panel.contentView = imageView
        panel.orderFrontRegardless()
        self.panel = panel
        currentPath = path

        let work = DispatchWorkItem { [weak self] in self?.hide() }
        dismissal = work
        DispatchQueue.main.asyncAfter(deadline: .now() + (timeout ?? configuration.timeoutSeconds), execute: work)
        return true
    }

    func hide() {
        dismissal?.cancel()
        dismissal = nil
        panel?.orderOut(nil)
        panel?.close()
        panel = nil
        currentPath = nil
    }

    var json: [String: Any] {
        ["visible": panel?.isVisible == true, "path": currentPath ?? NSNull()]
    }
}
