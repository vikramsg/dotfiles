import Foundation

public enum JSONValue: Codable, Equatable {
    case object([String: JSONValue])
    case array([JSONValue])
    case string(String)
    case number(Double)
    case boolean(Bool)
    case null

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .boolean(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else {
            self = .object(try container.decode([String: JSONValue].self))
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case let .object(value): try container.encode(value)
        case let .array(value): try container.encode(value)
        case let .string(value): try container.encode(value)
        case let .number(value): try container.encode(value)
        case let .boolean(value): try container.encode(value)
        case .null: try container.encodeNil()
        }
    }

    public var foundationObject: Any {
        switch self {
        case let .object(value): return value.mapValues(\.foundationObject)
        case let .array(value): return value.map(\.foundationObject)
        case let .string(value): return value
        case let .number(value): return value
        case let .boolean(value): return value
        case .null: return NSNull()
        }
    }
}

public struct WorkflowConfiguration: Codable, Equatable {
    public struct Appearance: Codable, Equatable {
        public let theme: String

        public init(theme: String = "system") {
            self.theme = theme
        }
    }

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

        public init(
            type: LayoutType,
            applications: [String],
            ratios: [Double]? = nil,
            targetScreenApplication: String? = nil,
            focus: String,
            gap: Double? = nil
        ) {
            self.type = type
            self.applications = applications
            self.ratios = ratios
            self.targetScreenApplication = targetScreenApplication
            self.focus = focus
            self.gap = gap
        }
    }

    public struct Action: Codable, Equatable {
        public let type: AutomationActionType
        public let layout: String?
    }

    public struct HotKey: Codable, Equatable {
        public let modifiers: [String]
        public let key: String
        public let scope: HotKeyScope
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

        public let directory: String
        public let extensions: [String]
        public let debounceSeconds: Double
        public let captureSettleSeconds: Double
        public let preview: Preview

        enum CodingKeys: String, CodingKey {
            case directory
            case extensions
            case debounceSeconds = "debounce_seconds"
            case captureSettleSeconds = "capture_settle_seconds"
            case preview
        }
    }

    public let server: Server
    public let appearance: Appearance
    public let applications: [String: Application]
    public let layouts: [String: Layout]
    public let hotkeys: [HotKey]
    public let screenshots: Screenshots

    enum CodingKeys: String, CodingKey {
        case server, appearance, applications, layouts, hotkeys, screenshots
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        server = try container.decode(Server.self, forKey: .server)
        appearance = try container.decodeIfPresent(Appearance.self, forKey: .appearance) ?? Appearance()
        applications = try container.decode([String: Application].self, forKey: .applications)
        layouts = try container.decode([String: Layout].self, forKey: .layouts)
        hotkeys = try container.decode([HotKey].self, forKey: .hotkeys)
        screenshots = try container.decode(Screenshots.self, forKey: .screenshots)
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(server, forKey: .server)
        try container.encode(appearance, forKey: .appearance)
        try container.encode(applications, forKey: .applications)
        try container.encode(layouts, forKey: .layouts)
        try container.encode(hotkeys, forKey: .hotkeys)
        try container.encode(screenshots, forKey: .screenshots)
    }

    public func validate() throws {
        guard ["127.0.0.1", "::1", "localhost"].contains(server.host.lowercased()) else {
            throw WorkflowValidationError.invalidServerHost(server.host)
        }
        guard !appearance.theme.isEmpty else {
            throw WorkflowValidationError.invalidTheme
        }
        for (name, layout) in layouts {
            let applicationsExist = !layout.applications.isEmpty
                && layout.applications.allSatisfy { applications[$0] != nil }
                && layout.applications.contains(layout.focus)
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

        var chords = Set<HotKeyChord>()
        for (index, hotkey) in hotkeys.enumerated() {
            let valid = hotkey.action.layout.map { layouts[$0] != nil } == true
            let modifiersAreValid = hotkey.modifiers.allSatisfy {
                KeyCodeResolver.supportedModifiers.contains($0.lowercased())
            }
            guard let chord = HotKeyChord(modifiers: hotkey.modifiers, key: hotkey.key),
                  modifiersAreValid,
                  valid
            else {
                throw WorkflowValidationError.invalidAction(index)
            }
            if !chords.insert(chord).inserted {
                throw WorkflowValidationError.duplicateHotKey(index)
            }
        }

        guard !screenshots.directory.isEmpty else {
            throw WorkflowValidationError.invalidScreenshotDirectory
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

    private static func decode<T: Decodable>(_ type: T.Type, from url: URL) throws -> T {
        try JSONDecoder().decode(type, from: Data(contentsOf: url))
    }
}
