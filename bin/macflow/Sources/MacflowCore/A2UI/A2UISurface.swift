import Foundation

public struct A2UISurface: Equatable {
    public let id: String
    public let catalogId: String
    public let properties: A2UISurfaceProperties
    public private(set) var components: [String: A2UIComponent]
    public private(set) var dataModel: A2UIDataModel

    public init(
        id: String,
        catalogId: String = A2UICatalog.defaultCatalogId,
        properties: A2UISurfaceProperties = .default,
        components: [String: A2UIComponent] = [:],
        dataModel: A2UIDataModel = A2UIDataModel()
    ) {
        self.id = id
        self.catalogId = catalogId
        self.properties = properties
        self.components = components
        self.dataModel = dataModel
    }

    public mutating func upsert(components newComponents: [A2UIComponent]) {
        for component in newComponents {
            components[component.id] = component
        }
    }

    public mutating func setDataModel(path: String, value: JSONValue) {
        dataModel.set(path: path, value: value)
    }
}

public struct A2UISurfaceStore {
    public private(set) var surfaces: [String: A2UISurface]

    public init(surfaces: [String: A2UISurface] = [:]) {
        self.surfaces = surfaces
    }

    public var ids: [String] { surfaces.keys.sorted() }

    public func surface(id: String) -> A2UISurface? { surfaces[id] }

    public mutating func remove(id: String) {
        surfaces.removeValue(forKey: id)
    }

    @discardableResult
    public mutating func apply(_ messages: [A2UIMessage]) throws -> [String] {
        var touched: [String] = []
        for message in messages {
            switch message {
            case let .createSurface(id, catalogId, properties):
                surfaces[id] = A2UISurface(id: id, catalogId: catalogId, properties: properties)
            case let .updateComponents(id, components):
                try components.forEach(A2UICatalog.validate)
                if surfaces[id] == nil { surfaces[id] = A2UISurface(id: id) }
                surfaces[id]?.upsert(components: components)
            case let .updateDataModel(id, path, value):
                if surfaces[id] == nil { surfaces[id] = A2UISurface(id: id) }
                surfaces[id]?.setDataModel(path: path, value: value)
            case let .deleteSurface(id):
                surfaces.removeValue(forKey: id)
            }
            if !touched.contains(message.surfaceId) { touched.append(message.surfaceId) }
        }
        return touched
    }
}

public struct A2UITab: Equatable {
    public let title: String
    public let child: A2UINode

    public init(title: String, child: A2UINode) {
        self.title = title
        self.child = child
    }
}

public indirect enum A2UINode: Equatable {
    case text(String, variant: String)
    case image(url: String, description: String?)
    case fileThumbnail(url: String)
    case button(child: A2UINode, action: A2UIAction?, variant: String)
    case card(child: A2UINode)
    case divider(axis: String)
    case stack(axis: String, children: [A2UINode], justify: String, align: String)
    case list(children: [A2UINode], direction: String)
    case tabs([A2UITab])
}

public enum A2UIAction: Equatable {
    case function(name: String, arguments: [String: JSONValue])
    case event(String)
}

public enum A2UIResolver {
    public static func resolve(_ surface: A2UISurface) throws -> A2UINode {
        try resolveComponent(id: "root", surface: surface, scope: nil)
    }

