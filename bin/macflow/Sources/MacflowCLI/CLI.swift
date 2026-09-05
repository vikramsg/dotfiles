import ArgumentParser
import Darwin
import Foundation
import MacflowCore

struct CLIError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

struct HTTPRequestPlan {
    let method: String
    let path: String
    let body: [String: Any]?
    let authenticated: Bool

    init(method: String, path: String, body: [String: Any]? = nil, authenticated: Bool = true) {
        self.method = method
        self.path = path
        self.body = body
        self.authenticated = authenticated
    }
}

struct MacflowHTTPClient {
    func send(_ plan: HTTPRequestPlan) throws -> Data {
        let configuration = try ConfigurationLoader.loadWorkflow()
        guard let url = HTTPURLBuilder.make(
            host: configuration.server.host,
            port: configuration.server.port,
            path: plan.path
        ) else {
            throw CLIError(message: "Invalid server URL")
        }
        var request = URLRequest(url: url)
        request.httpMethod = plan.method
        request.timeoutInterval = 5
        if plan.authenticated {
            let token = try String(contentsOf: runtimeFile("api-token"), encoding: .utf8)
                .trimmingCharacters(in: .whitespacesAndNewlines)
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        if let body = plan.body {
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
                result = .failure(
                    CLIError(message: object?["error"] as? String ?? "HTTP \(response.statusCode)")
                )
            }
        }.resume()
        semaphore.wait()
        return try result!.get()
    }

    private func runtimeFile(_ name: String) -> URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Macflow", isDirectory: true)
            .appendingPathComponent(name)
    }
}

protocol HTTPCommand: ParsableCommand {
    func requestPlan() throws -> HTTPRequestPlan
}

extension HTTPCommand {
    mutating func run() throws {
        let data = try MacflowHTTPClient().send(try requestPlan())
        let object = try JSONSerialization.jsonObject(with: data)
        let formatted = try JSONSerialization.data(withJSONObject: object, options: [.prettyPrinted, .sortedKeys])
        print(String(decoding: formatted, as: UTF8.self))
    }
}

enum PermissionName: String, CaseIterable, ExpressibleByArgument {
    case accessibility
    case screenRecording = "screen-recording"

    var apiValue: String {
        switch self {
        case .accessibility: return "accessibility"
        case .screenRecording: return "screen_recording"
        }
    }
}

enum MouseButton: String, CaseIterable, ExpressibleByArgument {
    case left
    case right
}

struct MacflowCommand: ParsableCommand {
    static let configuration = CommandConfiguration(
        commandName: "macflow",
        abstract: "Control the Macflow automation application.",
        subcommands: [
            App.self, Window.self, Screen.self, Input.self,
            ScreenshotCommands.self, UI.self, System.self,
        ]
    )

    struct App: ParsableCommand {
        static let configuration = CommandConfiguration(
            abstract: "List, launch, and activate applications.",
            subcommands: [Applications.self, Launch.self]
        )
    }

    struct Window: ParsableCommand {
        static let configuration = CommandConfiguration(
            abstract: "Inspect, position, and focus application windows.",
            subcommands: [Windows.self, Frame.self, Focus.self, Unminimize.self]
        )
    }

    struct Screen: ParsableCommand {
        static let configuration = CommandConfiguration(
            abstract: "Inspect displays and usable screen geometry.",
            subcommands: [Screens.self]
        )
    }

    struct Input: ParsableCommand {
        static let configuration = CommandConfiguration(
            abstract: "Send keyboard and mouse input.",
            subcommands: [Keystroke.self, Click.self, Drag.self]
        )
    }

