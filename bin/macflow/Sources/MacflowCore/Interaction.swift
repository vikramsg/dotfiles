import Foundation

public enum KeyCodeResolver {
    private static let codes: [String: UInt32] = [
        "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5,
        "z": 6, "x": 7, "c": 8, "v": 9, "b": 11,
        "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17,
        "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23,
        "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29,
        "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35,
        "return": 36, "l": 37, "j": 38, "'": 39, "k": 40,
        ";": 41, "\\": 42, ",": 43, "/": 44, "n": 45, "m": 46,
        ".": 47, "tab": 48, "space": 49, "`": 50, "delete": 51,
        "escape": 53, "esc": 53,
        "left": 123, "right": 124, "down": 125, "up": 126,
    ]

    public static let supportedModifiers: Set<String> = [
        "cmd", "command", "shift", "option", "alt", "control", "ctrl",
    ]

    public static func resolve(_ key: String) -> UInt32? {
        codes[key.lowercased()]
    }
}

public enum HotKeyScope: String, Codable, Equatable {
    case global
}

public enum HotKeyModifier: String, Hashable {
    case command
    case shift
    case option
    case control

    public init?(configurationValue: String) {
        switch configurationValue.lowercased() {
        case "cmd", "command": self = .command
        case "shift": self = .shift
        case "option", "alt": self = .option
        case "control", "ctrl": self = .control
        default: return nil
        }
    }
}

public struct HotKeyChord: Hashable {
    public let keyCode: UInt32
    public let modifiers: Set<HotKeyModifier>

    public init?(modifiers: [String], key: String) {
        guard let keyCode = KeyCodeResolver.resolve(key) else { return nil }
        let normalized = modifiers.compactMap(HotKeyModifier.init(configurationValue:))
        guard normalized.count == modifiers.count else { return nil }
        self.keyCode = keyCode
        self.modifiers = Set(normalized)
    }

    public init(keyCode: UInt32, modifiers: Set<HotKeyModifier>) {
        self.keyCode = keyCode
        self.modifiers = modifiers
    }
}

public enum HotKeyEventPhase {
    case keyDown
    case keyUp
}

public struct HotKeyInputEvent {
    public let phase: HotKeyEventPhase
    public let keyCode: UInt32
    public let modifiers: Set<HotKeyModifier>
    public let isRepeat: Bool

    public init(
        phase: HotKeyEventPhase,
        keyCode: UInt32,
        modifiers: Set<HotKeyModifier>,
        isRepeat: Bool = false
    ) {
        self.phase = phase
        self.keyCode = keyCode
        self.modifiers = modifiers
        self.isRepeat = isRepeat
    }
}

public struct HotKeyDecision: Equatable {
    public let consume: Bool
    public let triggeredBindingID: UInt32?
}

public struct GlobalHotKeyRouter {
    private var bindings: [HotKeyChord: [UInt32]] = [:]
    private var consumedKeyCodes = Set<UInt32>()

    public init() {}

    @discardableResult
    public mutating func register(_ chord: HotKeyChord, bindingID: UInt32) -> Bool {
        guard bindings[chord]?.contains(bindingID) != true else { return false }
        bindings[chord, default: []].append(bindingID)
        return true
    }

    public mutating func unregister(bindingID: UInt32) {
        bindings = bindings.compactMapValues { ids in
            let remaining = ids.filter { $0 != bindingID }
            return remaining.isEmpty ? nil : remaining
        }
    }

    public mutating func resetPressState() {
        consumedKeyCodes.removeAll()
    }

    public mutating func handle(_ event: HotKeyInputEvent) -> HotKeyDecision {
        switch event.phase {
        case .keyDown:
            if consumedKeyCodes.contains(event.keyCode) {
                return HotKeyDecision(consume: true, triggeredBindingID: nil)
            }
            let chord = HotKeyChord(keyCode: event.keyCode, modifiers: event.modifiers)
            guard let bindingID = bindings[chord]?.last else {
                return HotKeyDecision(consume: false, triggeredBindingID: nil)
            }
            let inserted = consumedKeyCodes.insert(event.keyCode).inserted
            return HotKeyDecision(
                consume: true,
                triggeredBindingID: inserted && !event.isRepeat ? bindingID : nil
            )
        case .keyUp:
            let consumed = consumedKeyCodes.remove(event.keyCode) != nil
            return HotKeyDecision(consume: consumed, triggeredBindingID: nil)
        }
    }
}

public struct SuspensionGate {
    private var count = 0

    public init() {}

    public var isSuspended: Bool { count > 0 }

    public mutating func suspend() {
        count += 1
    }

    public mutating func resume() {
        count = max(0, count - 1)
    }
}
