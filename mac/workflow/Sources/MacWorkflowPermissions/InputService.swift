import Carbon.HIToolbox
import CoreGraphics
import Darwin
import Foundation
import MacWorkflowCore

enum InputService {
    static func keyStroke(key: String, modifiers: [String]) throws {
        guard let code = KeyCodeResolver.resolve(key).map(CGKeyCode.init) else {
            throw NSError(domain: "MacWorkflow.Input", code: 1, userInfo: [NSLocalizedDescriptionKey: "Unsupported key: \(key)"])
        }
        let flags = modifiers.reduce(CGEventFlags()) { result, modifier in
            switch modifier.lowercased() {
            case "cmd", "command": return result.union(.maskCommand)
            case "shift": return result.union(.maskShift)
            case "option", "alt": return result.union(.maskAlternate)
            case "control", "ctrl": return result.union(.maskControl)
            default: return result
            }
        }
        let source = CGEventSource(stateID: .combinedSessionState)
        let down = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: true)
        let up = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: false)
        down?.flags = flags
        up?.flags = flags
        down?.post(tap: .cghidEventTap)
        up?.post(tap: .cghidEventTap)
    }

    static func click(x: Double, y: Double, button: String) throws {
        let mouseButton: CGMouseButton
        let downType: CGEventType
        let upType: CGEventType
        switch button.lowercased() {
        case "left":
            mouseButton = .left
            downType = .leftMouseDown
            upType = .leftMouseUp
        case "right":
            mouseButton = .right
            downType = .rightMouseDown
            upType = .rightMouseUp
        default:
            throw NSError(domain: "MacWorkflow.Input", code: 2, userInfo: [NSLocalizedDescriptionKey: "Unsupported mouse button: \(button)"])
        }
        let point = CGPoint(x: x, y: y)
        let source = CGEventSource(stateID: .combinedSessionState)
        CGEvent(mouseEventSource: source, mouseType: downType, mouseCursorPosition: point, mouseButton: mouseButton)?
            .post(tap: .cghidEventTap)
        CGEvent(mouseEventSource: source, mouseType: upType, mouseCursorPosition: point, mouseButton: mouseButton)?
            .post(tap: .cghidEventTap)
    }

    static func drag(from start: CGPoint, to end: CGPoint, duration: Double) throws {
        let steps = 20
        let delay = try InputValidation.dragDelayMicroseconds(duration: duration, steps: steps)
        DispatchQueue.global(qos: .userInitiated).async {
            let source = CGEventSource(stateID: .combinedSessionState)
            CGEvent(mouseEventSource: source, mouseType: .mouseMoved, mouseCursorPosition: start, mouseButton: .left)?
                .post(tap: .cghidEventTap)
            CGEvent(mouseEventSource: source, mouseType: .leftMouseDown, mouseCursorPosition: start, mouseButton: .left)?
                .post(tap: .cghidEventTap)
            for step in 1...steps {
                let progress = Double(step) / Double(steps)
                let point = CGPoint(
                    x: start.x + (end.x - start.x) * progress,
                    y: start.y + (end.y - start.y) * progress
                )
                CGEvent(mouseEventSource: source, mouseType: .leftMouseDragged, mouseCursorPosition: point, mouseButton: .left)?
                    .post(tap: .cghidEventTap)
                usleep(delay)
            }
            CGEvent(mouseEventSource: source, mouseType: .leftMouseUp, mouseCursorPosition: end, mouseButton: .left)?
                .post(tap: .cghidEventTap)
        }
    }

}
