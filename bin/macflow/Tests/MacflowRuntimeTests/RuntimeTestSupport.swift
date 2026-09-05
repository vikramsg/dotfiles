import Foundation
import MacflowCore
import Testing
@testable import Macflow

func testDirectory() throws -> URL {
    // Use a non-aliased path, like the configured screenshot directory. macOS's
    // /var temporary-directory alias is normalized differently for missing files.
    URL(fileURLWithPath: #filePath).deletingLastPathComponent()
        .deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent(".build", isDirectory: true)
        .appendingPathComponent("runtime-test-\(UUID().uuidString)", isDirectory: true)
}

func runtimeConfiguration(directory: URL) throws -> WorkflowConfiguration {
    let object: [String: Any] = [
        "server": ["host": "127.0.0.1", "port": 0],
        "applications": [:], "layouts": [:], "shelves": [:], "hotkeys": [],
        "screenshots": [
            "directory": directory.path, "extensions": ["png"],
            "debounce_seconds": 0.01, "capture_settle_seconds": 0.01,
            "preview": ["width": 100, "max_height": 100, "margin": 10, "timeout_seconds": 1, "corner_radius": 4],
        ],
    ]
    return try JSONDecoder().decode(WorkflowConfiguration.self, from: JSONSerialization.data(withJSONObject: object))
}

struct APIReply {
    let status: Int
    let body: [String: Any]
}

func request(port: UInt16, method: String = "GET", path: String, body: [String: Any]? = nil) async throws -> APIReply {
    var request = URLRequest(url: URL(string: "http://127.0.0.1:\(port)\(path)")!)
    request.httpMethod = method
    request.timeoutInterval = 3
    request.setValue("Bearer test-token", forHTTPHeaderField: "Authorization")
    if let body {
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    }
    let (data, response) = try await URLSession.shared.data(for: request)
    return APIReply(
        status: try #require(response as? HTTPURLResponse).statusCode,
        body: try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
    )
}

@MainActor
func eventually(_ condition: () -> Bool) async throws {
    let deadline = Date().addingTimeInterval(3)
    while !condition(), Date() < deadline { try await Task.sleep(for: .milliseconds(10)) }
    try #require(condition())
}
