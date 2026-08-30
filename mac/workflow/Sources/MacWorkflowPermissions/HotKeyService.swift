import Carbon.HIToolbox
import Foundation
import MacWorkflowCore

final class HotKeyService {
    private static let signature = OSType(0x4D57464C) // MWFL
    private var handler: EventHandlerRef?
    private var hotKeys: [UInt32: (ref: EventHotKeyRef, callback: () -> Void)] = [:]
    private var nextID: UInt32 = 1

    init() throws {
        var type = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        let status = InstallEventHandler(
            GetApplicationEventTarget(),
            { _, event, context in
                guard let event, let context else { return noErr }
                var identifier = EventHotKeyID()
                let result = GetEventParameter(
                    event,
                    EventParamName(kEventParamDirectObject),
                    EventParamType(typeEventHotKeyID),
                    nil,
                    MemoryLayout<EventHotKeyID>.size,
                    nil,
                    &identifier
                )
                guard result == noErr else { return result }
                let service = Unmanaged<HotKeyService>.fromOpaque(context).takeUnretainedValue()
                service.hotKeys[identifier.id]?.callback()
                return noErr
            },
            1,
            &type,
            Unmanaged.passUnretained(self).toOpaque(),
            &handler
        )
        if status != noErr { throw NSError(domain: NSOSStatusErrorDomain, code: Int(status)) }
    }

    @discardableResult
    func register(modifiers: [String], key: String, callback: @escaping () -> Void) throws -> UInt32 {
        guard let keyCode = KeyCodeResolver.resolve(key) else {
            throw NSError(domain: "MacWorkflow.HotKey", code: 1, userInfo: [NSLocalizedDescriptionKey: "Unsupported key: \(key)"])
        }
        let id = nextID
        nextID += 1
        let hotKeyID = EventHotKeyID(signature: Self.signature, id: id)
        var reference: EventHotKeyRef?
        let status = RegisterEventHotKey(
            keyCode,
            modifierFlags(modifiers),
            hotKeyID,
            GetApplicationEventTarget(),
            0,
            &reference
        )
        guard status == noErr, let reference else {
            throw NSError(domain: NSOSStatusErrorDomain, code: Int(status))
        }
        hotKeys[id] = (reference, callback)
        return id
    }

    func unregister(_ id: UInt32) {
        guard let hotKey = hotKeys.removeValue(forKey: id) else { return }
        UnregisterEventHotKey(hotKey.ref)
    }

    private func modifierFlags(_ modifiers: [String]) -> UInt32 {
        modifiers.reduce(0) { flags, modifier in
            switch modifier.lowercased() {
            case "cmd", "command": return flags | UInt32(cmdKey)
            case "shift": return flags | UInt32(shiftKey)
            case "option", "alt": return flags | UInt32(optionKey)
            case "control", "ctrl": return flags | UInt32(controlKey)
            default: return flags
            }
        }
    }

    deinit {
        hotKeys.values.forEach { UnregisterEventHotKey($0.ref) }
        if let handler { RemoveEventHandler(handler) }
    }
}
