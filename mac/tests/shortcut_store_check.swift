// Compiled by test_shell.py together with mac/Sources/Shortcuts.swift (as main.swift here).
// Checks ShortcutStore.owner(of:) on a throwaway UserDefaults suite. Prints one line.
import Carbon
import Foundation

let suite = "work.awelahlayray.gaffer.storecheck\(ProcessInfo.processInfo.processIdentifier)"
let defaults = UserDefaults(suiteName: suite)!
defer { defaults.removePersistentDomain(forName: suite) }
let store = ShortcutStore(defaults: defaults)
let mods = UInt32(controlKey | optionKey)

// Look 1 holds Control-Option-3, saved with a label that reads differently from a fresh recording.
store.set(Shortcut(keyCode: UInt32(kVK_ANSI_3), modifiers: mods, label: "three"), for: .look(1))
store.set(nil, for: .look(3))  // Look 3's default is also Control-Option-3; clear it so only Look 1 holds it

let recorded = Shortcut(keyCode: UInt32(kVK_ANSI_3), modifiers: mods, label: "3")
let owner = store.owner(of: recorded, besides: .look(2))
print(owner.map { $0.title } ?? "none")
