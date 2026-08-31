import AppKit
import MacflowCore

public final class FileShelfPanel: NSPanel {
    private let shelfContent: FileShelfContentView

    public init(
        contentRect: NSRect,
        configuration: WorkflowConfiguration.Shelf,
        theme: MacflowTheme,
        onSelectSource: @escaping (String) -> Void,
        onCompletedDrag: @escaping () -> Void
    ) {
        shelfContent = FileShelfContentView(
            frame: NSRect(origin: .zero, size: contentRect.size),
            configuration: configuration,
            theme: theme,
            onSelectSource: onSelectSource,
            onCompletedDrag: onCompletedDrag
        )
        super.init(
            contentRect: contentRect,
            styleMask: [.borderless, .nonactivatingPanel],
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
        contentView = shelfContent
    }

    public override var canBecomeKey: Bool { false }
    public override var canBecomeMain: Bool { false }

    public var selectedSourceID: String { shelfContent.selectedSourceID }

    public func display(items: [FileCatalogItem], for sourceID: String) {
        shelfContent.display(items: items, for: sourceID)
    }

    public func display(message: String, for sourceID: String) {
        shelfContent.display(message: message, for: sourceID)
    }
}

private final class FileShelfContentView: NSView {
    private let configuration: WorkflowConfiguration.Shelf
    private let theme: MacflowTheme
    private let onSelectSource: (String) -> Void
    private let onCompletedDrag: () -> Void
    private let tabBar = NSView()
    private let scroll = NSScrollView()
    private let document = FlippedShelfView()
    private var state: FileShelfState
    private var tabButtons: [ShelfTabButton] = []

    var selectedSourceID: String { state.selectedSourceID }

    init(
        frame frameRect: NSRect,
        configuration: WorkflowConfiguration.Shelf,
        theme: MacflowTheme,
        onSelectSource: @escaping (String) -> Void,
        onCompletedDrag: @escaping () -> Void
    ) {
        guard let state = FileShelfState(sourceIDs: configuration.sources.map(\.id)) else {
            preconditionFailure("Validated shelf configuration must have unique sources")
        }
        self.configuration = configuration
        self.theme = theme
        self.onSelectSource = onSelectSource
        self.onCompletedDrag = onCompletedDrag
        self.state = state
        super.init(frame: frameRect)

        wantsLayer = true
        layer?.backgroundColor = theme.background.withAlphaComponent(0.98).cgColor
        layer?.cornerRadius = theme.cornerRadius
        layer?.borderWidth = 1
        layer?.borderColor = theme.border.cgColor
        layer?.masksToBounds = true

        tabBar.wantsLayer = true
        tabBar.layer?.backgroundColor = theme.surface.cgColor
        addSubview(tabBar)

        scroll.drawsBackground = false
        scroll.hasHorizontalScroller = true
        scroll.hasVerticalScroller = false
        scroll.autohidesScrollers = true
        scroll.borderType = .noBorder
        scroll.documentView = document
        addSubview(scroll)

        configureTabs()
        layoutContent()
    }

    required init?(coder: NSCoder) { nil }

    override func layout() {
        super.layout()
        layoutContent()
    }

    func display(items: [FileCatalogItem], for sourceID: String) {
        guard sourceID == state.selectedSourceID else { return }
        document.subviews.forEach { $0.removeFromSuperview() }

        let contentHeight = scroll.bounds.height
        guard !items.isEmpty else {
            display(message: "No files available", for: sourceID)
            return
        }

        let thumbnailHeight = max(40, contentHeight - configuration.margin * 2)
        let contentWidth = max(
            scroll.bounds.width,
            configuration.margin * 2
                + Double(items.count) * configuration.thumbnailWidth
                + Double(max(0, items.count - 1)) * configuration.spacing
        )
        document.frame = NSRect(x: 0, y: 0, width: contentWidth, height: contentHeight)
        for (index, item) in items.enumerated() {
            guard let image = NSImage(contentsOf: item.url) else { continue }
            let x = configuration.margin + Double(index) * (configuration.thumbnailWidth + configuration.spacing)
            document.addSubview(FileThumbnailView(
                frame: NSRect(
                    x: x,
                    y: configuration.margin,
                    width: configuration.thumbnailWidth,
                    height: thumbnailHeight
                ),
                fileURL: item.url,
                image: image,
                theme: theme,
                onCompletedDrag: onCompletedDrag
            ))
        }
    }

    func display(message: String, for sourceID: String) {
        guard sourceID == state.selectedSourceID else { return }
        document.subviews.forEach { $0.removeFromSuperview() }
        let label = NSTextField(labelWithString: message)
        label.font = .systemFont(ofSize: 13, weight: .medium)
        label.textColor = theme.mutedText
        label.alignment = .center
        label.frame = NSRect(x: 0, y: max(0, scroll.bounds.height / 2 - 10), width: scroll.bounds.width, height: 20)
        document.frame = NSRect(origin: .zero, size: scroll.bounds.size)
        document.addSubview(label)
    }

    private func configureTabs() {
        tabButtons = configuration.sources.map { source in
            let button = ShelfTabButton(
                sourceID: source.id,
                label: source.label,
                symbolName: source.icon,
                style: theme.tabs
            )
            button.target = self
            button.action = #selector(selectTab(_:))
            tabBar.addSubview(button)
            return button
        }
        updateTabStyles()
    }

