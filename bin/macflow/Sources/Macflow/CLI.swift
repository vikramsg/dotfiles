import Foundation
import MacflowCore

struct CLIError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

func usage() -> Never {
    print("""
    Usage:
      macflow health
      macflow permissions
      macflow request-permission <accessibility|screen-recording>
      macflow applications
      macflow windows <bundle-id>
      macflow screens
      macflow launch <bundle-id>
      macflow frame <window-id> <x> <y> <width> <height>
      macflow focus <window-id>
      macflow unminimize <window-id>
      macflow overlay <image-path> [timeout-seconds]
      macflow overlays
      macflow hide-overlays
      macflow keystroke <key> [modifier ...]
      macflow click <left|right> <x> <y>
      macflow drag <from-x> <from-y> <to-x> <to-y> [duration]
      macflow shelves
      macflow shelf <directory>
      macflow close-shelf <id>
      macflow screenshot [--display <id>] [--path <png-path>] [--preview]
    """)
    exit(2)
}

func runtimeFile(_ name: String) -> URL {
    FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/Macflow", isDirectory: true)
        .appendingPathComponent(name)
}

func request(method: String, path: String, body: [String: Any]? = nil, authenticated: Bool = true) throws -> Data {
    let configuration = try ConfigurationLoader.loadWorkflow()
    guard let url = HTTPURLBuilder.make(
        host: configuration.server.host,
        port: configuration.server.port,
        path: path
    ) else {
        throw CLIError(message: "Invalid server URL")
    }
    var request = URLRequest(url: url)
    request.httpMethod = method
    request.timeoutInterval = 5
    if authenticated {
        let token = try String(contentsOf: runtimeFile("api-token"), encoding: .utf8)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    }
    if let body {
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    }

    let semaphore = DispatchSemaphore(value: 0)
    var result: Result<Data, Error>?
    URLSession.shared.dataTask(with: request) { data, response, error in
        defer { semaphore.signal() }
        if let error {
            result = .failure(error)
            return
        }
        guard let response = response as? HTTPURLResponse, let data else {
            result = .failure(CLIError(message: "Invalid server response"))
            return
        }
        if (200..<300).contains(response.statusCode) {
            result = .success(data)
        } else {
            let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            result = .failure(CLIError(message: object?["error"] as? String ?? "HTTP \(response.statusCode)"))
        }
    }.resume()
    semaphore.wait()
    return try result!.get()
}

func encoded(_ value: String) -> String {
    value.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? value
}

func runCLI(arguments: [String]) {
do {
    let data: Data
    if let permissionCommand = try PermissionCommand.parse(arguments: arguments) {
        let permissionRequest = permissionCommand.httpRequest
        data = try request(
            method: permissionRequest.method,
            path: permissionRequest.path,
            body: permissionRequest.body
        )
    } else {
    guard let command = arguments.first else { usage() }
    switch command {
    case "health":
        data = try request(method: "GET", path: "/v1/health", authenticated: false)
    case "applications":
        data = try request(method: "GET", path: "/v1/applications")
    case "windows":
        guard arguments.count == 2 else { usage() }
        data = try request(method: "GET", path: "/v1/windows?bundle_id=\(encoded(arguments[1]))")
    case "screens":
        data = try request(method: "GET", path: "/v1/screens")
    case "launch":
        guard arguments.count == 2 else { usage() }
        data = try request(method: "POST", path: "/v1/applications/launch", body: ["bundle_id": arguments[1]])
    case "frame":
        guard arguments.count == 6,
              let x = Double(arguments[2]), let y = Double(arguments[3]),
              let width = Double(arguments[4]), let height = Double(arguments[5])
        else { usage() }
        data = try request(
            method: "PUT",
            path: "/v1/windows/\(encoded(arguments[1]))",
            body: ["frame": ["x": x, "y": y, "width": width, "height": height]]
        )
    case "focus":
        guard arguments.count == 2 else { usage() }
        data = try request(method: "POST", path: "/v1/windows/\(encoded(arguments[1]))/focus")
    case "unminimize":
        guard arguments.count == 2 else { usage() }
        data = try request(method: "POST", path: "/v1/windows/\(encoded(arguments[1]))/unminimize")
    case "overlay":
        guard arguments.count == 2 || arguments.count == 3 else { usage() }
        var body: [String: Any] = ["path": URL(fileURLWithPath: arguments[1]).standardized.path]
        if arguments.count == 3 {
            guard let timeout = Double(arguments[2]) else { usage() }
            body["timeout_seconds"] = timeout
        }
        data = try request(method: "POST", path: "/v1/overlays/image", body: body)
    case "overlays":
        data = try request(method: "GET", path: "/v1/overlays")
    case "hide-overlays":
        data = try request(method: "DELETE", path: "/v1/overlays")
    case "keystroke":
        guard arguments.count >= 2 else { usage() }
        data = try request(
            method: "POST",
            path: "/v1/input/keystroke",
            body: ["key": arguments[1], "modifiers": Array(arguments.dropFirst(2))]
        )
    case "click":
        guard arguments.count == 4, let x = Double(arguments[2]), let y = Double(arguments[3]) else { usage() }
        data = try request(
            method: "POST",
            path: "/v1/input/click",
            body: ["button": arguments[1], "x": x, "y": y]
        )
    case "drag":
        guard (arguments.count == 5 || arguments.count == 6),
              let fromX = Double(arguments[1]), let fromY = Double(arguments[2]),
              let toX = Double(arguments[3]), let toY = Double(arguments[4])
        else { usage() }
        let duration = arguments.count == 6 ? Double(arguments[5]) : 0.5
        guard let duration else { usage() }
        data = try request(
            method: "POST",
            path: "/v1/input/drag",
            body: [
                "from": ["x": fromX, "y": fromY],
                "to": ["x": toX, "y": toY],
                "duration": duration,
            ]
        )
    case "shelves":
        data = try request(method: "GET", path: "/v1/file-shelves")
    case "shelf":
        guard arguments.count == 2 else { usage() }
        data = try request(method: "POST", path: "/v1/file-shelves", body: ["directory": arguments[1]])
    case "close-shelf":
        guard arguments.count == 2 else { usage() }
        data = try request(method: "DELETE", path: "/v1/file-shelves/\(encoded(arguments[1]))")
    case "screenshot":
        var body: [String: Any] = [:]
        var index = 1
        while index < arguments.count {
            if arguments[index] == "--preview" {
                body["show_preview"] = true
                index += 1
                continue
            }
            guard index + 1 < arguments.count else { usage() }
            switch arguments[index] {
            case "--display":
                guard let displayID = UInt32(arguments[index + 1]) else { usage() }
                body["display_id"] = displayID
            case "--path":
                body["path"] = URL(fileURLWithPath: arguments[index + 1]).standardized.path
            default:
                usage()
            }
            index += 2
        }
        data = try request(method: "POST", path: "/v1/screenshots", body: body)
    default:
        usage()
    }
    }

    let object = try JSONSerialization.jsonObject(with: data)
    let formatted = try JSONSerialization.data(withJSONObject: object, options: [.prettyPrinted, .sortedKeys])
    print(String(decoding: formatted, as: UTF8.self))
} catch {
    fputs("macflow: \(error.localizedDescription)\n", stderr)
    exit(1)
}
}
