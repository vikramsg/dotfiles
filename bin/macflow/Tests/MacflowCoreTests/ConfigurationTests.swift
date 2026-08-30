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
    }

    func testValidConfigurationPassesValidation() throws {
        XCTAssertNoThrow(try decode(validConfigurationJSON).validate())
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

    private func decode(_ json: String) throws -> WorkflowConfiguration {
        try JSONDecoder().decode(WorkflowConfiguration.self, from: Data(json.utf8))
    }
}
