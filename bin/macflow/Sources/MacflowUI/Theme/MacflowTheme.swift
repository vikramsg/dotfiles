import AppKit

public struct TabStyle {
    public let iconSize: CGFloat
    public let contentSpacing: CGFloat
    public let horizontalPadding: CGFloat
    public let height: CGFloat
    public let verticalPadding: CGFloat
    public let minimumWidth: CGFloat
    public let itemSpacing: CGFloat
    public let fontSize: CGFloat
}

public struct MacflowTheme {
    public let id: String
    public let appearance: NSAppearance?
    public let background: NSColor
    public let surface: NSColor
    public let raisedSurface: NSColor
    public let selectedSurface: NSColor
    public let border: NSColor
    public let focusedBorder: NSColor
    public let primaryText: NSColor
    public let secondaryText: NSColor
    public let mutedText: NSColor
    public let accent: NSColor
    public let cornerRadius: CGFloat
    public let controlCornerRadius: CGFloat
    public let tabs: TabStyle

    public var webValues: [String: Any] {
        [
            "background": background.cssValue,
            "surface": surface.cssValue,
            "raised-surface": raisedSurface.cssValue,
            "selected-surface": selectedSurface.cssValue,
            "border": border.cssValue,
            "focused-border": focusedBorder.cssValue,
            "primary-text": primaryText.cssValue,
            "secondary-text": secondaryText.cssValue,
            "muted-text": mutedText.cssValue,
            "accent": accent.cssValue,
            "corner-radius": "\(cornerRadius)px",
            "control-corner-radius": "\(controlCornerRadius)px",
        ]
    }
}

public enum ThemeResolutionError: LocalizedError, Equatable {
    case unknownTheme(String)

    public var errorDescription: String? {
        switch self {
        case let .unknownTheme(name): return "Unknown Macflow theme: \(name)"
        }
    }
}

public enum BuiltInThemeCatalog {
    public static let system = MacflowTheme(
        id: "system",
        appearance: nil,
        background: .windowBackgroundColor,
        surface: .controlBackgroundColor,
        raisedSurface: .underPageBackgroundColor,
        selectedSurface: .selectedControlColor,
        border: .separatorColor,
        focusedBorder: .keyboardFocusIndicatorColor,
        primaryText: .labelColor,
        secondaryText: .secondaryLabelColor,
        mutedText: .tertiaryLabelColor,
        accent: .controlAccentColor,
        cornerRadius: 14,
        controlCornerRadius: 8,
        tabs: TabStyle(
            iconSize: 13,
            contentSpacing: 6,
            horizontalPadding: 12,
            height: 30,
            verticalPadding: 6,
            minimumWidth: 132,
            itemSpacing: 8,
            fontSize: 12
        )
    )

    public static let tokyoNight = MacflowTheme(
        id: "tokyo-night",
        appearance: NSAppearance(named: .darkAqua),
        background: NSColor(hex: 0x1A1B26),
        surface: NSColor(hex: 0x24283B),
        raisedSurface: NSColor(hex: 0x292E42),
        selectedSurface: NSColor(hex: 0x33467C),
        border: NSColor(hex: 0x3B4261),
        focusedBorder: NSColor(hex: 0x7AA2F7),
        primaryText: NSColor(hex: 0xC0CAF5),
        secondaryText: NSColor(hex: 0xA9B1D6),
        mutedText: NSColor(hex: 0x565F89),
        accent: NSColor(hex: 0x7AA2F7),
        cornerRadius: 14,
        controlCornerRadius: 8,
        tabs: TabStyle(
            iconSize: 14,
            contentSpacing: 8,
            horizontalPadding: 16,
            height: 30,
            verticalPadding: 6,
            minimumWidth: 140,
            itemSpacing: 8,
            fontSize: 12
        )
    )

    public static func resolve(_ name: String) throws -> MacflowTheme {
        switch name {
        case system.id: system
        case tokyoNight.id: tokyoNight
        default: throw ThemeResolutionError.unknownTheme(name)
        }
    }
}

private extension NSColor {
    convenience init(hex: UInt32) {
        self.init(
            srgbRed: CGFloat((hex >> 16) & 0xff) / 255,
            green: CGFloat((hex >> 8) & 0xff) / 255,
            blue: CGFloat(hex & 0xff) / 255,
            alpha: 1
        )
    }

    var cssValue: String {
        guard let color = usingColorSpace(.sRGB) else { return "transparent" }
        return String(
            format: "rgba(%d, %d, %d, %.3f)",
            Int((color.redComponent * 255).rounded()),
            Int((color.greenComponent * 255).rounded()),
            Int((color.blueComponent * 255).rounded()),
            color.alphaComponent
        )
    }
}