    private func layoutContent() {
        let tabBarHeight = configuration.sources.count > 1
            ? theme.tabs.height + theme.tabs.verticalPadding * 2
            : 0
        tabBar.isHidden = tabBarHeight == 0
        tabBar.frame = NSRect(x: 0, y: bounds.height - tabBarHeight, width: bounds.width, height: tabBarHeight)
        scroll.frame = NSRect(x: 0, y: 0, width: bounds.width, height: bounds.height - tabBarHeight)

        guard !tabButtons.isEmpty else { return }
        let preferredWidths = tabButtons.map(\.preferredWidth)
        let spacingWidth = theme.tabs.itemSpacing * CGFloat(tabButtons.count - 1)
        let availableWidth = max(0, bounds.width - configuration.margin * 2 - spacingWidth)
        let preferredTotal = preferredWidths.reduce(0, +)
        let widths = preferredTotal <= availableWidth
            ? preferredWidths
            : Array(repeating: availableWidth / CGFloat(tabButtons.count), count: tabButtons.count)
        let totalWidth = widths.reduce(0, +) + spacingWidth
        var x = (bounds.width - totalWidth) / 2
        for (button, width) in zip(tabButtons, widths) {
            button.frame = NSRect(
                x: x,
                y: theme.tabs.verticalPadding,
                width: width,
                height: theme.tabs.height
            )
            button.layer?.cornerRadius = theme.controlCornerRadius
            x += width + theme.tabs.itemSpacing
        }
    }

    @objc private func selectTab(_ sender: ShelfTabButton) {
        guard state.select(sender.sourceID) else { return }
        updateTabStyles()
        onSelectSource(sender.sourceID)
    }

    private func updateTabStyles() {
        for button in tabButtons {
            let selected = button.sourceID == state.selectedSourceID
            button.layer?.backgroundColor = (selected ? theme.selectedSurface : theme.surface).cgColor
            button.layer?.borderWidth = selected ? 1 : 0
            button.layer?.borderColor = theme.focusedBorder.cgColor
            button.apply(
                selected: selected,
                foreground: selected ? theme.primaryText : theme.secondaryText,
                accent: selected ? theme.accent : theme.secondaryText
            )
        }
    }
}

final class ShelfTabButton: NSButton {
    let sourceID: String
    let sourceLabel: String
    let style: TabStyle
    let iconView = NSImageView()
    let titleLabel: NSTextField
    let naturalLabelWidth: CGFloat

    init(sourceID: String, label: String, symbolName: String, style: TabStyle) {
        self.sourceID = sourceID
        sourceLabel = label
        self.style = style
        let titleLabel = NSTextField(labelWithString: label)
        let measuringFont = NSFont.systemFont(ofSize: style.fontSize, weight: .semibold)
        titleLabel.font = measuringFont
        titleLabel.lineBreakMode = .byTruncatingTail
        titleLabel.maximumNumberOfLines = 1
        titleLabel.sizeToFit()
        self.titleLabel = titleLabel
        naturalLabelWidth = ceil(titleLabel.frame.width)
        super.init(frame: .zero)

        title = ""
        image = nil
        isBordered = false
        setButtonType(.momentaryChange)
        wantsLayer = true
        setAccessibilityLabel(label)

        iconView.image = NSImage(systemSymbolName: symbolName, accessibilityDescription: label)
        iconView.symbolConfiguration = NSImage.SymbolConfiguration(pointSize: style.iconSize, weight: .medium)
        iconView.imageScaling = .scaleProportionallyDown
        addSubview(iconView)

        addSubview(titleLabel)
    }

    required init?(coder: NSCoder) { nil }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func hitTest(_ point: NSPoint) -> NSView? {
        bounds.contains(convert(point, from: superview)) ? self : nil
    }

    var preferredWidth: CGFloat {
        max(
            style.minimumWidth,
            style.horizontalPadding * 2 + style.iconSize + style.contentSpacing + naturalLabelWidth
        )
    }

    var contentFrame: NSRect { iconView.frame.union(titleLabel.frame) }

    override func layout() {
        super.layout()
        let maximumLabelWidth = max(
            0,
            bounds.width - style.horizontalPadding * 2 - style.iconSize - style.contentSpacing
        )
        let labelWidth = min(naturalLabelWidth, maximumLabelWidth)
        let groupWidth = style.iconSize + style.contentSpacing + labelWidth
        let x = bounds.midX - groupWidth / 2
        iconView.frame = NSRect(
            x: x,
            y: bounds.midY - style.iconSize / 2,
            width: style.iconSize,
            height: style.iconSize
        )
        titleLabel.frame = NSRect(
            x: iconView.frame.maxX + style.contentSpacing,
            y: bounds.midY - ceil(titleLabel.intrinsicContentSize.height) / 2,
            width: labelWidth,
            height: ceil(titleLabel.intrinsicContentSize.height)
        )
    }

    func apply(selected: Bool, foreground: NSColor, accent: NSColor) {
        titleLabel.font = .systemFont(ofSize: style.fontSize, weight: selected ? .semibold : .medium)
        titleLabel.textColor = foreground
        iconView.contentTintColor = accent
        needsLayout = true
    }
}

private final class FlippedShelfView: NSView {
    override var isFlipped: Bool { true }
}
