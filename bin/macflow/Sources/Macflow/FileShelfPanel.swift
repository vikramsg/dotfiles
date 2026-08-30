import AppKit

final class FileShelfPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}

final class FlippedShelfView: NSView {
    override var isFlipped: Bool { true }
}
