import Foundation

/// The service's log file, ~/Library/Logs/Gaffer/service.log.
///
/// It can't grow without bound: each launch moves the last run's log to
/// service.previous.log (replacing the one before it) and starts a new service.log.
/// So there are at most two files, this run's and the previous run's. The rule has no
/// size figure, because none is set by any platform or contract; a single run's log
/// is only as long as that run.
enum ServiceLog {
    static let currentName = "service.log"
    static let previousName = "service.previous.log"

    static var defaultDirectory: URL {
        let library = FileManager.default.urls(for: .libraryDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library")
        return library.appendingPathComponent("Logs/Gaffer", isDirectory: true)
    }

    /// Rotate the log in `directory`, then open a fresh service.log for writing.
    /// Returns nil when the folder or file can't be made; the service then logs nowhere.
    static func open(in directory: URL) -> FileHandle? {
        let fm = FileManager.default
        try? fm.createDirectory(at: directory, withIntermediateDirectories: true)
        let current = directory.appendingPathComponent(currentName)
        let previous = directory.appendingPathComponent(previousName)
        // rename(2) replaces the old previous log in one step, so a crash half-way
        // never leaves the folder without a previous log it already had.
        if fm.fileExists(atPath: current.path) {
            rename(current.path, previous.path)
        }
        // Readable by this user only: the log can name lights and addresses.
        guard fm.createFile(atPath: current.path, contents: nil, attributes: [.posixPermissions: 0o600]) else {
            return nil
        }
        return try? FileHandle(forWritingTo: current)
    }
}
