import AppKit
import Carbon

/// Global shortcuts: look slots 1 to 9, All off, Next cue.
///
/// Registered with Carbon's RegisterEventHotKey, the system call that sindresorhus/
/// KeyboardShortcuts wraps. That package is SwiftPM-only (and loads a resource
/// bundle), while Gaffer builds with one swiftc line, so the call is used directly.
/// It needs no Accessibility or Input Monitoring permission and works while any
/// other app is frontmost.

enum ShortcutAction: Hashable {
    case look(Int)  // slot 1 to 9
    case allOff
    case nextCue

    static let lookSlots = 1...9
    static let all: [ShortcutAction] = lookSlots.map { .look($0) } + [.allOff, .nextCue]

    /// Key in UserDefaults.
    var storageKey: String {
        switch self {
        case .look(let slot): return "look\(slot)"
        case .allOff: return "allOff"
        case .nextCue: return "nextCue"
        }
    }

    var title: String {
        switch self {
        case .look(let slot): return "Look \(slot)"
        case .allOff: return "All off"
        case .nextCue: return "Next cue"
        }
    }

    /// Captain, 17 Oct 2026: Control-Option-1 to 9 for looks, Control-Option-0 for
    /// All off, Control-Option-Space for Next cue.
    var defaultShortcut: Shortcut {
        let mods = UInt32(controlKey | optionKey)
        let digits = [kVK_ANSI_1, kVK_ANSI_2, kVK_ANSI_3, kVK_ANSI_4, kVK_ANSI_5,
                      kVK_ANSI_6, kVK_ANSI_7, kVK_ANSI_8, kVK_ANSI_9]
        switch self {
        case .look(let slot):
            return Shortcut(keyCode: UInt32(digits[slot - 1]), modifiers: mods, label: "\(slot)")
        case .allOff:
            return Shortcut(keyCode: UInt32(kVK_ANSI_0), modifiers: mods, label: "0")
        case .nextCue:
            return Shortcut(keyCode: UInt32(kVK_Space), modifiers: mods, label: "Space")
        }
    }
}

struct Shortcut: Equatable {
    var keyCode: UInt32
    /// Carbon modifier mask (controlKey, optionKey, cmdKey, shiftKey).
    var modifiers: UInt32
    /// How the key reads on screen, saved when it was recorded.
    var label: String

    /// Modifiers a global shortcut must include, so it can't take over plain typing.
    static let requiredModifiers = UInt32(controlKey | optionKey | cmdKey)

    var display: String {
        var text = ""
        if modifiers & UInt32(controlKey) != 0 { text += "⌃" }
        if modifiers & UInt32(optionKey) != 0 { text += "⌥" }
        if modifiers & UInt32(shiftKey) != 0 { text += "⇧" }
        if modifiers & UInt32(cmdKey) != 0 { text += "⌘" }
        return text + label
    }

    static func carbonModifiers(_ flags: NSEvent.ModifierFlags) -> UInt32 {
        var mods: UInt32 = 0
        if flags.contains(.control) { mods |= UInt32(controlKey) }
        if flags.contains(.option) { mods |= UInt32(optionKey) }
        if flags.contains(.shift) { mods |= UInt32(shiftKey) }
        if flags.contains(.command) { mods |= UInt32(cmdKey) }
        return mods
    }

    /// Names for keys whose character is blank or unreadable.
    private static let keyNames: [Int: String] = [
        kVK_Space: "Space", kVK_Return: "Return", kVK_Tab: "Tab",
        kVK_LeftArrow: "←", kVK_RightArrow: "→", kVK_UpArrow: "↑", kVK_DownArrow: "↓",
        kVK_F1: "F1", kVK_F2: "F2", kVK_F3: "F3", kVK_F4: "F4", kVK_F5: "F5", kVK_F6: "F6",
        kVK_F7: "F7", kVK_F8: "F8", kVK_F9: "F9", kVK_F10: "F10", kVK_F11: "F11", kVK_F12: "F12",
    ]

    init(keyCode: UInt32, modifiers: UInt32, label: String) {
        self.keyCode = keyCode
        self.modifiers = modifiers
        self.label = label
    }

    /// nil when the key press can't be a global shortcut.
    init?(event: NSEvent) {
        let mods = Shortcut.carbonModifiers(event.modifierFlags.intersection(.deviceIndependentFlagsMask))
        guard mods & Shortcut.requiredModifiers != 0 else { return nil }
        let code = Int(event.keyCode)
        let label = Shortcut.keyNames[code]
            ?? event.charactersIgnoringModifiers?.uppercased().trimmingCharacters(in: .whitespacesAndNewlines)
            ?? ""
        guard !label.isEmpty else { return nil }
        self.init(keyCode: UInt32(code), modifiers: mods, label: label)
    }
}

