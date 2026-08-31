import AppKit
import MacflowCore
import Testing
@testable import MacflowUI

@Suite(.serialized)
@MainActor
struct FileShelfPanelTests {
    @Test
    func shelfShowsConfiguredTabsAndSelectsTheRequestedSource() throws {
        var selectedSource: String?
        let panel = FileShelfPanel(
            contentRect: NSRect(x: 0, y: 0, width: 800, height: 180),
            configuration: shelfConfiguration,
            theme: try BuiltInThemeCatalog.resolve("tokyo-night"),
            onSelectSource: { selectedSource = $0 },
            onCompletedDrag: {}
        )
        defer { panel.close() }

        #expect(panel.selectedSourceID == "local")
        let buttons = descendants(of: try #require(panel.contentView)).compactMap { $0 as? ShelfTabButton }
        #expect(Set(buttons.map(\.sourceLabel)) == ["Local VM", "Remote VM"])

        try #require(buttons.first { $0.sourceLabel == "Remote VM" }).performClick(nil)
        #expect(panel.selectedSourceID == "remote")
        #expect(selectedSource == "remote")
    }

    @Test
    func emptySelectedSourcePresentsAnEmptyState() throws {
        let panel = FileShelfPanel(
            contentRect: NSRect(x: 0, y: 0, width: 800, height: 180),
            configuration: shelfConfiguration,
            theme: try BuiltInThemeCatalog.resolve("tokyo-night"),
            onSelectSource: { _ in },
            onCompletedDrag: {}
        )
        defer { panel.close() }

        panel.display(items: [], for: "local")

        let labels = descendants(of: try #require(panel.contentView)).compactMap { $0 as? NSTextField }
        #expect(labels.contains { $0.stringValue == "No files available" })
    }

    @Test
    func tokyoNightColorsTheShelfRoot() throws {
        let theme = try BuiltInThemeCatalog.resolve("tokyo-night")
        let panel = FileShelfPanel(
            contentRect: NSRect(x: 0, y: 0, width: 800, height: 180),
            configuration: shelfConfiguration,
            theme: theme,
            onSelectSource: { _ in },
            onCompletedDrag: {}
        )
        defer { panel.close() }

        #expect(panel.appearance?.name == .darkAqua)
        #expect(panel.contentView?.layer?.backgroundColor == theme.background.withAlphaComponent(0.98).cgColor)
    }

    @Test
    func unavailableSelectedSourcePresentsItsFailure() throws {
        let panel = FileShelfPanel(
            contentRect: NSRect(x: 0, y: 0, width: 800, height: 180),
            configuration: shelfConfiguration,
            theme: try BuiltInThemeCatalog.resolve("tokyo-night"),
            onSelectSource: { _ in },
            onCompletedDrag: {}
        )
        defer { panel.close() }

        panel.display(message: "Directory unavailable", for: "local")

        let labels = descendants(of: try #require(panel.contentView)).compactMap { $0 as? NSTextField }
        #expect(labels.contains { $0.stringValue == "Directory unavailable" })
    }

    @Test
    func tabCentersContentAndUsesTokyoNightMetrics() throws {
        let theme = try BuiltInThemeCatalog.resolve("tokyo-night")
        let button = ShelfTabButton(
            sourceID: "local",
            label: "Local VM",
            symbolName: "desktopcomputer",
            style: theme.tabs
        )
        button.frame = NSRect(x: 0, y: 0, width: button.preferredWidth, height: theme.tabs.height)
        button.layoutSubtreeIfNeeded()

        #expect(abs(button.iconView.frame.width - theme.tabs.iconSize) <= 0.01)
        #expect(abs(button.titleLabel.frame.minX - button.iconView.frame.maxX - theme.tabs.contentSpacing) <= 0.01)
        #expect(abs(button.contentFrame.midX - button.bounds.midX) <= 0.01)
        #expect(button.contentFrame.minX >= theme.tabs.horizontalPadding)
        #expect(button.bounds.maxX - button.contentFrame.maxX >= theme.tabs.horizontalPadding)
        #expect(abs(button.titleLabel.frame.width - button.naturalLabelWidth) <= 0.01)
        #expect(button.titleLabel.cell?.expansionFrame(withFrame: button.titleLabel.bounds, in: button.titleLabel) == .zero)
    }

    @Test
    func tabGeometryChangesWithThemeMetricsInsteadOfEmbeddedSpacing() throws {
        let system = try BuiltInThemeCatalog.resolve("system")
        let tokyoNight = try BuiltInThemeCatalog.resolve("tokyo-night")
        let systemButton = laidOutButton(style: system.tabs)
        let tokyoNightButton = laidOutButton(style: tokyoNight.tabs)

        #expect(abs(systemButton.titleLabel.frame.minX - systemButton.iconView.frame.maxX - system.tabs.contentSpacing) <= 0.01)
        #expect(abs(tokyoNightButton.titleLabel.frame.minX - tokyoNightButton.iconView.frame.maxX - tokyoNight.tabs.contentSpacing) <= 0.01)
        #expect(system.tabs.contentSpacing != tokyoNight.tabs.contentSpacing)
        #expect(systemButton.iconView.frame.width != tokyoNightButton.iconView.frame.width)
    }

    @Test
    func selectingTabDoesNotShiftItsContent() throws {
        let theme = try BuiltInThemeCatalog.resolve("tokyo-night")
        let button = laidOutButton(style: theme.tabs)
        button.apply(selected: false, foreground: theme.secondaryText, accent: theme.secondaryText)
        button.layoutSubtreeIfNeeded()
        let unselectedFrame = button.contentFrame

        button.apply(selected: true, foreground: theme.primaryText, accent: theme.accent)
        button.layoutSubtreeIfNeeded()

        #expect(button.contentFrame == unselectedFrame)
    }

    private var shelfConfiguration: WorkflowConfiguration.Shelf {
        WorkflowConfiguration.Shelf(
            sources: [
                .init(id: "local", label: "Local VM", icon: "desktopcomputer", directory: "/local"),
                .init(id: "remote", label: "Remote VM", icon: "network", directory: "/remote"),
            ],
            extensions: ["png"],
            width: 800,
            height: 180,
            thumbnailWidth: 200,
            spacing: 8,
            margin: 12,
            closeAfterDrag: true,
            closeDelay: 0.2,
            restoreFocus: true
        )
    }

    private func descendants(of view: NSView) -> [NSView] {
        view.subviews + view.subviews.flatMap(descendants)
    }

    private func laidOutButton(style: TabStyle) -> ShelfTabButton {
        let button = ShelfTabButton(
            sourceID: "local",
            label: "Local VM",
            symbolName: "desktopcomputer",
            style: style
        )
        button.frame = NSRect(x: 0, y: 0, width: button.preferredWidth, height: style.height)
        button.layoutSubtreeIfNeeded()
        return button
    }
}
