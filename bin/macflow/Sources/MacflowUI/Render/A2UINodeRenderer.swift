import AppKit
import MacflowCore

public enum A2UINodeRenderer {
    public static let thumbnailSize = NSSize(width: 200, height: 140)

    public static func makeView(
        for node: A2UINode,
        theme: MacflowTheme,
        onAction: @escaping (A2UIAction) -> Void,
        onCompletedDrag: @escaping () -> Void
    ) -> NSView {
        switch node {
        case let .text(text, variant):
            return makeText(text, variant: variant, theme: theme)
        case let .image(url, description):
            return makeImage(url: url, description: description, theme: theme)
        case let .fileThumbnail(url):
            return makeThumbnail(url: url, theme: theme, onCompletedDrag: onCompletedDrag)
        case let .button(child, action, variant):
            return makeButton(child: child, action: action, variant: variant, theme: theme, onAction: onAction, onCompletedDrag: onCompletedDrag)
        case let .card(child):
            return makeCard(child: child, theme: theme, onAction: onAction, onCompletedDrag: onCompletedDrag)
        case let .divider(axis):
            return makeDivider(axis: axis, theme: theme)
        case let .stack(axis, children, justify, align):
            return makeStack(axis: axis, children: children, justify: justify, align: align, theme: theme, onAction: onAction, onCompletedDrag: onCompletedDrag)
        case let .list(children, direction):
            return makeStack(axis: direction == "horizontal" ? "row" : "column", children: children, justify: "start", align: "stretch", theme: theme, onAction: onAction, onCompletedDrag: onCompletedDrag)
        case let .tabs(tabs):
            return A2UITabsView(tabs: tabs, theme: theme, onAction: onAction, onCompletedDrag: onCompletedDrag)
        }
    }

    static func fileURL(from string: String) -> URL? {
        if let url = URL(string: string), url.isFileURL {
            return url
        }
        if string.hasPrefix("/") || string.hasPrefix("~") {
            return URL(fileURLWithPath: NSString(string: string).expandingTildeInPath)
        }
        return nil
    }

    private static func makeText(_ text: String, variant: String, theme: MacflowTheme) -> NSView {
        let label = NSTextField(labelWithString: text)
        label.textColor = theme.primaryText
        switch variant {
        case "h1": label.font = .systemFont(ofSize: 22, weight: .bold)
        case "h2": label.font = .systemFont(ofSize: 18, weight: .semibold)
        case "h3": label.font = .systemFont(ofSize: 15, weight: .semibold)
        case "caption": label.font = .systemFont(ofSize: 11); label.textColor = theme.mutedText
        default: label.font = .systemFont(ofSize: 13)
        }
        return label
    }