/// What the user chose, kept in UserDefaults as plain property-list values.
/// An action with no entry uses its default. A cleared one holds `cleared: true`.
final class ShortcutStore {
    private let defaults: UserDefaults
    private let key = "shortcuts.v1"

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    func shortcut(for action: ShortcutAction) -> Shortcut? {
        let saved = defaults.dictionary(forKey: key)?[action.storageKey] as? [String: Any]
        guard let saved else { return action.defaultShortcut }
        if saved["cleared"] as? Bool == true { return nil }
        guard let code = saved["keyCode"] as? Int, let mods = saved["modifiers"] as? Int,
              let label = saved["label"] as? String, code >= 0, mods >= 0 else {
            return action.defaultShortcut  // unreadable entry: fall back, never crash
        }
        return Shortcut(keyCode: UInt32(code), modifiers: UInt32(mods), label: label)
    }

    func set(_ shortcut: Shortcut?, for action: ShortcutAction) {
        var all = defaults.dictionary(forKey: key) ?? [:]
        if let shortcut {
            all[action.storageKey] = ["keyCode": Int(shortcut.keyCode), "modifiers": Int(shortcut.modifiers),
                                      "label": shortcut.label] as [String: Any]
        } else {
            all[action.storageKey] = ["cleared": true]
        }
        defaults.set(all, forKey: key)
    }

    func resetAll() {
        defaults.removeObject(forKey: key)
    }

    /// The other action that already uses this key combination, if any.
    func owner(of shortcut: Shortcut, besides action: ShortcutAction) -> ShortcutAction? {
        ShortcutAction.all.first { $0 != action && self.shortcut(for: $0) == shortcut }
    }
}

/// Registers the store's shortcuts with the system and reports presses.
final class HotKeyCenter {
    enum Problem: Equatable {
        case taken      // another app already holds this combination
        case failed
    }

    private let store: ShortcutStore
    private var refs: [UInt32: EventHotKeyRef] = [:]
    private var actions: [UInt32: ShortcutAction] = [:]
    private var handler: EventHandlerRef?
    var onPress: ((ShortcutAction) -> Void)?

    init(store: ShortcutStore) {
        self.store = store
    }

    deinit {
        unregisterAll()
        if let handler { RemoveEventHandler(handler) }
    }

    /// Install the system event handler once, then register the saved shortcuts.
    /// Returns the actions whose shortcut could not be registered.
    @discardableResult
    func start() -> [ShortcutAction: Problem] {
        if handler == nil {
            var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
            let status = InstallEventHandler(GetApplicationEventTarget(), { _, event, userData in
                guard let event, let userData else { return OSStatus(eventNotHandledErr) }
                var id = EventHotKeyID()
                let got = GetEventParameter(event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID),
                                            nil, MemoryLayout<EventHotKeyID>.size, nil, &id)
                guard got == noErr else { return got }
                Unmanaged<HotKeyCenter>.fromOpaque(userData).takeUnretainedValue().pressed(id.id)
                return noErr
            }, 1, &spec, Unmanaged.passUnretained(self).toOpaque(), &handler)
            if status != noErr {
                NSLog("Gaffer: could not listen for shortcuts (status \(status))")
                return Dictionary(uniqueKeysWithValues: ShortcutAction.all.map { ($0, Problem.failed) })
            }
        }
        return reload()
    }

    /// Register again from the store. Call after any change.
    @discardableResult
    func reload() -> [ShortcutAction: Problem] {
        unregisterAll()
        var problems: [ShortcutAction: Problem] = [:]
        for (index, action) in ShortcutAction.all.enumerated() {
            guard let shortcut = store.shortcut(for: action) else { continue }
            let id = UInt32(index + 1)
            var ref: EventHotKeyRef?
            let status = RegisterEventHotKey(shortcut.keyCode, shortcut.modifiers,
                                             EventHotKeyID(signature: OSType(0x47414646), id: id),  // 'GAFF'
                                             GetApplicationEventTarget(), 0, &ref)
            if status == noErr, let ref {
                refs[id] = ref
                actions[id] = action
            } else {
                problems[action] = status == OSStatus(eventHotKeyExistsErr) ? .taken : .failed
                NSLog("Gaffer: shortcut for \(action.title) not registered (status \(status))")
            }
        }
        return problems
    }

    /// Let go of every shortcut while one is being recorded, so pressing a combo
    /// that is already in use records it instead of running it. Call reload() after.
    func suspend() {
        unregisterAll()
    }

    private func unregisterAll() {
        for ref in refs.values { UnregisterEventHotKey(ref) }
        refs.removeAll()
        actions.removeAll()
    }

    private func pressed(_ id: UInt32) {
        if let action = actions[id] { onPress?(action) }
    }
}
