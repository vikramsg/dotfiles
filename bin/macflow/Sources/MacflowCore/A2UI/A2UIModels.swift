import Foundation

public enum A2UIError: LocalizedError, Equatable {
    case invalidPayload(String)
    case unknownComponent(String)
    case unknownFunction(String)
    case invalidProperty(String)

    public var errorDescription: String? {
        switch self {
        case let .invalidPayload(message): return "Invalid A2UI payload: \(message)"
        case let .unknownComponent(type): return "Unknown A2UI component: \(type)"
        case let .unknownFunction(name): return "Unknown A2UI function: \(name)"
        case let .invalidProperty(message): return "Invalid A2UI property: \(message)"
        }
    }
}

extension JSONValue {
    public init(any: Any) throws {
        switch any {
        case is NSNull:
            self = .null
        case let value as String:
            self = .string(value)
        case let value as NSNumber:
            if CFGetTypeID(value) == CFBooleanGetTypeID() {
                self = .boolean(value.boolValue)
            } else {
                self = .number(value.doubleValue)
            }
        case let value as [Any]:
            self = .array(try value.map { try JSONValue(any: $0) })
        case let value as [String: Any]:
            self = .object(try value.mapValues { try JSONValue(any: $0) })
        default:
            throw A2UIError.invalidPayload("Unsupported JSON value: \(any)")
        }
    }

    public var stringValue: String? {
        if case let .string(value) = self { return value }
        return nil
    }

    public var numberValue: Double? {
        if case let .number(value) = self { return value }
        return nil
    }

    public var boolValue: Bool? {
        if case let .boolean(value) = self { return value }
        return nil
    }

    public var arrayValue: [JSONValue]? {
        if case let .array(value) = self { return value }
        return nil
    }

    public var objectValue: [String: JSONValue]? {
        if case let .object(value) = self { return value }
        return nil
    }
}

public struct A2UISurfaceProperties: Equatable {
    public var width: Double
    public var height: Double
    public var margin: Double
    public var activates: Bool

    public static let `default` = A2UISurfaceProperties(
        width: 1255,
        height: 250,
        margin: 12,
        activates: false
    )

    public init(width: Double, height: Double, margin: Double, activates: Bool) {
        self.width = width
        self.height = height
        self.margin = margin
        self.activates = activates
    }
}

public enum A2UIMessage: Equatable {
    case createSurface(surfaceId: String, catalogId: String, properties: A2UISurfaceProperties)
    case updateComponents(surfaceId: String, components: [A2UIComponent])
    case updateDataModel(surfaceId: String, path: String, value: JSONValue)
    case deleteSurface(surfaceId: String)

    public var surfaceId: String {
        switch self {
        case let .createSurface(id, _, _): return id
        case let .updateComponents(id, _): return id
        case let .updateDataModel(id, _, _): return id
        case let .deleteSurface(id): return id
        }
    }
}

public enum A2UIMessageDecoder {
    public static func decode(_ data: Data) throws -> [A2UIMessage] {
        let object: Any
        do {
            object = try JSONSerialization.jsonObject(with: data)
        } catch {
            throw A2UIError.invalidPayload("Body is not valid JSON")
        }
        let dictionaries: [[String: Any]]
        if let array = object as? [Any] {
            dictionaries = try array.map {
                guard let dictionary = $0 as? [String: Any] else {
                    throw A2UIError.invalidPayload("Each message must be a JSON object")
                }
                return dictionary
            }
        } else if let dictionary = object as? [String: Any] {
            dictionaries = [dictionary]
        } else {
            throw A2UIError.invalidPayload("Expected a message object or an array of messages")
        }
        return try dictionaries.map(decodeMessage)
    }

    private static func decodeMessage(_ dictionary: [String: Any]) throws -> A2UIMessage {
        guard let version = dictionary["version"] as? String, version == "v0.9.1" else {
            throw A2UIError.invalidPayload("Only A2UI version v0.9.1 is supported")
        }
        let keys = ["createSurface", "updateComponents", "updateDataModel", "deleteSurface"]
            .filter { dictionary[$0] != nil }
        guard keys.count == 1, let key = keys.first,
              let body = dictionary[key] as? [String: Any]
        else {
            throw A2UIError.invalidPayload("Each message must contain exactly one A2UI message type")
        }
        switch key {
        case "createSurface":
            return .createSurface(
                surfaceId: try surfaceId(body),
                catalogId: body["catalogId"] as? String ?? A2UICatalog.defaultCatalogId,
                properties: properties(body["surface"] as? [String: Any])
            )
        case "updateComponents":
            guard let raw = body["components"] as? [Any] else {
                throw A2UIError.invalidPayload("updateComponents requires components")
            }
            let components = try raw.map { item -> A2UIComponent in
                guard let component = item as? [String: Any],
                      let id = component["id"] as? String,
                      let type = component["component"] as? String
                else {
                    throw A2UIError.invalidPayload("Each component requires id and component")
                }
                var properties: [String: JSONValue] = [:]
                for (name, value) in component where name != "id" && name != "component" {
                    properties[name] = try JSONValue(any: value)
                }
                return A2UIComponent(id: id, type: type, properties: properties)
            }
            return .updateComponents(surfaceId: try surfaceId(body), components: components)
        case "updateDataModel":
            guard let value = body["value"] else {
                throw A2UIError.invalidPayload("updateDataModel requires value")
            }
            return .updateDataModel(
                surfaceId: try surfaceId(body),
                path: body["path"] as? String ?? "/",
                value: try JSONValue(any: value)
            )
        default:
            return .deleteSurface(surfaceId: try surfaceId(body))
        }
    }

    private static func surfaceId(_ body: [String: Any]) throws -> String {
        guard let id = body["surfaceId"] as? String, !id.isEmpty else {
            throw A2UIError.invalidPayload("surfaceId is required")
        }
        return id
    }

    private static func properties(_ object: [String: Any]?) -> A2UISurfaceProperties {
        guard let object else { return .default }
        return A2UISurfaceProperties(
            width: (object["width"] as? NSNumber)?.doubleValue ?? A2UISurfaceProperties.default.width,
            height: (object["height"] as? NSNumber)?.doubleValue ?? A2UISurfaceProperties.default.height,
            margin: (object["margin"] as? NSNumber)?.doubleValue ?? A2UISurfaceProperties.default.margin,
            activates: object["activates"] as? Bool ?? A2UISurfaceProperties.default.activates
        )
    }
}

public enum A2UICatalog {
    public static let defaultCatalogId = "macflow/v1"

    public static let componentTypes: Set<String> = [
        "Text", "Image", "Row", "Column", "List", "Card", "Tabs", "Divider",
        "Button", "FileThumbnail",
    ]

    public static let functions: Set<String> = [
        "openUrl", "files.open", "files.reveal", "surface.dismiss",
    ]

    public static func validate(_ component: A2UIComponent) throws {
        guard componentTypes.contains(component.type) else {
            throw A2UIError.unknownComponent(component.type)
        }
        guard let action = component.properties["action"] else { return }
        guard component.type == "Button" else {
            throw A2UIError.invalidProperty("\(component.type) does not support action")
        }
        if case let .object(container) = action,
           case let .object(call)? = container["functionCall"],
           let name = call["call"]?.stringValue,
           !functions.contains(name)
        {
            throw A2UIError.unknownFunction(name)
        }
    }
}
