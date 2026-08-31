import AppKit

open class FloatingSurfacePanel: NSPanel {
    private let activatesSurface: Bool

    public init(
        contentRect: NSRect,
        theme: MacflowTheme,
        activates: Bool
    ) {
        activatesSurface = activates
        var styleMask: NSWindow.StyleMask = [.borderless]
        if !activates {
            styleMask.insert(.nonactivatingPanel)
        }
        super.init(
            contentRect: contentRect,
            styleMask: styleMask,
            backing: .buffered,
            defer: false
        )
        appearance = theme.appearance
        isOpaque = false
        backgroundColor = .clear
        hasShadow = true
        level = .floating
        hidesOnDeactivate = false
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
    }

    public override var canBecomeKey: Bool { activatesSurface }
    public override var canBecomeMain: Bool { false }
}
