import CoreGraphics
import Foundation
import MacflowCore

final class HotKeyService {
    private var eventTap: CFMachPort?
    private var runLoopSource: CFRunLoopSource?
    private var callbacks: [UInt32: () -> Void] = [:]
    private var router = GlobalHotKeyRouter()
    private var nextID: UInt32 = 1
    private let createEventTap: (UnsafeMutableRawPointer) -> CFMachPort?

    init(createEventTap: @escaping (UnsafeMutableRawPointer) -> CFMachPort? = HotKeyService.makeEventTap) {
        self.createEventTap = createEventTap
    }

    private static func makeEventTap(context: UnsafeMutableRawPointer) -> CFMachPort? {
        let mask = (CGEventMask(1) << CGEventType.keyDown.rawValue)
            | (CGEventMask(1) << CGEventType.keyUp.rawValue)
        return CGEvent.tapCreate(
            tap: .cgSessionEventTap,
            place: .headInsertEventTap,
            options: .defaultTap,
            eventsOfInterest: mask,
            callback: { _, type, event, context in
                guard let context else { return Unmanaged.passUnretained(event) }
                let service = Unmanaged<HotKeyService>.fromOpaque(context).takeUnretainedValue()
                return service.handle(type: type, event: event)
            },
            userInfo: context
        )
    }

    func start() throws {
        guard eventTap == nil else { return }
        guard let eventTap = createEventTap(Unmanaged.passUnretained(self).toOpaque()) else {
            throw NSError(
                domain: "Macflow.HotKey",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: "Could not install global hotkey event tap; Accessibility permission is required"]
            )
        }

        let source = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, eventTap, 0)
        CFRunLoopAddSource(CFRunLoopGetMain(), source, .commonModes)
        CGEvent.tapEnable(tap: eventTap, enable: true)
        self.eventTap = eventTap
        runLoopSource = source
    }

    @discardableResult
    func register(
        modifiers: [String],
        key: String,
        scope: HotKeyScope = .global,
        callback: @escaping () -> Void
    ) throws -> UInt32 {
        guard scope == .global, let chord = HotKeyChord(modifiers: modifiers, key: key) else {
            throw NSError(
                domain: "Macflow.HotKey",
                code: 2,
                userInfo: [NSLocalizedDescriptionKey: "Unsupported global hotkey: \(modifiers)+\(key)"]
            )
        }
        let id = nextID
        guard router.register(chord, bindingID: id) else {
            throw NSError(
                domain: "Macflow.HotKey",
                code: 3,
                userInfo: [NSLocalizedDescriptionKey: "Duplicate global hotkey: \(modifiers)+\(key)"]
            )
        }
        nextID += 1
        callbacks[id] = callback
        return id
    }

    func unregister(_ id: UInt32) {
        callbacks.removeValue(forKey: id)
        router.unregister(bindingID: id)
    }

    var status: HotKeyStatus {
        HotKeyStatus(
            eventTapEnabled: eventTap.map { CGEvent.tapIsEnabled(tap: $0) } ?? false,
            secureInputEnabled: PermissionService.secureInput()
        )
    }

    private func handle(type: CGEventType, event: CGEvent) -> Unmanaged<CGEvent>? {
        if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
            router.resetPressState()
            if let eventTap { CGEvent.tapEnable(tap: eventTap, enable: true) }
            return Unmanaged.passUnretained(event)
        }
        guard type == .keyDown || type == .keyUp else {
            return Unmanaged.passUnretained(event)
        }

        let input = HotKeyInputEvent(
            phase: type == .keyDown ? .keyDown : .keyUp,
            keyCode: UInt32(event.getIntegerValueField(.keyboardEventKeycode)),
            modifiers: modifiers(from: event.flags),
            isRepeat: event.getIntegerValueField(.keyboardEventAutorepeat) != 0
        )
        let decision = router.handle(input)
        if let id = decision.triggeredBindingID, let callback = callbacks[id] {
            DispatchQueue.main.async(execute: callback)
        }
        return decision.consume ? nil : Unmanaged.passUnretained(event)
    }

    private func modifiers(from flags: CGEventFlags) -> Set<HotKeyModifier> {
        var modifiers = Set<HotKeyModifier>()
        if flags.contains(.maskCommand) { modifiers.insert(.command) }
        if flags.contains(.maskShift) { modifiers.insert(.shift) }
        if flags.contains(.maskAlternate) { modifiers.insert(.option) }
        if flags.contains(.maskControl) { modifiers.insert(.control) }
        return modifiers
    }

    func stop() {
        if let runLoopSource { CFRunLoopRemoveSource(CFRunLoopGetMain(), runLoopSource, .commonModes) }
        if let eventTap { CFMachPortInvalidate(eventTap) }
        runLoopSource = nil
        eventTap = nil
        router.resetPressState()
    }

    deinit { stop() }
}
