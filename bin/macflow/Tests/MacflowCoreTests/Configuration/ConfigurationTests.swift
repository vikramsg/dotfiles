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
          "shelves": {
            "images": {
              "sources": [
                {
                  "id": "local",
                  "label": "Local",
                  "icon": "folder",
                  "directory": "/Users/Shared/Screenshots"
                }
              ],
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
        #expect(configuration.shelves["images"]?.sources.first?.directory == "/Users/Shared/Screenshots")
        #expect(configuration.screenshots.directory == "/Users/Shared/Screenshots")
        #expect(configuration.hotkeys.first?.action.layout == "full")
        #expect(configuration.hotkeys.first?.scope == .global)
    }

    @Test func testValidConfigurationPassesValidation() throws {
        try decode(validConfigurationJSON).validate()
    }

    @Test func testSurfaceConfigurationIsOpaqueAndShowActionResolvesIt() throws {
        var object = try #require(
            JSONSerialization.jsonObject(with: Data(validConfigurationJSON.utf8)) as? [String: Any]
        )
        object["surfaces"] = [
            "example": [
                "document": "ui/example/index.html",
                "width": 640,
                "height": 320,
                "margin": 12,
                "activates": true,
                "close_after_drag": false,
                "close_delay": 0.2,
                "restore_focus": true,
                "configuration": ["domain_value": "unchanged"],
            ],
        ]
        object["hotkeys"] = [[
            "modifiers": ["cmd", "shift"],
            "key": "j",
            "scope": "global",
            "action": ["type": "show_surface", "surface": "example"],
        ]]

        let configuration = try JSONDecoder().decode(
            WorkflowConfiguration.self,
            from: JSONSerialization.data(withJSONObject: object)
        )

        try configuration.validate()
        #expect(configuration.surfaces["example"]?.document == "ui/example/index.html")
        #expect(configuration.surfaces["example"]?.configuration["domain_value"] == .string("unchanged"))
        #expect(configuration.hotkeys.first?.action.surface == "example")
    }

    @Test func testConfigurationRejectsUnsafeSurfaceDocument() throws {
        for document in ["/tmp/index.html", "../index.html"] {
            var object = try #require(
                JSONSerialization.jsonObject(with: Data(validConfigurationJSON.utf8)) as? [String: Any]
            )
            object["surfaces"] = [
                "unsafe": [
                    "document": document,
                    "width": 640,
                    "height": 320,
                    "margin": 12,
                    "activates": false,
                    "close_after_drag": false,
                    "close_delay": 0,
                    "restore_focus": true,
                    "configuration": [:],
                ],
            ]
            let configuration = try JSONDecoder().decode(
                WorkflowConfiguration.self,
                from: JSONSerialization.data(withJSONObject: object)
            )
            do {
                try configuration.validate()
                Issue.record("Expected unsafe surface document to fail validation")
            } catch {
                #expect(error as? WorkflowValidationError == .invalidSurface("unsafe"))
            }
        }
    }

    @Test func testConfigurationRejectsUnknownSurfaceAction() throws {
        var object = try #require(
            JSONSerialization.jsonObject(with: Data(validConfigurationJSON.utf8)) as? [String: Any]
        )
        object["hotkeys"] = [[
            "modifiers": ["cmd", "shift"],
            "key": "j",
            "scope": "global",
            "action": ["type": "show_surface", "surface": "missing"],
        ]]
        let configuration = try JSONDecoder().decode(
            WorkflowConfiguration.self,
            from: JSONSerialization.data(withJSONObject: object)
        )

        do {
            try configuration.validate()
            Issue.record("Expected unknown surface action to fail validation")
        } catch {
            #expect(error as? WorkflowValidationError == .invalidAction(0))
        }
    }

    @Test func testShelfDefaultsToFiveItemsWhenLimitIsOmitted() throws {
        let configuration = try decode(validConfigurationJSON)
        #expect(configuration.shelves["images"]?.maxItems == 5)
    }

    @Test func testShelfUsesConfiguredItemLimit() throws {
        let text = validConfigurationJSON.replacingOccurrences(
            of: "\"extensions\": [\"png\"]",
            with: "\"extensions\": [\"png\"], \"max_items\": 3"
        )
        let configuration = try decode(text)
        #expect(configuration.shelves["images"]?.maxItems == 3)
    }

    @Test func testConfigurationRejectsNonpositiveShelfItemLimit() throws {
        for limit in [0, -1] {
            let text = validConfigurationJSON.replacingOccurrences(
                of: "\"extensions\": [\"png\"]",
                with: "\"extensions\": [\"png\"], \"max_items\": \(limit)"
            )
            do {
                try decode(text).validate()
                Issue.record("Expected nonpositive shelf item limit to fail validation")
            } catch {
                #expect(error as? WorkflowValidationError == .invalidShelf("images"))
            }
        }
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

    @Test func testConfigurationRejectsDuplicateShelfSourceIdentifiers() throws {
        var object = try #require(
            JSONSerialization.jsonObject(with: Data(validConfigurationJSON.utf8)) as? [String: Any]
        )
        var shelves = try #require(object["shelves"] as? [String: Any])
        var images = try #require(shelves["images"] as? [String: Any])
        var sources = try #require(images["sources"] as? [[String: Any]])
        sources.append(sources[0])
        images["sources"] = sources
        shelves["images"] = images
        object["shelves"] = shelves
        let data = try JSONSerialization.data(withJSONObject: object)

        do {
            try JSONDecoder().decode(WorkflowConfiguration.self, from: data).validate()
            Issue.record("Expected duplicate shelf source identifiers to fail validation")
        } catch {
            #expect(error as? WorkflowValidationError == .invalidShelf("images"))
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
