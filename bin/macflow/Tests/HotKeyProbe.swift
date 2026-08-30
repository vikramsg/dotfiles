import AppKit
import Darwin

final class ProbeDelegate: NSObject, NSApplicationDelegate {
    private let outputURL: URL
    private var monitor: Any?
    private var activationSignal: DispatchSourceSignal?
    private var window: NSWindow?

    init(outputURL: URL) {
        self.outputURL = outputURL
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let window = NSWindow(
            contentRect: NSRect(x: 100, y: 100, width: 480, height: 240),
            styleMask: [.titled, .closable],
            backing: .buffered,
            defer: false
        )
        window.title = "Macflow HotKey Probe"
        window.makeKeyAndOrderFront(nil)
        self.window = window

        monitor = NSEvent.addLocalMonitorForEvents(matching: [.keyDown, .keyUp]) { [weak self] event in
            self?.record(event)
            return event
        }

        signal(SIGUSR1, SIG_IGN)
        let source = DispatchSource.makeSignalSource(signal: SIGUSR1, queue: .main)
        source.setEventHandler {
            NSApp.activate(ignoringOtherApps: true)
            window.makeKeyAndOrderFront(nil)
        }
        source.resume()
        activationSignal = source

        NSApp.activate(ignoringOtherApps: true)
        try? Data().write(to: outputURL)
        try? Data("ready".utf8).write(to: outputURL.appendingPathExtension("ready"))
    }

    private func record(_ event: NSEvent) {
        let phase = event.type == .keyDown ? "down" : "up"
        let line = "\(phase) \(event.keyCode)\n"
        guard let data = line.data(using: .utf8),
              let handle = try? FileHandle(forWritingTo: outputURL)
        else { return }
        defer { try? handle.close() }
        _ = try? handle.seekToEnd()
        try? handle.write(contentsOf: data)
    }
}

guard CommandLine.arguments.count == 2 else { exit(2) }
let app = NSApplication.shared
let delegate = ProbeDelegate(outputURL: URL(fileURLWithPath: CommandLine.arguments[1]))
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
