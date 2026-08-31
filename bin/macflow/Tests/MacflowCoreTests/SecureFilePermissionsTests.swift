import Foundation
import Testing
@testable import MacflowCore

@Suite struct SecureFilePermissionsIntegrationTests {
    @Test func testExistingFileIsRestrictedToOwnerReadWrite() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let token = directory.appendingPathComponent("token")
        try "secret".write(to: token, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: token.path)

        try SecureFilePermissions.ensureOwnerReadWrite(token)

        let attributes = try FileManager.default.attributesOfItem(atPath: token.path)
        #expect((attributes[.posixPermissions] as? NSNumber)?.intValue == 0o600)
    }
}
