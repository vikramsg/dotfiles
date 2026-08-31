import AppKit
import Testing
@testable import MacflowUI

@Suite(.serialized)
@MainActor
struct ThemeTests {
    @Test
    func tokyoNightResolvesAsBuiltInDarkTheme() throws {
        let theme = try BuiltInThemeCatalog.resolve("tokyo-night")

        #expect(theme.id == "tokyo-night")
        #expect(theme.appearance?.name == .darkAqua)
        #expect(rgb(theme.background) == 0x1A1B26)
        #expect(rgb(theme.accent) == 0x7AA2F7)
        #expect(theme.tabs.contentSpacing == 8)
        #expect(theme.tabs.horizontalPadding == 16)
    }

    @Test
    func unknownThemeIsRejected() {
        do {
            _ = try BuiltInThemeCatalog.resolve("missing")
            Issue.record("Resolving an unknown theme should throw")
        } catch {
            #expect(error as? ThemeResolutionError == .unknownTheme("missing"))
        }
    }

    private func rgb(_ color: NSColor) -> UInt32? {
        guard let value = color.usingColorSpace(.sRGB) else { return nil }
        return UInt32(round(value.redComponent * 255)) << 16
            | UInt32(round(value.greenComponent * 255)) << 8
            | UInt32(round(value.blueComponent * 255))
    }

    @Test
    func tokyoNightExportsSemanticWebValues() throws {
        let values = try BuiltInThemeCatalog.resolve("tokyo-night").webValues

        #expect(values["corner-radius"] as? String == "14.0px")
        #expect(values["accent"] as? String == "rgba(122, 162, 247, 1.000)")
        #expect(values["primary-text"] != nil)
        #expect(values["raised-surface"] != nil)
    }
}
