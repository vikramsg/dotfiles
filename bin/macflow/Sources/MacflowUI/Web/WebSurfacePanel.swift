import AppKit
import WebKit

public struct WebSurfaceRequest {
    public let action: String
    public let payload: [String: Any]
}

public enum WebSurfaceRequestError: LocalizedError {
    case malformedRequest

    public var errorDescription: String? { "Malformed web surface request" }
}

public final class WebSurfacePanel: FloatingSurfacePanel, NSDraggingSource, WKNavigationDelegate {
    public typealias RequestHandler = (WebSurfaceRequest) throws -> Any?

    public let webView: WKWebView
    public private(set) var loadedDocumentURL: URL?

    private let bridge: WebSurfaceMessageBridge
    private let fileSchemeHandler: WebSurfaceFileSchemeHandler
    private let documentDirectory: URL
    private let onCompletedDrag: () -> Void
    private var pendingDragURL: URL?
    private var deferredDragEvent: NSEvent?
    private var mouseIsDown = false
    private var dragEventMonitor: Any?

    public init(
        contentRect: NSRect,
        documentURL: URL,
        surfaceConfiguration: [String: Any],
        theme: MacflowTheme,
        activates: Bool,
        requestHandler: @escaping RequestHandler,
        onCompletedDrag: @escaping () -> Void
    ) throws {
        bridge = WebSurfaceMessageBridge(handler: requestHandler)
        fileSchemeHandler = WebSurfaceFileSchemeHandler()
        documentDirectory = documentURL.deletingLastPathComponent().standardizedFileURL
        self.onCompletedDrag = onCompletedDrag

        let webConfiguration = WKWebViewConfiguration()
        webConfiguration.websiteDataStore = .nonPersistent()
        webConfiguration.setURLSchemeHandler(fileSchemeHandler, forURLScheme: "macflow-file")
        webConfiguration.userContentController.addScriptMessageHandler(bridge, contentWorld: .page, name: "macflow")
        webConfiguration.userContentController.addUserScript(WKUserScript(
            source: try Self.bootstrapScript(configuration: surfaceConfiguration, theme: theme),
            injectionTime: .atDocumentStart,
            forMainFrameOnly: true
        ))
        webView = WKWebView(frame: NSRect(origin: .zero, size: contentRect.size), configuration: webConfiguration)

        super.init(contentRect: contentRect, theme: theme, activates: activates)
        webView.navigationDelegate = self
        webView.underPageBackgroundColor = .clear
        webView.autoresizingMask = [.width, .height]
        if #available(macOS 13.3, *) {
            webView.isInspectable = true
        }
        contentView = webView
        installDragEventMonitor()
        webView.loadFileURL(documentURL, allowingReadAccessTo: documentDirectory)
    }

    public func prepareFileDrag(_ url: URL) {
        guard mouseIsDown else { return }
        pendingDragURL = url
        if let event = deferredDragEvent {
            pendingDragURL = nil
            deferredDragEvent = nil
            beginFileDrag(url: url, event: event)
        }
    }

    public func registerFiles(_ urls: [URL]) -> [String: String] {
        fileSchemeHandler.replaceFiles(urls)
    }

    public override func close() {
        removeDragEventMonitor()
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "macflow", contentWorld: .page)
        webView.stopLoading()
        super.close()
    }

    public func draggingSession(
        _ session: NSDraggingSession,
        sourceOperationMaskFor context: NSDraggingContext
    ) -> NSDragOperation {
        .copy
    }

    public func ignoreModifierKeys(for session: NSDraggingSession) -> Bool { true }

    public func draggingSession(
        _ session: NSDraggingSession,
        endedAt screenPoint: NSPoint,
        operation: NSDragOperation
    ) {
        if !operation.isEmpty { onCompletedDrag() }
    }

    public func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
    ) {
        guard let url = navigationAction.request.url else {
            decisionHandler(.cancel)
            return
        }
        if url.scheme == "about" || isAllowedFileURL(url) {
            decisionHandler(.allow)
        } else {
            decisionHandler(.cancel)
        }
    }

    public func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        loadedDocumentURL = webView.url
    }

    private func isAllowedFileURL(_ url: URL) -> Bool {
        guard url.isFileURL else { return false }
        let path = url.standardizedFileURL.path
        return path == documentDirectory.path || path.hasPrefix(documentDirectory.path + "/")
    }

    private func installDragEventMonitor() {
        dragEventMonitor = NSEvent.addLocalMonitorForEvents(matching: [.leftMouseDown, .leftMouseDragged, .leftMouseUp]) {
            [weak self] event in
            guard let self, event.window === self else { return event }
            if event.type == .leftMouseDown {
                self.mouseIsDown = true
                self.pendingDragURL = nil
                self.deferredDragEvent = nil
                return event
            }
            if event.type == .leftMouseUp {
                self.mouseIsDown = false
                self.pendingDragURL = nil
                self.deferredDragEvent = nil
                return event
            }
            guard let url = self.pendingDragURL else {
                self.deferredDragEvent = event
                return event
            }
            self.pendingDragURL = nil
            self.deferredDragEvent = nil
            self.beginFileDrag(url: url, event: event)
            return nil
        }
    }

    private func removeDragEventMonitor() {
        if let dragEventMonitor {
            NSEvent.removeMonitor(dragEventMonitor)
            self.dragEventMonitor = nil
        }
    }

    private func beginFileDrag(url: URL, event: NSEvent) {
        let image = NSImage(contentsOf: url) ?? NSWorkspace.shared.icon(forFile: url.path)
        let maximumSize = NSSize(width: 180, height: 110)
        let scale = min(maximumSize.width / image.size.width, maximumSize.height / image.size.height, 1)
        let size = NSSize(width: max(1, image.size.width * scale), height: max(1, image.size.height * scale))
        let point = webView.convert(event.locationInWindow, from: nil)
        let item = NSDraggingItem(pasteboardWriter: url as NSURL)
        item.setDraggingFrame(
            NSRect(x: point.x - size.width / 2, y: point.y - size.height / 2, width: size.width, height: size.height),
            contents: image
        )
        webView.beginDraggingSession(with: [item], event: event, source: self)
    }

    private static func bootstrapScript(configuration: [String: Any], theme: MacflowTheme) throws -> String {
        let configurationData = try JSONSerialization.data(withJSONObject: configuration)
        let configurationJSON = String(decoding: configurationData, as: UTF8.self)
        let themeData = try JSONSerialization.data(withJSONObject: theme.webValues)
        let themeJSON = String(decoding: themeData, as: UTF8.self)
        return """
        (() => {
          const invoke = (action, payload = {}) =>
            window.webkit.messageHandlers.macflow.postMessage({ action, payload });
          const theme = \(themeJSON);
          window.macflow = Object.freeze({
            configuration: Object.freeze(\(configurationJSON)),
            theme: Object.freeze(theme),
            files: Object.freeze({
              list: options => invoke("files.list", options),
              open: path => invoke("files.open", { path }),
              reveal: path => invoke("files.reveal", { path }),
              prepareDrag: path => invoke("files.prepareDrag", { path })
            }),
            surface: Object.freeze({ dismiss: () => invoke("surface.dismiss") }),
            diagnostics: Object.freeze({ log: message => invoke("diagnostics.log", { message }) })
          });
          const css = Object.entries(theme)
            .map(([name, value]) => `--macflow-${name}: ${value};`)
            .join("");
          const style = document.createElement("style");
          style.textContent = `:root { ${css} }`;
          (document.head || document.documentElement).appendChild(style);
        })();
        """
    }
}

