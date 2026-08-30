import ApplicationServices
import CoreGraphics
import Foundation

enum PermissionService {
    static func accessibility(prompt: Bool = false) -> Bool {
        guard prompt else { return AXIsProcessTrusted() }
        let options = [
            kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true,
        ] as CFDictionary
        return AXIsProcessTrustedWithOptions(options)
    }

    static func screenRecording(prompt: Bool = false) -> Bool {
        if prompt && !CGPreflightScreenCaptureAccess() {
            return CGRequestScreenCaptureAccess()
        }
        return CGPreflightScreenCaptureAccess()
    }

    static var dictionary: [String: Bool] {
        [
            "accessibility": accessibility(),
            "screen_recording": screenRecording(),
        ]
    }
}