    private static func makeImage(url: String, description: String?, theme: MacflowTheme) -> NSView {
        let view = NSImageView()
        view.imageScaling = .scaleProportionallyUpOrDown
        if let fileURL = fileURL(from: url) {
            view.image = NSImage(contentsOf: fileURL)
        }
        if let description { view.setAccessibilityLabel(description) }
        view.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            view.widthAnchor.constraint(equalToConstant: thumbnailSize.width),
            view.heightAnchor.constraint(equalToConstant: thumbnailSize.height),
        ])
        return view
    }

    private static func makeThumbnail(url: String, theme: MacflowTheme, onCompletedDrag: @escaping () -> Void) -> NSView {
        guard let fileURL = fileURL(from: url), let image = NSImage(contentsOf: fileURL) else {
            return makeText("Missing file", variant: "caption", theme: theme)
        }
        let view = FileThumbnailView(
            frame: NSRect(origin: .zero, size: thumbnailSize),
            fileURL: fileURL,
            image: image,
            theme: theme,
            onCompletedDrag: onCompletedDrag
        )
        view.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            view.widthAnchor.constraint(equalToConstant: thumbnailSize.width),
            view.heightAnchor.constraint(equalToConstant: thumbnailSize.height),
        ])
        return view
    }

    private static func makeButton(
        child: A2UINode,
        action: A2UIAction?,
        variant: String,
        theme: MacflowTheme,
        onAction: @escaping (A2UIAction) -> Void,
        onCompletedDrag: @escaping () -> Void
    ) -> NSView {
        let button = ActionButton()
        button.bezelStyle = variant == "borderless" ? .inline : .rounded
        switch child {
        case let .text(text, _):
            button.title = text
        default:
            let childView = makeView(for: child, theme: theme, onAction: onAction, onCompletedDrag: onCompletedDrag)
            childView.translatesAutoresizingMaskIntoConstraints = false
            button.addSubview(childView)
            NSLayoutConstraint.activate([
                childView.leadingAnchor.constraint(equalTo: button.leadingAnchor, constant: 4),
                childView.trailingAnchor.constraint(equalTo: button.trailingAnchor, constant: -4),
                childView.topAnchor.constraint(equalTo: button.topAnchor, constant: 4),
                childView.bottomAnchor.constraint(equalTo: button.bottomAnchor, constant: -4),
            ])
        }
        if let action {
            button.handler = { onAction(action) }
        }
        return button
    }

    private static func makeCard(
        child: A2UINode,
        theme: MacflowTheme,
        onAction: @escaping (A2UIAction) -> Void,
        onCompletedDrag: @escaping () -> Void
    ) -> NSView {
        let container = NSView()
        container.wantsLayer = true
        container.layer?.backgroundColor = theme.surface.cgColor
        container.layer?.cornerRadius = theme.cornerRadius
        container.layer?.borderWidth = 1
        container.layer?.borderColor = theme.border.cgColor
        let childView = makeView(for: child, theme: theme, onAction: onAction, onCompletedDrag: onCompletedDrag)
        childView.translatesAutoresizingMaskIntoConstraints = false
        container.addSubview(childView)
        NSLayoutConstraint.activate([
            childView.leadingAnchor.constraint(equalTo: container.leadingAnchor, constant: 12),
            childView.trailingAnchor.constraint(equalTo: container.trailingAnchor, constant: -12),
            childView.topAnchor.constraint(equalTo: container.topAnchor, constant: 12),
            childView.bottomAnchor.constraint(equalTo: container.bottomAnchor, constant: -12),
        ])
        return container
    }

    private static func makeDivider(axis: String, theme: MacflowTheme) -> NSView {
        let view = NSBox()
        view.boxType = .separator
        if axis == "vertical" {
            view.translatesAutoresizingMaskIntoConstraints = false
            view.widthAnchor.constraint(equalToConstant: 1).isActive = true
        } else {
            view.translatesAutoresizingMaskIntoConstraints = false
            view.heightAnchor.constraint(equalToConstant: 1).isActive = true
        }
        return view
    }

    private static func makeStack(
        axis: String,
        children: [A2UINode],
        justify: String,
        align: String,
        theme: MacflowTheme,
        onAction: @escaping (A2UIAction) -> Void,
        onCompletedDrag: @escaping () -> Void
    ) -> NSView {
        let stack = NSStackView()
        stack.translatesAutoresizingMaskIntoConstraints = false
        stack.orientation = axis == "row" ? .horizontal : .vertical
        stack.spacing = 8
        stack.alignment = alignment(axis: axis, align: align)
        switch justify {
        case "center", "spaceAround", "spaceBetween", "spaceEvenly":
            stack.distribution = .equalSpacing
        default:
            stack.distribution = .fill
        }
        for child in children {
            stack.addArrangedSubview(makeView(for: child, theme: theme, onAction: onAction, onCompletedDrag: onCompletedDrag))
        }
        if stack.arrangedSubviews.isEmpty {
            stack.addArrangedSubview(makeText("", variant: "body", theme: theme))
        }
        return stack
    }

    private static func alignment(axis: String, align: String) -> NSLayoutConstraint.Attribute {
        if axis == "row" {
            switch align {
            case "start": return .top
            case "center": return .centerY
            case "end": return .bottom
            default: return .height
            }
        }
        switch align {
        case "start": return .leading
        case "center": return .centerX
        case "end": return .trailing
        default: return .width
        }
    }
}

final class ActionButton: NSButton {
    var handler: (() -> Void)?

    init() {
        super.init(frame: .zero)
        target = self
        action = #selector(invoke)
    }

    required init?(coder: NSCoder) { nil }

    @objc private func invoke() {
        handler?()
    }
}

final class A2UITabsView: NSView {
    private let segmented: NSSegmentedControl
    private let container = NSView()
    private var childViews: [NSView]

    init(
        tabs: [A2UITab],
        theme: MacflowTheme,
        onAction: @escaping (A2UIAction) -> Void,
        onCompletedDrag: @escaping () -> Void
    ) {
        childViews = tabs.map {
            A2UINodeRenderer.makeView(for: $0.child, theme: theme, onAction: onAction, onCompletedDrag: onCompletedDrag)
        }
        segmented = NSSegmentedControl(labels: tabs.map(\.title), trackingMode: .selectOne, target: nil, action: nil)
        super.init(frame: .zero)
        translatesAutoresizingMaskIntoConstraints = false
        segmented.target = self
        segmented.action = #selector(selectTab)
        segmented.selectedSegment = tabs.isEmpty ? -1 : 0
        segmented.translatesAutoresizingMaskIntoConstraints = false
        container.translatesAutoresizingMaskIntoConstraints = false
        addSubview(segmented)
        addSubview(container)
        NSLayoutConstraint.activate([
            segmented.leadingAnchor.constraint(equalTo: leadingAnchor),
            segmented.topAnchor.constraint(equalTo: topAnchor),
            container.leadingAnchor.constraint(equalTo: leadingAnchor),
            container.trailingAnchor.constraint(equalTo: trailingAnchor),
            container.topAnchor.constraint(equalTo: segmented.bottomAnchor, constant: 8),
            container.bottomAnchor.constraint(equalTo: bottomAnchor),
        ])
        show(index: 0)
    }

    required init?(coder: NSCoder) { nil }

    @objc private func selectTab() {
        show(index: segmented.selectedSegment)
    }

    private func show(index: Int) {
        container.subviews.forEach { $0.removeFromSuperview() }
        guard childViews.indices.contains(index) else { return }
        let view = childViews[index]
        view.translatesAutoresizingMaskIntoConstraints = false
        container.addSubview(view)
        NSLayoutConstraint.activate([
            view.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            view.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            view.topAnchor.constraint(equalTo: container.topAnchor),
            view.bottomAnchor.constraint(equalTo: container.bottomAnchor),
        ])
    }
}
