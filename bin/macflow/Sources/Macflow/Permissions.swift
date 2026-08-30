import ApplicationServices
import CoreGraphics
import Foundation
import MacflowCore

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

    static func request(_ permission: PermissionKind) -> Bool {
        switch permission {
        case .accessibility: return accessibility(prompt: true)
        case .screenRecording: return screenRecording(prompt: true)
        }
    }

    static var dictionary: [String: Bool] {
        [
            "accessibility": accessibility(),
            "screen_recording": screenRecording(),
        ]
    }
}
