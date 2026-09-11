import Foundation
import Testing
@testable import MacflowCore

@Suite struct A2UITests {
    private func decode(_ json: String) throws -> [A2UIMessage] {
        try A2UIMessageDecoder.decode(Data(json.utf8))
    }

    @Test func decodesAnArrayOfMessages() throws {
        let messages = try decode(
            """
            [
              {"version":"v0.9.1","createSurface":{"surfaceId":"s","catalogId":"macflow/v1"}},
              {"version":"v0.9.1","updateComponents":{"surfaceId":"s","components":[
                {"id":"root","component":"Text","text":"hello"}
              ]}},
              {"version":"v0.9.1","updateDataModel":{"surfaceId":"s","path":"/x","value":1}},
              {"version":"v0.9.1","deleteSurface":{"surfaceId":"s"}}
            ]
            """
        )
        #expect(messages.count == 4)
        #expect(messages[0].surfaceId == "s")
    }

    @Test func decodesASingleMessageObject() throws {
        let messages = try decode(#"{"version":"v0.9.1","deleteSurface":{"surfaceId":"only"}}"#)
        #expect(messages == [.deleteSurface(surfaceId: "only")])
    }

    @Test func rejectsMessagesWithoutVersion() {
        #expect(throws: A2UIError.self) {
            try decode(#"{"deleteSurface":{"surfaceId":"s"}}"#)
        }
    }

    @Test func rejectsMessagesWithTwoTypes() {
        #expect(throws: A2UIError.self) {
            try decode(#"{"version":"v0.9.1","deleteSurface":{"surfaceId":"s"},"updateDataModel":{"surfaceId":"s","value":1}}"#)
        }
    }

    @Test func rejectsUnknownComponentsAndFunctions() {
        let unknownComponent = A2UIComponent(id: "root", type: "Spaceship")
        #expect(throws: A2UIError.unknownComponent("Spaceship")) {
            try A2UICatalog.validate(unknownComponent)
        }

        let unknownFunction = A2UIComponent(
            id: "root",
            type: "Image",
            properties: [
                "url": .string("file:///a.png"),
                "action": .object(["functionCall": .object(["call": .string("files.explode")])]),
            ]
        )
        #expect(throws: A2UIError.unknownFunction("files.explode")) {
            try A2UICatalog.validate(unknownFunction)
        }
    }

    @Test func dataModelMergesAtPathAndResolvesValues() {
        var model = A2UIDataModel()
        model.set(path: "/shots", value: .array([.object(["url": .string("a")]), .object(["url": .string("b")])]))
        model.set(path: "/title", value: .string("hello"))

        #expect(model.value(at: "/title") == .string("hello"))
        #expect(model.value(at: "/shots/1/url") == .string("b"))
        // Relative path resolves against the supplied scope.
        #expect(model.value(at: "url", scope: .object(["url": .string("scoped")])) == .string("scoped"))
        // A later write to the same subtree replaces only that subtree.
        model.set(path: "/title", value: .string("changed"))
        #expect(model.value(at: "/title") == .string("changed"))
        #expect(model.value(at: "/shots/0/url") == .string("a"))
    }

    @Test func resolvingATemplateExpandsOncePerListItem() throws {
        let root = A2UIComponent(
            id: "root",
            type: "List",
            properties: [
                "direction": .string("horizontal"),
                "children": .object(["componentId": .string("thumb"), "path": .string("/shots")]),
            ]
        )
        let thumb = A2UIComponent(
            id: "thumb",
            type: "Image",
            properties: ["url": .object(["path": .string("url")])]
        )
        var surface = A2UISurface(id: "s", components: ["root": root, "thumb": thumb])
        surface.setDataModel(path: "/shots", value: .array([
            .object(["url": .string("file:///a.png")]),
            .object(["url": .string("file:///b.png")]),
            .object(["url": .string("file:///c.png")]),
        ]))

        let node = try A2UIResolver.resolve(surface)
        guard case let .list(children, _) = node else {
            Issue.record("Expected a list node")
            return
        }
        #expect(children.count == 3)
        let urls = children.compactMap { child -> String? in
            guard case let .image(url, _) = child else { return nil }
            return url
        }
        #expect(urls == ["file:///a.png", "file:///b.png", "file:///c.png"])
    }

    @Test func createSurfaceResetsTreeAndDataModel() throws {
        var store = A2UISurfaceStore()
        try store.apply(try decode(
            """
            [
              {"version":"v0.9.1","createSurface":{"surfaceId":"s"}},
              {"version":"v0.9.1","updateComponents":{"surfaceId":"s","components":[{"id":"root","component":"Text","text":"first"}]}},
              {"version":"v0.9.1","updateDataModel":{"surfaceId":"s","path":"/shots","value":[1,2,3]}}
            ]
            """
        ))
        #expect(store.surface(id: "s")?.elements == 2)

        try store.apply(try decode(
            """
            [
              {"version":"v0.9.1","createSurface":{"surfaceId":"s"}},
              {"version":"v0.9.1","updateComponents":{"surfaceId":"s","components":[{"id":"root","component":"Text","text":"second"}]}}
            ]
            """
        ))
        #expect(store.surface(id: "s")?.elements == 1)
        #expect(store.surface(id: "s")?.dataModel.value(at: "/shots") == nil)
    }

    @Test func updateComponentsWithoutCreateSurfaceMerges() throws {
        var store = A2UISurfaceStore()
        try store.apply(try decode(
            #"{"version":"v0.9.1","updateComponents":{"surfaceId":"s","components":[{"id":"a","component":"Text","text":"a"}]}}"#
        ))
        try store.apply(try decode(
            #"{"version":"v0.9.1","updateComponents":{"surfaceId":"s","components":[{"id":"b","component":"Text","text":"b"}]}}"#
        ))
        #expect(store.surface(id: "s")?.elements == 2)
    }

    @Test func deleteSurfaceRemovesTheSurface() throws {
        var store = A2UISurfaceStore()
        try store.apply(try decode(
            #"{"version":"v0.9.1","updateComponents":{"surfaceId":"gone","components":[{"id":"root","component":"Text","text":"x"}]}}"#
        ))
        #expect(store.surface(id: "gone") != nil)
        try store.apply(try decode(#"{"version":"v0.9.1","deleteSurface":{"surfaceId":"gone"}}"#))
        #expect(store.surface(id: "gone") == nil)
    }
}

private extension A2UISurface {
    /// Number of components plus top-level data keys, a compact "did reset" signal.
    var elements: Int {
        components.count + (dataModel.value(at: "/")?.objectValue?.count ?? 0)
    }
}
