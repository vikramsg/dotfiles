import Foundation

public struct A2UIComponent: Equatable {
    public let id: String
    public let type: String
    public let properties: [String: JSONValue]

    public init(id: String, type: String, properties: [String: JSONValue] = [:]) {
        self.id = id
        self.type = type
        self.properties = properties
    }
}

public struct A2UIDataModel: Equatable {
    public private(set) var root: JSONValue

    public init(root: JSONValue = .object([:])) {
        self.root = root
    }

    public mutating func set(path: String, value: JSONValue) {
        let tokens = A2UIPath.tokens(path)
        guard !tokens.isEmpty else {
            root = value
            return
        }
        root = A2UIPath.set(root, tokens: tokens, value: value)
    }

    public func value(at path: String, scope: JSONValue? = nil) -> JSONValue? {
        let tokens = A2UIPath.tokens(path)
        if path.hasPrefix("/") || scope == nil {
            return A2UIPath.get(root, tokens: tokens)
        }
        return A2UIPath.get(scope ?? root, tokens: tokens)
    }
}

public enum A2UIPath {
    public static func tokens(_ path: String) -> [String] {
        guard !path.isEmpty, path != "/" else { return [] }
        return path.split(separator: "/", omittingEmptySubsequences: true).map { token in
            String(token)
                .replacingOccurrences(of: "~1", with: "/")
                .replacingOccurrences(of: "~0", with: "~")
        }
    }

    public static func get(_ node: JSONValue, tokens: [String]) -> JSONValue? {
        guard let token = tokens.first else { return node }
        let rest = Array(tokens.dropFirst())
        switch node {
        case let .object(values):
            guard let child = values[token] else { return nil }
            return get(child, tokens: rest)
        case let .array(items):
            guard let index = Int(token), items.indices.contains(index) else { return nil }
            return get(items[index], tokens: rest)
        default:
            return nil
        }
    }

    public static func set(_ node: JSONValue, tokens: [String], value: JSONValue) -> JSONValue {
        guard let token = tokens.first else { return value }
        let rest = Array(tokens.dropFirst())
        switch node {
        case .object(var values):
            let child = values[token] ?? .object([:])
            values[token] = set(child, tokens: rest, value: value)
            return .object(values)
        case .array(var items):
            guard let index = Int(token) else { return node }
            while items.count <= index { items.append(.null) }
            items[index] = set(items[index], tokens: rest, value: value)
            return .array(items)
        default:
            return Int(token) == nil ? set(.object([:]), tokens: tokens, value: value) : node
        }
    }
}
