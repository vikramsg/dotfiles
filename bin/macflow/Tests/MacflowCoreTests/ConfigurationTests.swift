import Foundation
import XCTest
@testable import MacflowCore

final class ConfigurationTests: XCTestCase {
    private var validConfigurationJSON: String {
        """
        {
          "server": {"host": "127.0.0.1", "port": 17421},
          "applications": {"first": {"bundle_id": "example.first"}},
          "layouts": {
            "full": {
              "type": "maximize",
              "applications": ["first"],
              "focus": "first"
            }
          },
          "shelves": {
            "images": {
              "directory_from": "images/config.json",
              "directory_key": "directory",
              "extensions": ["png"],
              "width": 800,
              "height": 300,
              "thumbnail_width": 200,
              "spacing": 10,
              "margin": 20,
              "close_after_drag": true,
              "close_delay": 0.2,
              "restore_focus": true
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
            "config_file": "images/config.json",
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

    func testXDGPaths() {
        let environment = ["HOME": "/Users/test", "XDG_CONFIG_HOME": "/custom/config"]
        XCTAssertEqual(
            ConfigurationLoader.workflowURL(environment: environment).path,
            "/custom/config/macflow/config.json"
        )
    }

    func testConfigurationDecodesExpectedValues() throws {
        let configuration = try decode(validConfigurationJSON)
        XCTAssertEqual(configuration.applications["first"]?.bundleID, "example.first")
        XCTAssertEqual(configuration.server.host, "127.0.0.1")
        XCTAssertEqual(configuration.hotkeys.first?.action.layout, "full")
        XCTAssertEqual(configuration.hotkeys.first?.scope, .global)
    }

    func testValidConfigurationPassesValidation() throws {
        XCTAssertNoThrow(try decode(validConfigurationJSON).validate())
    }

    func testShelfDefaultsToFiveItemsWhenLimitIsOmitted() throws {
        let configuration = try decode(validConfigurationJSON)
        XCTAssertEqual(configuration.shelves["images"]?.maxItems, 5)
    }

    func testShelfUsesConfiguredItemLimit() throws {
        let text = validConfigurationJSON.replacingOccurrences(
            of: "\"extensions\": [\"png\"]",
            with: "\"extensions\": [\"png\"], \"max_items\": 3"
        )
        let configuration = try decode(text)
        XCTAssertEqual(configuration.shelves["images"]?.maxItems, 3)
    }

    func testConfigurationRejectsNonpositiveShelfItemLimit() throws {
        for limit in [0, -1] {
            let text = validConfigurationJSON.replacingOccurrences(
                of: "\"extensions\": [\"png\"]",
                with: "\"extensions\": [\"png\"], \"max_items\": \(limit)"
            )
            XCTAssertThrowsError(try decode(text).validate()) { error in
                XCTAssertEqual(error as? WorkflowValidationError, .invalidShelf("images"))
            }
        }
    }

    func testConfigurationRejectsUnknownLayoutAction() throws {
        let text = validConfigurationJSON.replacingOccurrences(
            of: "\"layout\": \"full\"",
            with: "\"layout\": \"missing\""
        )
        XCTAssertThrowsError(try decode(text).validate()) { error in
            XCTAssertEqual(error as? WorkflowValidationError, .invalidAction(0))
        }
    }

    func testConfigurationRejectsNonLoopbackServer() throws {
        let text = validConfigurationJSON.replacingOccurrences(of: "\"127.0.0.1\"", with: "\"0.0.0.0\"")
        XCTAssertThrowsError(try decode(text).validate()) { error in
            XCTAssertEqual(error as? WorkflowValidationError, .invalidServerHost("0.0.0.0"))
        }
    }

    func testConfigurationRejectsUnsupportedKey() throws {
        let text = validConfigurationJSON.replacingOccurrences(of: "\"key\": \"g\"", with: "\"key\": \"invalid\"")
        XCTAssertThrowsError(try decode(text).validate()) { error in
            XCTAssertEqual(error as? WorkflowValidationError, .invalidAction(0))
        }
    }

    func testConfigurationRejectsUnsupportedModifier() throws {
        let text = validConfigurationJSON.replacingOccurrences(
            of: "\"modifiers\": [\"cmd\", \"shift\"]",
            with: "\"modifiers\": [\"hyper\"]"
        )
        XCTAssertThrowsError(try decode(text).validate()) { error in
            XCTAssertEqual(error as? WorkflowValidationError, .invalidAction(0))
        }
    }

    func testConfigurationRequiresSupportedHotKeyScope() {
        let missing = validConfigurationJSON.replacingOccurrences(of: "\"scope\": \"global\",", with: "")
        XCTAssertThrowsError(try decode(missing))

        let unsupported = validConfigurationJSON.replacingOccurrences(
            of: "\"scope\": \"global\"",
            with: "\"scope\": \"application\""
        )
        XCTAssertThrowsError(try decode(unsupported))
    }

    func testConfigurationRejectsDuplicateGlobalShortcut() throws {
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
        XCTAssertThrowsError(try decode(duplicate).validate()) { error in
            XCTAssertEqual(error as? WorkflowValidationError, .duplicateHotKey(1))
        }
    }

    private func decode(_ json: String) throws -> WorkflowConfiguration {
        try JSONDecoder().decode(WorkflowConfiguration.self, from: Data(json.utf8))
    }
}
