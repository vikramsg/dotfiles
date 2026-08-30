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
