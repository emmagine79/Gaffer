import AppKit
import WebKit

/// Gaffer's Mac shell: a menu-bar item and one window that shows the light
/// service's web page. All light work happens in the Python service.
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem?
    private var window: NSWindow?
    private var webView: WKWebView?
    private var service: ServiceProcess?
    private var serviceURL: URL?
    private var quitting = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMainMenu()
        buildStatusItem()
        buildWindow()
        showMessage("Starting Gaffer…")
        showWindow(nil)

        let service = ServiceProcess { [weak self] event in self?.handle(event) }
        self.service = service
        do {
            try service.start()
        } catch {
            NSLog("Gaffer: could not start the light service: \(error)")
            showMessage("Gaffer's light service didn't start. Quit Gaffer and open it again.")
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        quitting = true
        service?.stop()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false  // Gaffer stays in the menu bar.
    }

    private func handle(_ event: ServiceProcess.Event) {
        switch event {
        case .ready(let port):
            let url = URL(string: "http://127.0.0.1:\(port)/")!
            serviceURL = url
            webView?.load(URLRequest(url: url))
        case .stopped(let status):
            if !quitting {
                NSLog("Gaffer: light service stopped with status \(status)")
                showMessage("Gaffer's light service stopped. Quit Gaffer and open it again.")
            }
        }
    }

    // MARK: UI

    private func buildMainMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem()
        main.addItem(appItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Quit Gaffer", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        NSApp.mainMenu = main
    }

    private func buildStatusItem() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = item.button {
            let image = NSImage(systemSymbolName: "lightbulb", accessibilityDescription: "Gaffer")
            image?.isTemplate = true
            button.image = image
        }
        let menu = NSMenu()
        menu.addItem(withTitle: "Open Gaffer", action: #selector(showWindow(_:)), keyEquivalent: "")
        menu.addItem(withTitle: "Scan again", action: #selector(rescan(_:)), keyEquivalent: "")
        menu.addItem(.separator())
        menu.addItem(withTitle: "Quit Gaffer", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        for menuItem in menu.items where menuItem.action != #selector(NSApplication.terminate(_:)) {
            menuItem.target = self
        }
        item.menu = menu
        statusItem = item
    }

    private func buildWindow() {
        let web = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
        let win = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 420, height: 560),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        win.title = "Gaffer"
        win.contentView = web
        win.isReleasedWhenClosed = false
        win.center()
        window = win
        webView = web
    }

    private func showMessage(_ text: String) {
        let escaped = text
            .replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
        let html = """
        <!doctype html><meta charset="utf-8"><style>
        :root{color-scheme:light dark}body{margin:0;height:100vh;display:grid;place-items:center;
        font:14px -apple-system,sans-serif;color:#888;padding:16px;text-align:center}</style>
        <p>\(escaped)</p>
        """
        webView?.loadHTMLString(html, baseURL: nil)
    }

    @objc func showWindow(_ sender: Any?) {
        NSApp.activate(ignoringOtherApps: true)
        window?.makeKeyAndOrderFront(sender)
    }

    @objc func rescan(_ sender: Any?) {
        showWindow(sender)
        if let url = serviceURL { webView?.load(URLRequest(url: url)) }
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