    static func resolveComponent(id: String, surface: A2UISurface, scope: JSONValue?) throws -> A2UINode {
        guard let component = surface.components[id] else {
            throw A2UIError.invalidPayload("Unknown component reference: \(id)")
        }
        switch component.type {
        case "Text":
            return .text(
                string(component.properties["text"], surface: surface, scope: scope) ?? "",
                variant: string(component.properties["variant"], surface: surface, scope: scope) ?? "body"
            )
        case "Image":
            guard let url = string(component.properties["url"], surface: surface, scope: scope) else {
                throw A2UIError.invalidProperty("Image requires url")
            }
            return .image(url: url, description: string(component.properties["description"], surface: surface, scope: scope))
        case "FileThumbnail":
            guard let url = string(component.properties["url"], surface: surface, scope: scope) else {
                throw A2UIError.invalidProperty("FileThumbnail requires url")
            }
            return .fileThumbnail(url: url)
        case "Button":
            guard let child = string(component.properties["child"], surface: surface, scope: scope) else {
                throw A2UIError.invalidProperty("Button requires child")
            }
            return .button(
                child: try resolveComponent(id: child, surface: surface, scope: scope),
                action: action(component.properties["action"], surface: surface, scope: scope),
                variant: string(component.properties["variant"], surface: surface, scope: scope) ?? "default"
            )
        case "Card":
            guard let child = string(component.properties["child"], surface: surface, scope: scope) else {
                throw A2UIError.invalidProperty("Card requires child")
            }
            return .card(child: try resolveComponent(id: child, surface: surface, scope: scope))
        case "Divider":
            return .divider(axis: string(component.properties["axis"], surface: surface, scope: scope) ?? "horizontal")
        case "Row":
            return .stack(
                axis: "row",
                children: try children(component, surface: surface, scope: scope),
                justify: string(component.properties["justify"], surface: surface, scope: scope) ?? "start",
                align: string(component.properties["align"], surface: surface, scope: scope) ?? "stretch"
            )
        case "Column":
            return .stack(
                axis: "column",
                children: try children(component, surface: surface, scope: scope),
                justify: string(component.properties["justify"], surface: surface, scope: scope) ?? "start",
                align: string(component.properties["align"], surface: surface, scope: scope) ?? "stretch"
            )
        case "List":
            return .list(
                children: try children(component, surface: surface, scope: scope),
                direction: string(component.properties["direction"], surface: surface, scope: scope) ?? "vertical"
            )
        case "Tabs":
            let rawTabs = component.properties["tabs"]?.arrayValue ?? []
            let tabs = try rawTabs.map { item -> A2UITab in
                guard case let .object(values) = item,
                      let child = string(values["child"], surface: surface, scope: scope)
                else {
                    throw A2UIError.invalidProperty("Tabs entries require title and child")
                }
                return A2UITab(
                    title: string(values["title"], surface: surface, scope: scope) ?? "",
                    child: try resolveComponent(id: child, surface: surface, scope: scope)
                )
            }
            return .tabs(tabs)
        default:
            throw A2UIError.unknownComponent(component.type)
        }
    }

    static func children(_ component: A2UIComponent, surface: A2UISurface, scope: JSONValue?) throws -> [A2UINode] {
        guard let children = component.properties["children"] else { return [] }
        switch children {
        case let .array(items):
            return try items.compactMap { item -> A2UINode? in
                guard let id = item.stringValue else { return nil }
                return try resolveComponent(id: id, surface: surface, scope: scope)
            }
        case let .object(values):
            guard let componentId = values["componentId"]?.stringValue,
                  let path = values["path"]?.stringValue
            else {
                throw A2UIError.invalidProperty("children template requires componentId and path")
            }
            let items = surface.dataModel.value(at: path, scope: scope)?.arrayValue ?? []
            return try items.map { item in
                try resolveComponent(id: componentId, surface: surface, scope: item)
            }
        default:
            return []
        }
    }

    static func string(_ value: JSONValue?, surface: A2UISurface, scope: JSONValue?) -> String? {
        guard let value else { return nil }
        switch value {
        case let .string(text):
            return text
        case let .object(values):
            guard let path = values["path"]?.stringValue else { return nil }
            return surface.dataModel.value(at: path, scope: scope)?.stringValue
        default:
            return nil
        }
    }

    static func action(_ value: JSONValue?, surface: A2UISurface, scope: JSONValue?) -> A2UIAction? {
        guard case let .object(values)? = value else { return nil }
        if case let .object(event)? = values["event"], let name = event["name"]?.stringValue {
            return .event(name)
        }
        if case let .object(call)? = values["functionCall"], let name = call["call"]?.stringValue {
            var arguments: [String: JSONValue] = [:]
            if case let .object(rawArguments)? = call["args"] {
                for (key, argument) in rawArguments {
                    arguments[key] = resolveValue(argument, surface: surface, scope: scope)
                }
            }
            return .function(name: name, arguments: arguments)
        }
        return nil
    }

    static func resolveValue(_ value: JSONValue, surface: A2UISurface, scope: JSONValue?) -> JSONValue {
        if case let .object(values) = value,
           values.count == 1,
           let path = values["path"]?.stringValue
        {
            return surface.dataModel.value(at: path, scope: scope) ?? value
        }
        return value
    }
}
