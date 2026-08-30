import Foundation

public struct WorkflowConfiguration: Codable, Equatable {
    public struct Server: Codable, Equatable {
        public let host: String
        public let port: UInt16
    }

    public struct Application: Codable, Equatable {
        public let bundleID: String

        enum CodingKeys: String, CodingKey {
            case bundleID = "bundle_id"
        }
    }

    public struct Layout: Codable, Equatable {
        public let type: LayoutType
        public let applications: [String]
        public let ratios: [Double]?
        public let targetScreenApplication: String?
        public let focus: String
        public let gap: Double?

        enum CodingKeys: String, CodingKey {
            case type, applications, ratios, focus, gap
            case targetScreenApplication = "target_screen_application"
        }
    }

    public struct Shelf: Codable, Equatable {
        public let directoryFrom: String
        public let directoryKey: String
        public let extensions: [String]
        public let width: Double
        public let height: Double
        public let thumbnailWidth: Double
        public let spacing: Double
        public let margin: Double
        public let closeAfterDrag: Bool
        public let closeDelay: Double
        public let restoreFocus: Bool

        enum CodingKeys: String, CodingKey {
            case extensions, width, height, spacing, margin
            case directoryFrom = "directory_from"
            case directoryKey = "directory_key"
            case thumbnailWidth = "thumbnail_width"
            case closeAfterDrag = "close_after_drag"
            case closeDelay = "close_delay"
            case restoreFocus = "restore_focus"
        }

        public init(
            directoryFrom: String,
            directoryKey: String,
            extensions: [String],
            width: Double,
            height: Double,
            thumbnailWidth: Double,
            spacing: Double,
            margin: Double,
            closeAfterDrag: Bool,
            closeDelay: Double,
            restoreFocus: Bool
        ) {
            self.directoryFrom = directoryFrom
            self.directoryKey = directoryKey
            self.extensions = extensions
            self.width = width
            self.height = height
            self.thumbnailWidth = thumbnailWidth
            self.spacing = spacing
            self.margin = margin
            self.closeAfterDrag = closeAfterDrag
            self.closeDelay = closeDelay
            self.restoreFocus = restoreFocus
        }
    }

    public struct Action: Codable, Equatable {
        public let type: AutomationActionType
        public let layout: String?
        public let shelf: String?
    }

    public struct HotKey: Codable, Equatable {
        public let modifiers: [String]
        public let key: String
        public let action: Action
    }

    public struct Screenshots: Codable, Equatable {
        public struct Preview: Codable, Equatable {
            public let width: Double
            public let maxHeight: Double
            public let margin: Double
            public let timeoutSeconds: Double
            public let cornerRadius: Double

            enum CodingKeys: String, CodingKey {
                case width, margin
                case maxHeight = "max_height"
                case timeoutSeconds = "timeout_seconds"
                case cornerRadius = "corner_radius"
            }
        }

        public let configFile: String
        public let extensions: [String]
        public let debounceSeconds: Double
        public let captureSettleSeconds: Double
        public let preview: Preview

        enum CodingKeys: String, CodingKey {
            case configFile = "config_file"
            case extensions
            case debounceSeconds = "debounce_seconds"
            case captureSettleSeconds = "capture_settle_seconds"
            case preview
        }
    }

    public let server: Server
    public let applications: [String: Application]
    public let layouts: [String: Layout]
    public let shelves: [String: Shelf]
    public let hotkeys: [HotKey]
    public let screenshots: Screenshots

    public func validate() throws {
        guard ["127.0.0.1", "::1", "localhost"].contains(server.host.lowercased()) else {
            throw WorkflowValidationError.invalidServerHost(server.host)
        }
        for (name, layout) in layouts {
            let applicationsExist = !layout.applications.isEmpty
                && layout.applications.allSatisfy { applications[$0] != nil }
                && applications[layout.focus] != nil
                && layout.targetScreenApplication.map { applications[$0] != nil } != false
            let geometryIsValid: Bool
            switch layout.type {
            case .maximize:
                geometryIsValid = layout.applications.count == 1
            case .columns:
                geometryIsValid = layout.ratios?.count == layout.applications.count
                    && layout.ratios?.allSatisfy { $0 > 0 } == true
                    && (layout.gap ?? 0) >= 0
            }
            if !applicationsExist || !geometryIsValid {
                throw WorkflowValidationError.invalidLayout(name)
            }
        }

        for (index, hotkey) in hotkeys.enumerated() {
            let valid: Bool
            switch hotkey.action.type {
            case .applyLayout:
                valid = hotkey.action.layout.map { layouts[$0] != nil } == true
            case .showFileShelf:
                valid = hotkey.action.shelf.map { shelves[$0] != nil } == true
            }
            let modifiersAreValid = hotkey.modifiers.allSatisfy {
                KeyCodeResolver.supportedModifiers.contains($0.lowercased())
            }
            if KeyCodeResolver.resolve(hotkey.key) == nil || !modifiersAreValid || !valid {
                throw WorkflowValidationError.invalidAction(index)
            }
        }

        for (name, shelf) in shelves where shelf.extensions.isEmpty
            || shelf.width <= 0
            || shelf.height <= 0
            || shelf.thumbnailWidth <= 0
            || shelf.closeDelay < 0 {
            throw WorkflowValidationError.invalidShelf(name)
        }
    }
}

public struct ScreenshotConfiguration: Codable, Equatable {
    public let screenshotDirectory: String

    enum CodingKeys: String, CodingKey {
        case screenshotDirectory = "screenshot_dir"
    }
}

public enum ConfigurationError: LocalizedError {
    case missingString(String, URL)

    public var errorDescription: String? {
        switch self {
        case let .missingString(key, url): return "Missing string key \(key) in \(url.path)"
        }
    }
}

public enum ConfigurationLoader {
    public static func xdgConfigHome(environment: [String: String] = ProcessInfo.processInfo.environment) -> URL {
        if let configured = environment["XDG_CONFIG_HOME"], !configured.isEmpty {
            return URL(fileURLWithPath: configured, isDirectory: true)
        }
        let home = environment["HOME"] ?? FileManager.default.homeDirectoryForCurrentUser.path
        return URL(fileURLWithPath: home, isDirectory: true).appendingPathComponent(".config", isDirectory: true)
    }

    public static func workflowURL(environment: [String: String] = ProcessInfo.processInfo.environment) -> URL {
        xdgConfigHome(environment: environment)
            .appendingPathComponent("macflow", isDirectory: true)
            .appendingPathComponent("config.json")
    }

    public static func loadWorkflow(from url: URL? = nil) throws -> WorkflowConfiguration {
        try decode(WorkflowConfiguration.self, from: url ?? workflowURL())
    }

    public static func referencedURL(
        _ path: String,
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> URL {
        path.hasPrefix("/")
            ? URL(fileURLWithPath: path)
            : xdgConfigHome(environment: environment).appendingPathComponent(path)
    }

    public static func stringValue(
        configFile: String,
        key: String,
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) throws -> String {
        let url = referencedURL(configFile, environment: environment)
        let object = try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any]
        guard let value = object?[key] as? String else {
            throw ConfigurationError.missingString(key, url)
        }
        return value
    }

    public static func loadScreenshot(
        for configuration: WorkflowConfiguration,
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) throws -> ScreenshotConfiguration {
        try decode(
            ScreenshotConfiguration.self,
            from: referencedURL(configuration.screenshots.configFile, environment: environment)
        )
    }

    private static func decode<T: Decodable>(_ type: T.Type, from url: URL) throws -> T {
        try JSONDecoder().decode(type, from: Data(contentsOf: url))
    }
}
