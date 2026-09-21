import Foundation
import Testing
@testable import MacflowCore

@Suite struct ConfigurationTests {
    private var validConfigurationJSON: String {
        """
        {
          "server": {"host": "127.0.0.1", "port": 17421},
          "appearance": {"theme": "tokyo-night"},
          "applications": {"first": {"bundle_id": "example.first"}},
          "layouts": {
            "full": {
              "type": "maximize",
              "applications": ["first"],
              "focus": "first"
            }
          },
          "hotkeys": [
            {
              "modifiers": ["cmd", "shift"],
              "key": "g",
              "scope": "global",
              "action": {"type": "apply_layout", "layout": "full"}
            }
          ],
          "screenshots": {
            "directory": "/Users/Shared/Screenshots",
            "extensions": ["png"],
            "debounce_seconds": 0.2,
            "capture_settle_seconds": 0.15,
            "preview": {
              "width": 360,
              "max_height": 260,
              "margin": 24,
              "timeout_seconds": 8,
              "corner_radius": 12
            }
          }
        }
        """
    }

    @Test func testXDGPaths() {
        let environment = ["HOME": "/Users/test", "XDG_CONFIG_HOME": "/custom/config"]
        #expect(ConfigurationLoader.workflowURL(environment: environment).path == "/custom/config/macflow/config.json")
    }

    @Test func testConfigurationDecodesExpectedValues() throws {
        let configuration = try decode(validConfigurationJSON)
        #expect(configuration.applications["first"]?.bundleID == "example.first")
        #expect(configuration.server.host == "127.0.0.1")
        #expect(configuration.appearance.theme == "tokyo-night")
        #expect(configuration.screenshots.directory == "/Users/Shared/Screenshots")
        #expect(configuration.hotkeys.first?.action.layout == "full")
        #expect(configuration.hotkeys.first?.scope == .global)
    }

    @Test func testValidConfigurationPassesValidation() throws {
        try decode(validConfigurationJSON).validate()
    }

    @Test func testConfigurationDefaultsToSystemThemeWhenAppearanceIsOmitted() throws {
        let text = validConfigurationJSON.replacingOccurrences(
            of: "\"appearance\": {\"theme\": \"tokyo-night\"},",
            with: ""
        )
        #expect(try decode(text).appearance.theme == "system")
    }

    @Test func testConfigurationRejectsEmptyThemeName() throws {
        let text = validConfigurationJSON.replacingOccurrences(of: "\"tokyo-night\"", with: "\"\"")
        do {
            try decode(text).validate()
            Issue.record("Expected empty theme name to fail validation")
        } catch {
            #expect(error as? WorkflowValidationError == .invalidTheme)
        }
    }

    @Test func testConfigurationRejectsUnknownLayoutAction() throws {
        let text = validConfigurationJSON.replacingOccurrences(
            of: "\"layout\": \"full\"",
            with: "\"layout\": \"missing\""
        )
        do {
            try decode(text).validate()
            Issue.record("Expected unknown layout action to fail validation")
        } catch {
            #expect(error as? WorkflowValidationError == .invalidAction(0))
        }
    }

    @Test func testConfigurationRejectsFocusOutsideLayoutParticipants() throws {
        let text = validConfigurationJSON
            .replacingOccurrences(
                of: "\"applications\": {\"first\": {\"bundle_id\": \"example.first\"}}",
                with: "\"applications\": {\"first\": {\"bundle_id\": \"example.first\"}, \"other\": {\"bundle_id\": \"example.other\"}}"
            )
            .replacingOccurrences(of: "\"focus\": \"first\"", with: "\"focus\": \"other\"")
        do {
            try decode(text).validate()
            Issue.record("Expected out-of-layout focus to fail validation")
        } catch {
            #expect(error as? WorkflowValidationError == .invalidLayout("full"))
        }
    }

    @Test func testConfigurationRejectsNonLoopbackServer() throws {
        let text = validConfigurationJSON.replacingOccurrences(of: "\"127.0.0.1\"", with: "\"0.0.0.0\"")
        do {
            try decode(text).validate()
            Issue.record("Expected non-loopback server to fail validation")
        } catch {
            #expect(error as? WorkflowValidationError == .invalidServerHost("0.0.0.0"))
        }
    }

    @Test func testConfigurationRejectsUnsupportedKey() throws {
        let text = validConfigurationJSON.replacingOccurrences(of: "\"key\": \"g\"", with: "\"key\": \"invalid\"")
        do {
            try decode(text).validate()
            Issue.record("Expected unsupported key to fail validation")
        } catch {
            #expect(error as? WorkflowValidationError == .invalidAction(0))
        }
    }

    @Test func testConfigurationRejectsUnsupportedModifier() throws {
        let text = validConfigurationJSON.replacingOccurrences(
            of: "\"modifiers\": [\"cmd\", \"shift\"]",
            with: "\"modifiers\": [\"hyper\"]"
        )
        do {
            try decode(text).validate()
            Issue.record("Expected unsupported modifier to fail validation")
        } catch {
            #expect(error as? WorkflowValidationError == .invalidAction(0))
        }
    }

    @Test func testConfigurationRequiresSupportedHotKeyScope() {
        let missing = validConfigurationJSON.replacingOccurrences(of: "\"scope\": \"global\",", with: "")
        #expect(throws: Error.self) {
            try decode(missing)
        }

        let unsupported = validConfigurationJSON.replacingOccurrences(
            of: "\"scope\": \"global\"",
            with: "\"scope\": \"application\""
        )
        #expect(throws: Error.self) {
            try decode(unsupported)
        }
    }

    @Test func testConfigurationRejectsDuplicateGlobalShortcut() throws {
        let duplicate = validConfigurationJSON.replacingOccurrences(
            of: """
            {
                  "modifiers": ["cmd", "shift"],
                  "key": "g",
                  "scope": "global",
                  "action": {"type": "apply_layout", "layout": "full"}
                }
            """,
            with: """
            {
                  "modifiers": ["cmd", "shift"],
                  "key": "g",
                  "scope": "global",
                  "action": {"type": "apply_layout", "layout": "full"}
                },
                {
                  "modifiers": ["command", "shift"],
                  "key": "g",
                  "scope": "global",
                  "action": {"type": "apply_layout", "layout": "full"}
                }
            """
        )
        do {
            try decode(duplicate).validate()
            Issue.record("Expected duplicate global shortcut to fail validation")
        } catch {
            #expect(error as? WorkflowValidationError == .duplicateHotKey(1))
        }
    }

    private func decode(_ json: String) throws -> WorkflowConfiguration {
        try JSONDecoder().decode(WorkflowConfiguration.self, from: Data(json.utf8))
    }
}
