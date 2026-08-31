import AppKit
import XCTest
@testable import MacflowUI

final class ThemeTests: XCTestCase {
    func testTokyoNightResolvesAsBuiltInDarkTheme() throws {
        let theme = try BuiltInThemeCatalog.resolve("tokyo-night")

        XCTAssertEqual(theme.id, "tokyo-night")
        XCTAssertEqual(theme.appearance?.name, .darkAqua)
        XCTAssertEqual(rgb(theme.background), 0x1A1B26)
        XCTAssertEqual(rgb(theme.accent), 0x7AA2F7)
        XCTAssertEqual(theme.tabs.contentSpacing, 8)
        XCTAssertEqual(theme.tabs.horizontalPadding, 16)
    }

    func testUnknownThemeIsRejected() {
        XCTAssertThrowsError(try BuiltInThemeCatalog.resolve("missing")) { error in
            XCTAssertEqual(error as? ThemeResolutionError, .unknownTheme("missing"))
        }
    }

    private func rgb(_ color: NSColor) -> UInt32? {
        guard let value = color.usingColorSpace(.sRGB) else { return nil }
        return UInt32(round(value.redComponent * 255)) << 16
            | UInt32(round(value.greenComponent * 255)) << 8
            | UInt32(round(value.blueComponent * 255))
    }
}
