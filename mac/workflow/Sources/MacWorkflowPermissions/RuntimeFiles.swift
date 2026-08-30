import Darwin
import Foundation
import MacWorkflowCore

enum RuntimeFiles {
    static let directory = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/Mac Workflow Permissions", isDirectory: true)
    static let token = directory.appendingPathComponent("api-token")
    static let port = directory.appendingPathComponent("port")
    static let permissionStatus = directory.appendingPathComponent("permission-status")

    static func prepare(port: UInt16) throws -> String {
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let tokenValue: String
        if let existing = try? String(contentsOf: token, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines),
           !existing.isEmpty {
            tokenValue = existing
        } else {
            tokenValue = UUID().uuidString + UUID().uuidString
            try tokenValue.write(to: token, atomically: true, encoding: .utf8)
        }
        try SecureFilePermissions.ensureOwnerReadWrite(token)
        try String(port).write(to: self.port, atomically: true, encoding: .utf8)
        try writePermissions()
        return tokenValue
    }

    static func writePermissions() throws {
        let values = PermissionService.dictionary
        let text = ["accessibility", "screen_recording"]
            .map { "\($0)=\(values[$0] == true ? "granted" : "not granted")" }
            .joined(separator: "\n") + "\n"
        try text.write(to: permissionStatus, atomically: true, encoding: .utf8)
    }
}
