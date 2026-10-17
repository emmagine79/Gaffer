import AppKit

/// A button that records a key combination when clicked.
final class RecorderButton: NSButton {
    var shortcut: Shortcut? { didSet { refresh() } }
    /// Called with the new shortcut (nil = cleared). Returns a reason to refuse it, or nil to accept.
    var onChange: ((Shortcut?) -> String?)?
    var onHint: ((String?) -> Void)?
    /// True when recording starts, false when it ends (saved, cancelled or clicked away).
    var onRecording: ((Bool) -> Void)?
    private var recording = false {
        didSet {
            refresh()
            if recording != oldValue { onRecording?(recording) }
        }
    }

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        bezelStyle = .rounded
        setButtonType(.momentaryPushIn)
        target = self
        action = #selector(toggle)
    }

    required init?(coder: NSCoder) { fatalError("not used") }

    override var acceptsFirstResponder: Bool { true }

    @objc private func toggle() {
        if recording {
            recording = false
        } else {
            recording = true
            onHint?(nil)
            window?.makeFirstResponder(self)
        }
    }

    private func refresh() {
        if recording {
            title = "Press the keys…"
        } else {
            title = shortcut?.display ?? "Record shortcut"
        }
        setAccessibilityLabel(shortcut.map { "Shortcut \($0.display)" } ?? "No shortcut")
    }

    /// End recording without saving. The window calls this when it closes or loses focus.
    func cancelRecording() {
        recording = false
    }

    override func resignFirstResponder() -> Bool {
        recording = false
        return super.resignFirstResponder()
    }

    override func performKeyEquivalent(with event: NSEvent) -> Bool {
        guard recording else { return super.performKeyEquivalent(with: event) }
        capture(event)
        return true  // swallow it, so Cmd-W and friends don't act while recording
    }

    override func keyDown(with event: NSEvent) {
        guard recording else { return super.keyDown(with: event) }
        capture(event)
    }

    private func capture(_ event: NSEvent) {
        switch Int(event.keyCode) {
        case 53:  // Escape: cancel
            recording = false
        case 51, 117:  // Delete: clear
            finish(nil)
        default:
            guard let new = Shortcut(event: event) else {
                onHint?("Hold Control, Option or Command with the key.")
                return
            }
            finish(new)
        }
    }

    private func finish(_ new: Shortcut?) {
        recording = false
        if let reason = onChange?(new) {
            onHint?(reason)
        } else {
            shortcut = new
            onHint?(nil)
        }
    }
}

/// The Settings window: one row per global shortcut.
final class SettingsWindowController: NSWindowController, NSWindowDelegate {
    private let store: ShortcutStore
    private let hotKeys: HotKeyCenter
    private var recorders: [ShortcutAction: RecorderButton] = [:]
    private var notes: [ShortcutAction: NSTextField] = [:]

    init(store: ShortcutStore, hotKeys: HotKeyCenter) {
        self.store = store
        self.hotKeys = hotKeys
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 460, height: 200),
                              styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "Gaffer Settings"
        window.isReleasedWhenClosed = false
        super.init(window: window)
        window.delegate = self
        window.contentView = buildContent()
        window.setContentSize(window.contentView!.fittingSize)
        window.center()
        refreshProblems(hotKeys.reload())
    }

    required init?(coder: NSCoder) { fatalError("not used") }

    private func buildContent() -> NSView {
        let intro = NSTextField(wrappingLabelWithString:
            "These shortcuts work in any app. Look 1 to 9 are the first nine looks in your list, in order.")
        intro.preferredMaxLayoutWidth = 420

        let rows = NSStackView(views: ShortcutAction.all.map(row(for:)))
        rows.orientation = .vertical
        rows.alignment = .leading
        rows.spacing = 6

        let reset = NSButton(title: "Reset to defaults", target: self, action: #selector(resetAll))
        let stack = NSStackView(views: [intro, rows, reset])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 14
        stack.edgeInsets = NSEdgeInsets(top: 20, left: 20, bottom: 20, right: 20)
        return stack
    }

    private func row(for action: ShortcutAction) -> NSView {
        let label = NSTextField(labelWithString: action.title)
        label.widthAnchor.constraint(equalToConstant: 80).isActive = true

        let recorder = RecorderButton(frame: .zero)
        recorder.widthAnchor.constraint(equalToConstant: 150).isActive = true
        recorder.shortcut = store.shortcut(for: action)
        recorder.onChange = { [weak self] new in self?.record(new, for: action) }
        recorder.onHint = { [weak self] text in self?.setNote(text, for: action) }
        recorder.onRecording = { [weak self] on in
            guard let self else { return }
            if on { self.hotKeys.suspend() } else { self.refreshProblems(self.hotKeys.reload()) }
        }
        recorders[action] = recorder

        let note = NSTextField(labelWithString: "")
        note.textColor = .systemRed
        note.font = .systemFont(ofSize: NSFont.smallSystemFontSize)
        notes[action] = note

        let row = NSStackView(views: [label, recorder, note])
        row.spacing = 10
        return row
    }

    private func setNote(_ text: String?, for action: ShortcutAction) {
        notes[action]?.stringValue = text ?? ""
    }

    /// Save a recorded shortcut. Returns a reason to refuse it.
    private func record(_ new: Shortcut?, for action: ShortcutAction) -> String? {
        if let new, let other = store.owner(of: new, besides: action) {
            return "\(other.title) already uses \(new.display)."
        }
        store.set(new, for: action)
        refreshProblems(hotKeys.reload())
        return nil
    }

    private func refreshProblems(_ problems: [ShortcutAction: HotKeyCenter.Problem]) {
        for action in ShortcutAction.all {
            switch problems[action] {
            case .taken?: setNote("Another app uses this.", for: action)
            case .failed?: setNote("Couldn't be set.", for: action)
            case nil: setNote(nil, for: action)
            }
        }
    }

    @objc private func resetAll() {
        store.resetAll()
        for action in ShortcutAction.all { recorders[action]?.shortcut = store.shortcut(for: action) }
        refreshProblems(hotKeys.reload())
    }

    // Closing the window, or switching to another app, does not resign the first
    // responder, so the button would stay in "recording" with every global shortcut
    // let go (hotKeys.suspend). End it here so reload() puts them back.
    func windowWillClose(_ notification: Notification) { cancelAllRecording() }
    func windowDidResignKey(_ notification: Notification) { cancelAllRecording() }

    private func cancelAllRecording() {
        for recorder in recorders.values { recorder.cancelRecording() }
    }

    func show() {
        NSApp.activate(ignoringOtherApps: true)
        window?.makeKeyAndOrderFront(nil)
    }
}
