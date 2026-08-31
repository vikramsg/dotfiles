import AppKit

final class FileThumbnailView: NSView, NSDraggingSource {
    private let fileURL: URL
    private let image: NSImage
    private let onCompletedDrag: () -> Void
    private var mouseDownEvent: NSEvent?
    private var startedDrag = false

    init(
        frame: NSRect,
        fileURL: URL,
        image: NSImage,
        theme: MacflowTheme,
        onCompletedDrag: @escaping () -> Void
    ) {
        self.fileURL = fileURL
        self.image = image
        self.onCompletedDrag = onCompletedDrag
        super.init(frame: frame)
        wantsLayer = true
        layer?.backgroundColor = theme.raisedSurface.cgColor
        layer?.cornerRadius = theme.controlCornerRadius
        layer?.borderWidth = 1
        layer?.borderColor = theme.border.cgColor

        let imageView = NSImageView(frame: NSRect(x: 8, y: 30, width: frame.width - 16, height: frame.height - 38))
        imageView.image = image
        imageView.imageScaling = .scaleProportionallyUpOrDown
        addSubview(imageView)

        let label = NSTextField(labelWithString: fileURL.lastPathComponent)
        label.frame = NSRect(x: 8, y: 7, width: frame.width - 16, height: 17)
        label.lineBreakMode = .byTruncatingMiddle
        label.font = .systemFont(ofSize: 11)
        label.textColor = theme.secondaryText
        addSubview(label)
    }

    required init?(coder: NSCoder) { nil }

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func hitTest(_ point: NSPoint) -> NSView? {
        bounds.contains(convert(point, from: superview)) ? self : nil
    }

    override func mouseDown(with event: NSEvent) {
        mouseDownEvent = event
        startedDrag = false
    }

    override func mouseUp(with event: NSEvent) {
        guard !startedDrag else { return }
        NSWorkspace.shared.open(fileURL)
    }

    override func rightMouseUp(with event: NSEvent) {
        NSWorkspace.shared.activateFileViewerSelecting([fileURL])
    }

    override func mouseDragged(with event: NSEvent) {
        guard let initial = mouseDownEvent else { return }
        let dx = event.locationInWindow.x - initial.locationInWindow.x
        let dy = event.locationInWindow.y - initial.locationInWindow.y
        guard hypot(dx, dy) >= 6 else { return }
        mouseDownEvent = nil
        startedDrag = true
        let item = NSDraggingItem(pasteboardWriter: fileURL as NSURL)
        item.setDraggingFrame(bounds, contents: image)
        beginDraggingSession(with: [item], event: event, source: self)
    }

    func draggingSession(_ session: NSDraggingSession, sourceOperationMaskFor context: NSDraggingContext) -> NSDragOperation {
        .copy
    }

    func ignoreModifierKeys(for session: NSDraggingSession) -> Bool { true }

    func draggingSession(_ session: NSDraggingSession, endedAt screenPoint: NSPoint, operation: NSDragOperation) {
        if !operation.isEmpty { onCompletedDrag() }
    }
}
