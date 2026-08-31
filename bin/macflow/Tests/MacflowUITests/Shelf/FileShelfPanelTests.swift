import AppKit
import MacflowCore
import XCTest
@testable import MacflowUI

final class FileShelfPanelTests: XCTestCase {
    func testShelfShowsConfiguredTabsAndSelectsTheRequestedSource() throws {
        var selectedSource: String?
        let panel = FileShelfPanel(
            contentRect: NSRect(x: 0, y: 0, width: 800, height: 180),
            configuration: shelfConfiguration,
            theme: try BuiltInThemeCatalog.resolve("tokyo-night"),
            onSelectSource: { selectedSource = $0 },
            onCompletedDrag: {}
        )

        XCTAssertEqual(panel.selectedSourceID, "local")
        let buttons = descendants(of: try XCTUnwrap(panel.contentView)).compactMap { $0 as? ShelfTabButton }
        XCTAssertEqual(Set(buttons.map(\.sourceLabel)), ["Local VM", "Remote VM"])

        try XCTUnwrap(buttons.first { $0.sourceLabel == "Remote VM" }).performClick(nil)
        XCTAssertEqual(panel.selectedSourceID, "remote")
        XCTAssertEqual(selectedSource, "remote")
    }

    func testEmptySelectedSourcePresentsAnEmptyState() throws {
        let panel = FileShelfPanel(
            contentRect: NSRect(x: 0, y: 0, width: 800, height: 180),
            configuration: shelfConfiguration,
            theme: try BuiltInThemeCatalog.resolve("tokyo-night"),
            onSelectSource: { _ in },
            onCompletedDrag: {}
        )

        panel.display(items: [], for: "local")

        let labels = descendants(of: try XCTUnwrap(panel.contentView)).compactMap { $0 as? NSTextField }
        XCTAssertTrue(labels.contains { $0.stringValue == "No files available" })
    }

    func testTokyoNightColorsTheShelfRoot() throws {
        let theme = try BuiltInThemeCatalog.resolve("tokyo-night")
        let panel = FileShelfPanel(
            contentRect: NSRect(x: 0, y: 0, width: 800, height: 180),
            configuration: shelfConfiguration,
            theme: theme,
            onSelectSource: { _ in },
            onCompletedDrag: {}
        )

        XCTAssertEqual(panel.appearance?.name, .darkAqua)
        XCTAssertEqual(panel.contentView?.layer?.backgroundColor, theme.background.withAlphaComponent(0.98).cgColor)
    }

    func testUnavailableSelectedSourcePresentsItsFailure() throws {
        let panel = FileShelfPanel(
            contentRect: NSRect(x: 0, y: 0, width: 800, height: 180),
            configuration: shelfConfiguration,
            theme: try BuiltInThemeCatalog.resolve("tokyo-night"),
            onSelectSource: { _ in },
            onCompletedDrag: {}
        )

        panel.display(message: "Directory unavailable", for: "local")

        let labels = descendants(of: try XCTUnwrap(panel.contentView)).compactMap { $0 as? NSTextField }
        XCTAssertTrue(labels.contains { $0.stringValue == "Directory unavailable" })
    }

    func testTabCentersContentAndUsesTokyoNightMetrics() throws {
        let theme = try BuiltInThemeCatalog.resolve("tokyo-night")
        let button = ShelfTabButton(
            sourceID: "local",
            label: "Local VM",
            symbolName: "desktopcomputer",
            style: theme.tabs
        )
        button.frame = NSRect(x: 0, y: 0, width: button.preferredWidth, height: theme.tabs.height)
        button.layoutSubtreeIfNeeded()

        XCTAssertEqual(button.iconView.frame.width, theme.tabs.iconSize, accuracy: 0.01)
        XCTAssertEqual(button.titleLabel.frame.minX - button.iconView.frame.maxX, theme.tabs.contentSpacing, accuracy: 0.01)
        XCTAssertEqual(button.contentFrame.midX, button.bounds.midX, accuracy: 0.01)
        XCTAssertGreaterThanOrEqual(button.contentFrame.minX, theme.tabs.horizontalPadding)
        XCTAssertGreaterThanOrEqual(button.bounds.maxX - button.contentFrame.maxX, theme.tabs.horizontalPadding)
        XCTAssertEqual(button.titleLabel.frame.width, button.naturalLabelWidth, accuracy: 0.01)
        XCTAssertEqual(
            button.titleLabel.cell?.expansionFrame(withFrame: button.titleLabel.bounds, in: button.titleLabel),
            .zero
        )
    }

    func testTabGeometryChangesWithThemeMetricsInsteadOfEmbeddedSpacing() throws {
        let system = try BuiltInThemeCatalog.resolve("system")
        let tokyoNight = try BuiltInThemeCatalog.resolve("tokyo-night")
        let systemButton = laidOutButton(style: system.tabs)
        let tokyoNightButton = laidOutButton(style: tokyoNight.tabs)

        XCTAssertEqual(
            systemButton.titleLabel.frame.minX - systemButton.iconView.frame.maxX,
            system.tabs.contentSpacing,
            accuracy: 0.01
        )
        XCTAssertEqual(
            tokyoNightButton.titleLabel.frame.minX - tokyoNightButton.iconView.frame.maxX,
            tokyoNight.tabs.contentSpacing,
            accuracy: 0.01
        )
        XCTAssertNotEqual(system.tabs.contentSpacing, tokyoNight.tabs.contentSpacing)
        XCTAssertNotEqual(systemButton.iconView.frame.width, tokyoNightButton.iconView.frame.width)
    }

    func testSelectingTabDoesNotShiftItsContent() throws {
        let theme = try BuiltInThemeCatalog.resolve("tokyo-night")
        let button = laidOutButton(style: theme.tabs)
        button.apply(selected: false, foreground: theme.secondaryText, accent: theme.secondaryText)
        button.layoutSubtreeIfNeeded()
        let unselectedFrame = button.contentFrame

        button.apply(selected: true, foreground: theme.primaryText, accent: theme.accent)
        button.layoutSubtreeIfNeeded()

        XCTAssertEqual(button.contentFrame, unselectedFrame)
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
