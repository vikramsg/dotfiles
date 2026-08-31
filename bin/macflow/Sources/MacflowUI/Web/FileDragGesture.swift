import Foundation

struct FileDragGesture<Event> {
    private var mouseIsDown = false
    private var pendingURL: URL?
    private var deferredEvent: Event?

    mutating func mouseDown() {
        mouseIsDown = true
        pendingURL = nil
        deferredEvent = nil
    }

    mutating func prepare(_ url: URL) -> (URL, Event)? {
        guard mouseIsDown else { return nil }
        pendingURL = url
        guard let event = deferredEvent else { return nil }
        pendingURL = nil
        deferredEvent = nil
        return (url, event)
    }

    mutating func mouseDragged(_ event: Event) -> (URL, Event)? {
        guard let url = pendingURL else {
            deferredEvent = event
            return nil
        }
        pendingURL = nil
        deferredEvent = nil
        return (url, event)
    }

    mutating func mouseUp() {
        mouseIsDown = false
        pendingURL = nil
        deferredEvent = nil
    }
}
