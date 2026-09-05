import Foundation
import MacflowCore
import MacflowUI
import Network

struct HTTPResponse {
    let status: Int
    let value: Any

    static func ok(_ value: Any) -> HTTPResponse { HTTPResponse(status: 200, value: value) }
    static func error(_ status: Int, _ message: String) -> HTTPResponse {
        HTTPResponse(status: status, value: ["error": message])
    }

    var data: Data {
        let body = (try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])) ?? Data("{}".utf8)
        let reason: String
        switch status {
        case 200: reason = "OK"
        case 400: reason = "Bad Request"
        case 401: reason = "Unauthorized"
        case 404: reason = "Not Found"
        case 422: reason = "Unprocessable Entity"
        default: reason = "Internal Server Error"
        }
        let header = "HTTP/1.1 \(status) \(reason)\r\nContent-Type: application/json\r\nContent-Length: \(body.count)\r\nConnection: close\r\n\r\n"
        return Data(header.utf8) + body
    }
}

final class HTTPServer {
    private let configuration: WorkflowConfiguration.Server
    private let token: String
    private let applications: ApplicationService
    private let windows: WindowService
    private let screens: ScreenService
    private let preview: any ScreenshotPreviewing
    private let screenshots: ScreenshotController
    private let shelf: FileShelfController
    private let hotKeyStatus: () -> HotKeyStatus
    private let permissions: PermissionAccess
    private var listener: NWListener?
    private let queue = DispatchQueue(label: "dev.vikramsingh.mac-workflow.http")

    init(
        configuration: WorkflowConfiguration.Server,
        token: String,
        applications: ApplicationService,
        windows: WindowService,
        screens: ScreenService,
        preview: any ScreenshotPreviewing,
        screenshots: ScreenshotController,
        shelf: FileShelfController,
        hotKeyStatus: @escaping () -> HotKeyStatus,
        permissions: PermissionAccess = .live
    ) {
        self.configuration = configuration
        self.token = token
        self.applications = applications
        self.windows = windows
        self.screens = screens
        self.preview = preview
        self.screenshots = screenshots
        self.shelf = shelf
        self.hotKeyStatus = hotKeyStatus
        self.permissions = permissions
    }

    func start() throws {
        guard let port = NWEndpoint.Port(rawValue: configuration.port) else {
            throw NSError(domain: "MacWorkflow.HTTP", code: 1, userInfo: [NSLocalizedDescriptionKey: "Invalid port"])
        }
        let parameters = NWParameters.tcp
        parameters.requiredLocalEndpoint = .hostPort(host: NWEndpoint.Host(configuration.host), port: port)
        let listener = try NWListener(using: parameters)
        listener.newConnectionHandler = { [weak self] in self?.accept($0) }
        listener.stateUpdateHandler = { state in
            if case let .failed(error) = state {
                NSLog("HTTP server failed: \(error)")
            }
        }
        self.listener = listener
        listener.start(queue: queue)
    }

    func stop() {
        listener?.cancel()
        listener = nil
    }

    var port: UInt16? { listener?.port?.rawValue }

    private func accept(_ connection: NWConnection) {
        connection.start(queue: queue)
        receive(connection, accumulated: Data())
    }