    struct ScreenshotCommands: ParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "screenshot",
            abstract: "Capture displays to PNG files.",
            subcommands: [Screenshot.self]
        )
    }

    struct UI: ParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "ui",
            abstract: "Show and dismiss Macflow-owned UI.",
            subcommands: [OverlayCommands.self, ShelfCommands.self]
        )
    }

    struct OverlayCommands: ParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "overlay",
            abstract: "Show, inspect, and hide image overlays.",
            subcommands: [Overlay.self, Overlays.self, HideOverlays.self]
        )
    }

    struct ShelfCommands: ParsableCommand {
        static let configuration = CommandConfiguration(
            commandName: "shelf",
            abstract: "Show, inspect, and close file shelves.",
            subcommands: [Shelf.self, Shelves.self, CloseShelf.self]
        )
    }

    struct System: ParsableCommand {
        static let configuration = CommandConfiguration(
            abstract: "Check service health, permissions, and shortcuts.",
            subcommands: [Health.self, Doctor.self, Permissions.self]
        )
    }

    struct Health: HTTPCommand {
        static let configuration = CommandConfiguration(abstract: "Check whether Macflow is running.")

        func requestPlan() throws -> HTTPRequestPlan {
            HTTPRequestPlan(method: "GET", path: "/v1/health", authenticated: false)
        }
    }

    struct Doctor: ParsableCommand {
        static let configuration = CommandConfiguration(
            abstract: "Check permissions and global shortcut health."
        )

        mutating func run() throws {
            let client = MacflowHTTPClient()
            let report = DoctorCommand.run { request in
                try client.send(HTTPRequestPlan(method: request.method, path: request.path))
            }
            let color = DoctorRenderer.shouldUseColor(
                isTerminal: isatty(STDOUT_FILENO) == 1,
                environment: ProcessInfo.processInfo.environment
            )
            print(DoctorRenderer.render(report, color: color))
            if !report.passed { throw ExitCode.failure }
        }
    }

    struct Permissions: HTTPCommand {
        static let configuration = CommandConfiguration(
            abstract: "Show or request macOS permissions.",
            usage: "macflow system permissions [<subcommand>]",
            subcommands: [Request.self]
        )

        func requestPlan() throws -> HTTPRequestPlan {
            HTTPRequestPlan(method: "GET", path: "/v1/permissions")
        }

        struct Request: HTTPCommand {
            static let configuration = CommandConfiguration(
                abstract: "Request a macOS permission for Macflow."
            )

            @Argument(help: "Permission to request: accessibility or screen-recording.")
            var permission: PermissionName

            func requestPlan() throws -> HTTPRequestPlan {
                HTTPRequestPlan(
                    method: "POST",
                    path: "/v1/permissions/request",
                    body: ["permission": permission.apiValue]
                )
            }
        }
    }

    struct Applications: HTTPCommand {
        static let configuration = CommandConfiguration(commandName: "list", abstract: "List running applications.")

        func requestPlan() throws -> HTTPRequestPlan {
            HTTPRequestPlan(method: "GET", path: "/v1/applications")
        }
    }

    struct Windows: HTTPCommand {
        static let configuration = CommandConfiguration(commandName: "list", abstract: "List windows for an application.")

        @Argument(help: "Application bundle identifier.")
        var bundleID: String

        func requestPlan() throws -> HTTPRequestPlan {
            HTTPRequestPlan(method: "GET", path: "/v1/windows?bundle_id=\(encoded(bundleID))")
        }
    }

    struct Screens: HTTPCommand {
        static let configuration = CommandConfiguration(commandName: "list", abstract: "List displays.")

        func requestPlan() throws -> HTTPRequestPlan {
            HTTPRequestPlan(method: "GET", path: "/v1/screens")
        }
    }

    struct Launch: HTTPCommand {
        static let configuration = CommandConfiguration(abstract: "Launch or activate an application.")

        @Argument(help: "Application bundle identifier.")
        var bundleID: String

        func requestPlan() throws -> HTTPRequestPlan {
            HTTPRequestPlan(
                method: "POST",
                path: "/v1/applications/launch",
                body: ["bundle_id": bundleID]
            )
        }
    }

    struct Frame: HTTPCommand {
        static let configuration = CommandConfiguration(abstract: "Set a window frame.")

        @Argument(help: "Window identifier.") var windowID: String
        @Argument(help: "Horizontal origin.") var x: Double
        @Argument(help: "Vertical origin.") var y: Double
        @Argument(help: "Window width.") var width: Double
        @Argument(help: "Window height.") var height: Double

        func requestPlan() throws -> HTTPRequestPlan {
            HTTPRequestPlan(
                method: "PUT",
                path: "/v1/windows/\(encoded(windowID))",
                body: ["frame": ["x": x, "y": y, "width": width, "height": height]]
            )
        }
    }

    struct Focus: HTTPCommand {
        static let configuration = CommandConfiguration(abstract: "Focus a window.")

        @Argument(help: "Window identifier.") var windowID: String

        func requestPlan() throws -> HTTPRequestPlan {
            HTTPRequestPlan(method: "POST", path: "/v1/windows/\(encoded(windowID))/focus")
        }
    }

    struct Unminimize: HTTPCommand {
        static let configuration = CommandConfiguration(abstract: "Restore a minimized window.")

        @Argument(help: "Window identifier.") var windowID: String

        func requestPlan() throws -> HTTPRequestPlan {
            HTTPRequestPlan(method: "POST", path: "/v1/windows/\(encoded(windowID))/unminimize")
        }
    }

    struct Overlay: HTTPCommand {
        static let configuration = CommandConfiguration(commandName: "show", abstract: "Show an image overlay.")

        @Argument(help: "Image path.") var imagePath: String
        @Argument(help: "Optional display duration in seconds.") var timeoutSeconds: Double?

        func requestPlan() throws -> HTTPRequestPlan {
            var body: [String: Any] = ["path": URL(fileURLWithPath: imagePath).standardized.path]
            if let timeoutSeconds { body["timeout_seconds"] = timeoutSeconds }
            return HTTPRequestPlan(method: "POST", path: "/v1/overlays/image", body: body)
        }
    }

    struct Overlays: HTTPCommand {
        static let configuration = CommandConfiguration(commandName: "list", abstract: "List image overlays.")

        func requestPlan() throws -> HTTPRequestPlan {
            HTTPRequestPlan(method: "GET", path: "/v1/overlays")
        }
    }

    struct HideOverlays: HTTPCommand {
        static let configuration = CommandConfiguration(commandName: "hide", abstract: "Hide all image overlays.")

        func requestPlan() throws -> HTTPRequestPlan {
            HTTPRequestPlan(method: "DELETE", path: "/v1/overlays")
        }
    }

    struct Keystroke: HTTPCommand {
        static let configuration = CommandConfiguration(abstract: "Send a keyboard shortcut.")

        @Argument(help: "Key to press.") var key: String
        @Argument(help: "Modifiers to hold while pressing the key.") var modifiers: [String] = []

        func requestPlan() throws -> HTTPRequestPlan {
            HTTPRequestPlan(
                method: "POST",
                path: "/v1/input/keystroke",
                body: ["key": key, "modifiers": modifiers]
            )
        }
    }

    struct Click: HTTPCommand {
        static let configuration = CommandConfiguration(abstract: "Click a screen coordinate.")

        @Argument(help: "Mouse button.") var button: MouseButton
        @Argument(help: "Horizontal screen coordinate.") var x: Double
        @Argument(help: "Vertical screen coordinate.") var y: Double

        func requestPlan() throws -> HTTPRequestPlan {
            HTTPRequestPlan(
                method: "POST",
                path: "/v1/input/click",
                body: ["button": button.rawValue, "x": x, "y": y]
            )
        }
    }

    struct Drag: HTTPCommand {
        static let configuration = CommandConfiguration(abstract: "Drag between screen coordinates.")

        @Argument(help: "Starting horizontal coordinate.") var fromX: Double
        @Argument(help: "Starting vertical coordinate.") var fromY: Double
        @Argument(help: "Ending horizontal coordinate.") var toX: Double
        @Argument(help: "Ending vertical coordinate.") var toY: Double
        @Argument(help: "Optional drag duration in seconds.") var duration: Double?

        func requestPlan() throws -> HTTPRequestPlan {
            HTTPRequestPlan(
                method: "POST",
                path: "/v1/input/drag",
                body: [
                    "from": ["x": fromX, "y": fromY],
                    "to": ["x": toX, "y": toY],
                    "duration": duration ?? 0.5,
                ]
            )
        }
    }

    struct Shelves: HTTPCommand {
        static let configuration = CommandConfiguration(commandName: "list", abstract: "List native file shelves.")

        func requestPlan() throws -> HTTPRequestPlan {
            HTTPRequestPlan(method: "GET", path: "/v1/file-shelves")
        }
    }

    struct Shelf: HTTPCommand {
        static let configuration = CommandConfiguration(commandName: "show", abstract: "Show a file shelf for a directory.")

        @Argument(help: "Directory containing files for the shelf.") var directory: String

        func requestPlan() throws -> HTTPRequestPlan {
            HTTPRequestPlan(method: "POST", path: "/v1/file-shelves", body: ["directory": directory])
        }
    }

    struct CloseShelf: HTTPCommand {
        static let configuration = CommandConfiguration(commandName: "close", abstract: "Close a file shelf.")

        @Argument(help: "File shelf identifier.") var id: String

        func requestPlan() throws -> HTTPRequestPlan {
            HTTPRequestPlan(method: "DELETE", path: "/v1/file-shelves/\(encoded(id))")
        }
    }

    struct Screenshot: HTTPCommand {
        static let configuration = CommandConfiguration(commandName: "capture", abstract: "Capture a display to a PNG file.")

        @Option(name: .customLong("display"), help: "Display identifier.")
        var displayID: UInt32?

        @Option(name: .customLong("path"), help: "Destination PNG path.")
        var outputPath: String?

        @Flag(help: "Show the standard preview after capture.")
        var preview = false

        func requestPlan() throws -> HTTPRequestPlan {
            var body: [String: Any] = [:]
            if let displayID { body["display_id"] = displayID }
            if let outputPath { body["path"] = URL(fileURLWithPath: outputPath).standardized.path }
            if preview { body["show_preview"] = true }
            return HTTPRequestPlan(method: "POST", path: "/v1/screenshots", body: body)
        }
    }
}

private func encoded(_ value: String) -> String {
    value.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? value
}

public func runCLI(arguments: [String]) {
    MacflowCommand.main(arguments)
}
