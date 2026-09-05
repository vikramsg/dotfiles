import ApplicationServices
import Carbon.HIToolbox
import CoreGraphics
import Foundation
import MacflowCore

struct PermissionAccess {
    let status: () throws -> PermissionStatus
    let request: (PermissionKind) -> Bool

    static let live = PermissionAccess(
        status: {
            try RuntimeFiles.writePermissions()
            return PermissionService.status
        },
        request: PermissionService.request
    )
}

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

    static func secureInput() -> Bool {
        IsSecureEventInputEnabled()
    }

    static func request(_ permission: PermissionKind) -> Bool {
        switch permission {
        case .accessibility: return accessibility(prompt: true)
        case .screenRecording: return screenRecording(prompt: true)
        }
    }

    static var status: PermissionStatus {
        PermissionStatus(accessibility: accessibility(), screenRecording: screenRecording())
    }
}
