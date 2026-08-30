import AppKit
import Darwin

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var runtime: AutomationRuntime?
    private var statusItem: NSStatusItem?

    func applicationDidFinishLaunching(_ notification: Notification) {
        do {
            let runtime = try AutomationRuntime()
            try runtime.start()
            self.runtime = runtime
            installStatusItem()
        } catch {
            presentFatal(error)
        }
    }

    private func installStatusItem() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        item.button?.image = NSImage(systemSymbolName: "rectangle.3.group", accessibilityDescription: "Macflow")
        let menu = NSMenu()
        menu.addItem(withTitle: "Show Screenshot Shelf", action: #selector(showShelf), keyEquivalent: "")
        menu.addItem(withTitle: "Request Accessibility", action: #selector(requestAccessibility), keyEquivalent: "")
        menu.addItem(.separator())
        menu.addItem(withTitle: "Quit", action: #selector(quit), keyEquivalent: "q")
        menu.items.forEach { $0.target = self }
        item.menu = menu
        statusItem = item
    }

    @objc private func showShelf() {
        runtime?.showFirstShelf()
    }

    @objc private func requestAccessibility() {
        _ = PermissionService.accessibility(prompt: true)
    }

    @objc private func quit() {
        NSApplication.shared.terminate(nil)
    }

    private func presentFatal(_ error: Error) {
        NSLog("Macflow failed to start: \(error.localizedDescription)")
        let alert = NSAlert()
        alert.messageText = "Macflow could not start"
        alert.informativeText = error.localizedDescription
        alert.runModal()
        NSApplication.shared.terminate(nil)
    }
}

func runApplication() {
    let app = NSApplication.shared
    let delegate = AppDelegate()
    app.delegate = delegate
    app.setActivationPolicy(.accessory)
    app.run()
}

func runServiceLauncher() -> Never {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/open")
    process.arguments = [
        "-W",
        "-g",
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Applications/Macflow.app").path,
    ]

    signal(SIGTERM, SIG_IGN)
    signal(SIGINT, SIG_IGN)
    let terminate = {
        NSRunningApplication.runningApplications(withBundleIdentifier: "dev.vikramsingh.dotfiles.mac-workflow")
            .forEach { $0.terminate() }
        process.terminate()
    }
    let terminationSignal = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .global())
    terminationSignal.setEventHandler(handler: terminate)
    terminationSignal.resume()
    let interruptSignal = DispatchSource.makeSignalSource(signal: SIGINT, queue: .global())
    interruptSignal.setEventHandler(handler: terminate)
    interruptSignal.resume()

    do {
        try process.run()
        process.waitUntilExit()
        exit(process.terminationStatus)
    } catch {
        fputs("macflow: \(error.localizedDescription)\n", stderr)
        exit(1)
    }
}

let arguments = Array(CommandLine.arguments.dropFirst())
if Bundle.main.bundleURL.pathExtension == "app" {
    runApplication()
} else if arguments.first == "serve" {
    runServiceLauncher()
} else {
    runCLI(arguments: arguments)
}
