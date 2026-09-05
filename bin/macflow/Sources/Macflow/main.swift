import AppKit
import MacflowCLI

@MainActor
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

    func applicationWillTerminate(_ notification: Notification) {
        runtime?.stop()
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

@MainActor
func runApplication() {
    let app = NSApplication.shared
    let delegate = AppDelegate()
    app.delegate = delegate
    app.setActivationPolicy(.accessory)
    app.run()
}

let arguments = Array(CommandLine.arguments.dropFirst())
if Bundle.main.bundleURL.pathExtension == "app" {
    MainActor.assumeIsolated { runApplication() }
} else {
    runCLI(arguments: arguments)
}
