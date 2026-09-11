import AppKit
import MacflowCore

public final class A2UIPanel: FloatingSurfacePanel {
    private let theme: MacflowTheme
    private let onAction: (A2UIAction) -> Void
    private let onCompletedDrag: () -> Void
    private let container = NSView()

    public init(
        contentRect: NSRect,
        theme: MacflowTheme,
        activates: Bool,
        onAction: @escaping (A2UIAction) -> Void,
        onCompletedDrag: @escaping () -> Void
    ) {
        self.theme = theme
        self.onAction = onAction
        self.onCompletedDrag = onCompletedDrag
        super.init(contentRect: contentRect, theme: theme, activates: activates)
        container.wantsLayer = true
        container.layer?.backgroundColor = theme.background.withAlphaComponent(0.98).cgColor
        container.layer?.cornerRadius = theme.cornerRadius
        container.layer?.borderWidth = 1
        container.layer?.borderColor = theme.border.cgColor
        container.layer?.masksToBounds = true
        contentView = container
    }

    public func render(_ node: A2UINode) {
        container.subviews.forEach { $0.removeFromSuperview() }
        let view = A2UINodeRenderer.makeView(
            for: node,
            theme: theme,
            onAction: onAction,
            onCompletedDrag: onCompletedDrag
        )
        view.translatesAutoresizingMaskIntoConstraints = false
        container.addSubview(view)
        NSLayoutConstraint.activate([
            view.leadingAnchor.constraint(equalTo: container.leadingAnchor, constant: 12),
            view.trailingAnchor.constraint(equalTo: container.trailingAnchor, constant: -12),
            view.topAnchor.constraint(equalTo: container.topAnchor, constant: 12),
            view.bottomAnchor.constraint(equalTo: container.bottomAnchor, constant: -12),
        ])
    }
}
