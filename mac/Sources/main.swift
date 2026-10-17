import AppKit
import WebKit

/// Gaffer's Mac shell: a menu-bar item with the current look's name, a panel under
/// it, a main window, and global shortcuts. All light work happens in the Python
/// service; the shell links no Bluetooth framework (contracts/api.md).
final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    private var statusItem: NSStatusItem?
    private var popover = NSPopover()
    private var window: NSWindow?
    private var panelView: WKWebView?
    private var windowView: WKWebView?
    private var service: ServiceProcess?
    private var servicePort: Int?
    private var serviceStopped = false
    private var quitting = false
    /// True from the sign-in request until its page has loaded; then the surfaces load.
    private var signingIn = false

    private let client = ServiceClient()
    private let store = ShortcutStore()
    private lazy var hotKeys = HotKeyCenter(store: store)
    private lazy var settings = SettingsWindowController(store: store, hotKeys: hotKeys)

    private var lookName: String?
    private var link: ServiceClient.Link = .idle
    private var problem: String?

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMainMenu()
        buildStatusItem()
        buildViews()
        showMessage("Starting Gaffer…")
        showWindow(nil)

        client.onLook = { [weak self] name in
            self?.lookName = name
            self?.updateStatusItem()
        }
        client.onLink = { [weak self] link in
            self?.link = link
            self?.updateStatusItem()
        }
        hotKeys.onPress = { [weak self] action in self?.run(action) }
        hotKeys.start()

        let service = ServiceProcess { [weak self] event in self?.handle(event) }
        self.service = service
        do {
            try service.start()
        } catch {
            NSLog("Gaffer: could not start the light service: \(error)")
            serviceStopped = true
            showMessage("Gaffer's light service didn't start. Quit Gaffer and open it again.")
            updateStatusItem()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        quitting = true
        client.stop()
        service?.stop()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false  // Gaffer stays in the menu bar.
    }

    private func handle(_ event: ServiceProcess.Event) {
        switch event {
        case .ready(let port):
            guard let secret = service?.secret else { return }
            servicePort = port
            client.start(port: port, secret: secret)
            // One-time sign-in link: sets the session cookie in the data store both
            // views share. The panel view uses it; once its page has loaded, both
            // views load their own surface.
            signingIn = true
            panelView?.load(URLRequest(url: URL(string: "http://127.0.0.1:\(port)/session?key=\(secret)")!))
        case .stopped(let status):
            serviceStopped = true
            client.stop()
            lookName = nil
            popover.performClose(nil)
            if !quitting {
                NSLog("Gaffer: light service stopped with status \(status)")
                showMessage("Gaffer's light service stopped. Quit Gaffer and open it again.")
            }
            updateStatusItem()
        }
    }

    private func surfaceURL(_ surface: String) -> URL? {
        servicePort.flatMap { URL(string: "http://127.0.0.1:\($0)/?surface=\(surface)") }
    }

    // MARK: Shortcuts

    private func run(_ action: ShortcutAction) {
        let done: (Result<Void, ServiceClient.Failure>) -> Void = { [weak self] result in
            switch result {
            case .success:
                self?.problem = nil
            case .failure(let failure):
                NSSound.beep()  // a key press with no window needs some sign that it failed
                self?.problem = failure.message
                NSLog("Gaffer: \(action.title) failed: \(failure.message)")
            }
        }
        switch action {
        case .look(let slot): client.applyLook(slot: slot, completion: done)
        case .allOff: client.allOff(completion: done)
        case .nextCue: client.nextCue(completion: done)
        }
    }

    // MARK: Menu bar

    private func buildMainMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem()
        main.addItem(appItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Settings…", action: #selector(showSettings(_:)), keyEquivalent: ",").target = self
        appMenu.addItem(.separator())
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
            button.target = self
            button.action = #selector(statusClicked(_:))
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }
        statusItem = item
        updateStatusItem()
    }

    private func updateStatusItem() {
        guard let button = statusItem?.button else { return }
        let name = lookName
        if let name {
            // The full name: macOS clips or hides a status item that doesn't fit the menu bar.
            button.title = name
            button.imagePosition = .imageLeading
            button.toolTip = "Gaffer: \(name)"
        } else {
            button.title = ""
            button.imagePosition = .imageOnly
            button.toolTip = "Gaffer"
        }
    }

    /// Left click: the panel. Right click, or Control-click: the menu.
    @objc private func statusClicked(_ sender: NSStatusBarButton) {
        let event = NSApp.currentEvent
        if event?.type == .rightMouseUp || event?.modifierFlags.contains(.control) == true {
            statusItem?.menu = buildMenu()
            sender.performClick(nil)
            statusItem?.menu = nil
        } else {
            togglePanel(sender)
        }
    }

    private func buildMenu() -> NSMenu {
        let menu = NSMenu()
        menu.autoenablesItems = false
        let state: String
        if serviceStopped {
            state = "Light service stopped"
        } else if link == .reconnecting {
            state = "Reconnecting to the light service…"
        } else if let lookName {
            state = "Look: \(lookName)"
        } else {
            state = "No look active"
        }
        let header = menu.addItem(withTitle: state, action: nil, keyEquivalent: "")
        header.isEnabled = false
        if let problem {
            menu.addItem(withTitle: problem, action: nil, keyEquivalent: "").isEnabled = false
        }
        menu.addItem(.separator())
        menu.addItem(withTitle: "Open Gaffer", action: #selector(showWindow(_:)), keyEquivalent: "").target = self
        menu.addItem(withTitle: "Settings…", action: #selector(showSettings(_:)), keyEquivalent: ",").target = self
        menu.addItem(withTitle: "Scan again", action: #selector(rescan(_:)), keyEquivalent: "").target = self
        menu.addItem(.separator())
        menu.addItem(withTitle: "Quit Gaffer", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        return menu
    }

    private func togglePanel(_ sender: NSStatusBarButton) {
        if popover.isShown {
            popover.performClose(nil)
        } else {
            NSApp.activate(ignoringOtherApps: true)
            popover.show(relativeTo: sender.bounds, of: sender, preferredEdge: .minY)
        }
    }

    // MARK: Views

    private func buildViews() {
        // One in-memory data store for both views: they share the session cookie, and
        // it dies with this launch.
        let store = WKWebsiteDataStore.nonPersistent()
        func makeView() -> WKWebView {
            let config = WKWebViewConfiguration()
            config.websiteDataStore = store
            let view = WKWebView(frame: .zero, configuration: config)
            view.navigationDelegate = self
            // No white flash before the page loads in dark mode. The page itself follows
            // the Mac's appearance through prefers-color-scheme, which WKWebView sets.
            view.underPageBackgroundColor = .windowBackgroundColor
            return view
        }
        let panel = makeView()
        let main = makeView()
        panelView = panel
        windowView = main

        let controller = NSViewController()
        controller.view = panel
        popover.contentViewController = controller
        popover.contentSize = NSSize(width: 400, height: 560)  // 400 pt wide as in design/ROUND4.md
        popover.behavior = .transient

        let win = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 420, height: 560),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        win.title = "Gaffer"
        win.contentView = main
        win.isReleasedWhenClosed = false
        win.center()
        window = win
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
        windowView?.loadHTMLString(html, baseURL: nil)
        panelView?.loadHTMLString(html, baseURL: nil)
    }

    // MARK: Page loading

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard signingIn, webView === panelView else { return }
        signingIn = false
        if let url = surfaceURL("menubar") { panelView?.load(URLRequest(url: url)) }
        if let url = surfaceURL("window") { windowView?.load(URLRequest(url: url)) }
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationResponse: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        // A refused page (not signed in, bad host) would show raw JSON. Say it in words.
        if navigationResponse.isForMainFrame, let http = navigationResponse.response as? HTTPURLResponse,
           http.statusCode >= 400 {
            decisionHandler(.cancel)
            signingIn = false
            showMessage("Gaffer's light service refused the page. Quit Gaffer and open it again.")
            return
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        pageFailed(error)
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        pageFailed(error)
    }

    private func pageFailed(_ error: Error) {
        // Our own cancel above, or a navigation replaced by the next one, is not a failure.
        if (error as NSError).code == NSURLErrorCancelled { return }
        signingIn = false
        if !quitting && !serviceStopped {
            showMessage("Gaffer couldn't load its page. Quit Gaffer and open it again.")
        }
    }

    // MARK: Actions

    @objc func showWindow(_ sender: Any?) {
        NSApp.activate(ignoringOtherApps: true)
        window?.makeKeyAndOrderFront(sender)
    }

    @objc func showSettings(_ sender: Any?) {
        settings.show()
    }

    @objc func rescan(_ sender: Any?) {
        showWindow(sender)
        if let url = surfaceURL("window") { windowView?.load(URLRequest(url: url)) }
    }
}

// A write to the service's stdin after it has gone must not end Gaffer.
signal(SIGPIPE, SIG_IGN)
let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