    private func receive(_ connection: NWConnection, accumulated: Data) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 1_048_576) { [weak self] data, _, complete, error in
            guard let self else { return }
            var buffer = accumulated
            if let data { buffer.append(data) }
            if let reason = HTTPParser.rejectionReason(buffer) {
                let response = HTTPResponse.error(400, reason)
                connection.send(content: response.data, completion: .contentProcessed { _ in connection.cancel() })
            } else if let request = HTTPParser.parse(buffer) {
                DispatchQueue.main.async {
                    self.route(request) { response in
                        connection.send(content: response.data, completion: .contentProcessed { _ in connection.cancel() })
                    }
                }
            } else if complete || error != nil || buffer.count >= 1_048_576 {
                let response = HTTPResponse.error(400, "Invalid or incomplete request")
                connection.send(content: response.data, completion: .contentProcessed { _ in connection.cancel() })
            } else {
                self.receive(connection, accumulated: buffer)
            }
        }
    }

    private func route(_ request: HTTPRequest, completion: @escaping (HTTPResponse) -> Void) {
        if request.method == "GET", request.path == "/v1/health" {
            completion(.ok(["ok": true, "pid": ProcessInfo.processInfo.processIdentifier]))
            return
        }
        guard request.headers["authorization"] == "Bearer \(token)" else {
            completion(.error(401, "Unauthorized"))
            return
        }

        do {
            switch (request.method, request.path) {
            case ("GET", "/v1/permissions"):
                completion(.ok(try permissions.status().json))
            case ("POST", "/v1/permissions/request"):
                guard let body = try? jsonBody(request) else {
                    completion(.error(400, "JSON object required"))
                    return
                }
                do {
                    let result = try PermissionRequestHandler.handle(
                        body: body,
                        request: permissions.request
                    )
                    completion(.ok(result.json))
                } catch let error as PermissionCommandError {
                    completion(.error(400, error.localizedDescription))
                }
            case ("GET", "/v1/hotkeys"):
                completion(.ok(hotKeyStatus().json))
            case ("GET", "/v1/applications"):
                completion(.ok(["applications": applications.all()]))
            case ("GET", "/v1/windows"):
                guard let bundleID = request.queryItems["bundle_id"] else {
                    completion(.error(400, "bundle_id is required"))
                    return
                }
                completion(.ok(["windows": try windows.windows(bundleID: bundleID).map(\.json)]))
            case ("GET", "/v1/screens"):
                completion(.ok(["screens": screens.all().map(\.json)]))
            case ("POST", "/v1/applications/launch"):
                let body = try jsonBody(request)
                guard let bundleID = body["bundle_id"] as? String else {
                    completion(.error(400, "bundle_id is required"))
                    return
                }
                applications.launch(bundleID: bundleID) { result in
                    switch result {
                    case let .success(app): completion(.ok(["pid": app.processIdentifier, "bundle_id": bundleID]))
                    case let .failure(error): completion(.error(422, error.localizedDescription))
                    }
                }
            case ("POST", "/v1/overlays/image"):
                let body = try jsonBody(request)
                guard let path = body["path"] as? String else {
                    completion(.error(400, "path is required"))
                    return
                }
                let timeout = body["timeout_seconds"] as? Double
                completion(preview.show(path: path, timeout: timeout)
                    ? .ok(["shown": true, "path": path])
                    : .error(422, "Image could not be loaded"))
            case ("GET", "/v1/overlays"):
                completion(.ok(["overlays": [preview.json]]))
            case ("DELETE", "/v1/overlays"):
                preview.hide()
                completion(.ok(["hidden": true]))
            case ("GET", "/v1/file-shelves"):
                completion(.ok(["file_shelves": [shelf.json]]))
            case ("POST", "/v1/file-shelves"):
                let body = try jsonBody(request)
                guard let directory = body["directory"] as? String else {
                    completion(.error(400, "directory is required"))
                    return
                }
                let options = WorkflowConfiguration.Shelf(
                    sources: [WorkflowConfiguration.Shelf.Source(
                        id: "files",
                        label: "Files",
                        icon: "folder",
                        directory: directory
                    )],
                    extensions: body["extensions"] as? [String] ?? ["png", "jpg", "jpeg", "webp"],
                    width: body["width"] as? Double ?? 1200,
                    height: body["height"] as? Double ?? 420,
                    thumbnailWidth: body["thumbnail_width"] as? Double ?? 240,
                    spacing: body["spacing"] as? Double ?? 12,
                    margin: body["margin"] as? Double ?? 20,
                    closeAfterDrag: body["close_after_drag"] as? Bool ?? true,
                    closeDelay: body["close_delay"] as? Double ?? 0.2,
                    restoreFocus: body["restore_focus"] as? Bool ?? true
                )
                completion(shelf.show(configuration: options, allowsEmpty: false)
                    ? .ok(shelf.json)
                    : .error(422, "No supported files available"))
            case ("POST", "/v1/input/keystroke"):
                let body = try jsonBody(request)
                guard let key = body["key"] as? String,
                      let modifiers = body["modifiers"] as? [String]
                else {
                    completion(.error(400, "key and modifiers are required"))
                    return
                }
                try InputService.keyStroke(key: key, modifiers: modifiers)
                completion(.ok(["sent": true, "key": key, "modifiers": modifiers]))
            case ("POST", "/v1/input/click"):
                let body = try jsonBody(request)
                guard let x = body["x"] as? Double,
                      let y = body["y"] as? Double,
                      let button = body["button"] as? String
                else {
                    completion(.error(400, "x, y, and button are required"))
                    return
                }
                try InputService.click(x: x, y: y, button: button)
                completion(.ok(["sent": true, "x": x, "y": y, "button": button]))
            case ("POST", "/v1/input/drag"):
                let body = try jsonBody(request)
                guard let from = body["from"] as? [String: Any],
                      let to = body["to"] as? [String: Any],
                      let fromX = from["x"] as? Double,
                      let fromY = from["y"] as? Double,
                      let toX = to["x"] as? Double,
                      let toY = to["y"] as? Double
                else {
                    completion(.error(400, "from and to points are required"))
                    return
                }
                let duration = body["duration"] as? Double ?? 0.5
                try InputService.drag(
                    from: CGPoint(x: fromX, y: fromY),
                    to: CGPoint(x: toX, y: toY),
                    duration: duration
                )
                completion(.ok(["sent": true]))
            case ("POST", "/v1/screenshots"):
                let body = request.body.isEmpty ? [:] : try jsonBody(request)
                let displayID = (body["display_id"] as? NSNumber).map { UInt32($0.uint32Value) }
                let path = body["path"] as? String
                let showPreview = body["show_preview"] as? Bool ?? false
                screenshots.takeScreenshot(displayID: displayID, path: path, showPreview: showPreview) { result in
                    switch result {
                    case let .success(value): completion(.ok(value))
                    case let .failure(error): completion(.error(422, error.localizedDescription))
                    }
                }
            default:
                if request.method == "DELETE", request.path.hasPrefix("/v1/file-shelves/") {
                    let identifier = String(request.path.dropFirst("/v1/file-shelves/".count))
                    guard shelf.identifier == identifier else {
                        completion(.error(404, "File shelf not found"))
                        return
                    }
                    shelf.hide()
                    completion(.ok(["closed": true, "id": identifier]))
                } else if request.path.hasPrefix("/v1/windows/") {
                    routeWindow(request, completion: completion)
                } else {
                    completion(.error(404, "Not found"))
                }
            }
        } catch {
            completion(.error(422, error.localizedDescription))
        }
    }

    private func routeWindow(_ request: HTTPRequest, completion: @escaping (HTTPResponse) -> Void) {
        var suffix = String(request.path.dropFirst("/v1/windows/".count))
        let focusing = suffix.hasSuffix("/focus")
        if focusing { suffix.removeLast("/focus".count) }
        let unminimizing = suffix.hasSuffix("/unminimize")
        if unminimizing { suffix.removeLast("/unminimize".count) }
        do {
            let window = try windows.window(identifier: suffix.removingPercentEncoding ?? suffix)
            if request.method == "GET", !focusing, !unminimizing {
                completion(.ok(window.json))
            } else if request.method == "POST", focusing {
                try windows.focus(window)
                completion(.ok(window.json))
            } else if request.method == "POST", unminimizing {
                try windows.unminimize(window)
                completion(.ok(window.json))
            } else if request.method == "PUT", !focusing {
                let body = try jsonBody(request)
                guard let frameBody = body["frame"] as? [String: Any],
                      let x = frameBody["x"] as? Double,
                      let y = frameBody["y"] as? Double,
                      let width = frameBody["width"] as? Double,
                      let height = frameBody["height"] as? Double
                else {
                    completion(.error(400, "frame with x, y, width, and height is required"))
                    return
                }
                try windows.setFrame(CGRect(x: x, y: y, width: width, height: height), for: window)
                completion(.ok(["id": suffix, "frame": CGRect(x: x, y: y, width: width, height: height).dictionary]))
            } else {
                completion(.error(404, "Not found"))
            }
        } catch {
            completion(.error(422, error.localizedDescription))
        }
    }

    private func jsonBody(_ request: HTTPRequest) throws -> [String: Any] {
        guard let object = try JSONSerialization.jsonObject(with: request.body) as? [String: Any] else {
            throw NSError(domain: "MacWorkflow.HTTP", code: 2, userInfo: [NSLocalizedDescriptionKey: "JSON object required"])
        }
        return object
    }
}