private final class WebSurfaceFileSchemeHandler: NSObject, WKURLSchemeHandler {
    private let lock = NSLock()
    private var files: [String: URL] = [:]
    private var identifiersByPath: [String: String] = [:]

    func replaceFiles(_ urls: [URL]) -> [String: String] {
        lock.lock()
        var nextFiles: [String: URL] = [:]
        var nextIdentifiers: [String: String] = [:]
        var result: [String: String] = [:]
        for url in urls {
            let identifier = identifiersByPath[url.path] ?? UUID().uuidString
            nextFiles[identifier] = url
            nextIdentifiers[url.path] = identifier
            result[url.path] = "macflow-file://asset/\(identifier)"
        }
        files = nextFiles
        identifiersByPath = nextIdentifiers
        lock.unlock()
        return result
    }

    func webView(_ webView: WKWebView, start urlSchemeTask: WKURLSchemeTask) {
        guard let requestURL = urlSchemeTask.request.url else {
            fail(urlSchemeTask, message: "Missing file URL")
            return
        }
        let identifier = requestURL.lastPathComponent
        lock.lock()
        let fileURL = files[identifier]
        lock.unlock()
        guard let fileURL, let data = try? Data(contentsOf: fileURL, options: .mappedIfSafe) else {
            fail(urlSchemeTask, message: "Unknown file")
            return
        }
        let response = URLResponse(
            url: requestURL,
            mimeType: mimeType(for: fileURL),
            expectedContentLength: data.count,
            textEncodingName: nil
        )
        urlSchemeTask.didReceive(response)
        urlSchemeTask.didReceive(data)
        urlSchemeTask.didFinish()
    }

    func webView(_ webView: WKWebView, stop urlSchemeTask: WKURLSchemeTask) {}

    private func mimeType(for url: URL) -> String {
        switch url.pathExtension.lowercased() {
        case "jpg", "jpeg": return "image/jpeg"
        case "webp": return "image/webp"
        default: return "image/png"
        }
    }

    private func fail(_ task: WKURLSchemeTask, message: String) {
        task.didFailWithError(NSError(
            domain: "Macflow.WebSurfaceFile",
            code: 1,
            userInfo: [NSLocalizedDescriptionKey: message]
        ))
    }
}

private final class WebSurfaceMessageBridge: NSObject, WKScriptMessageHandlerWithReply {
    private let handler: WebSurfacePanel.RequestHandler

    init(handler: @escaping WebSurfacePanel.RequestHandler) {
        self.handler = handler
    }

    func userContentController(
        _ userContentController: WKUserContentController,
        didReceive message: WKScriptMessage,
        replyHandler: @escaping (Any?, String?) -> Void
    ) {
        guard let body = message.body as? [String: Any],
              let action = body["action"] as? String
        else {
            replyHandler(nil, WebSurfaceRequestError.malformedRequest.localizedDescription)
            return
        }
        do {
            let result = try handler(WebSurfaceRequest(
                action: action,
                payload: body["payload"] as? [String: Any] ?? [:]
            ))
            replyHandler(result, nil)
        } catch {
            replyHandler(nil, error.localizedDescription)
        }
    }
}
