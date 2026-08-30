import Darwin
import Foundation

public enum SecureFilePermissions {
    public static func ensureOwnerReadWrite(_ url: URL) throws {
        guard chmod(url.path, S_IRUSR | S_IWUSR) == 0 else {
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
        }
    }
}
