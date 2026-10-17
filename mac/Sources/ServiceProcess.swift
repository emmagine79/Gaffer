import Foundation
import Security

/// Runs Gaffer's Python light service from inside the app bundle.
///
/// The interpreter is the bundled copy at Contents/Resources/python, so no system
/// Python is used. It is started with Foundation's Process, which makes Gaffer the
/// child's "responsible process": macOS then checks Bluetooth permission against
/// Gaffer's Info.plist and shows the prompt in Gaffer's name.
///
/// The child's stdin is a pipe whose write end only Gaffer holds. Its first line is
/// a random session secret made at each launch; the window signs in with it once
/// (see service/src/gaffer_service/session.py). The service exits when that pipe
/// closes, and the kernel closes it however Gaffer ends (Quit, crash, SIGINT,
/// SIGKILL), so the service can't be left running.
final class ServiceProcess {
    enum Event {
        case ready(port: Int)
        case stopped(status: Int32)
    }

    private let process = Process()
    private let stdinPipe = Pipe()
    private let stdoutPipe = Pipe()
    private var buffer = Data()
    private var announced = false
    private let onEvent: (Event) -> Void
    /// Random secret for this launch: 32 bytes from the system's secure generator, as hex.
    let secret: String = {
        var bytes = [UInt8](repeating: 0, count: 32)
        guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else {
            fatalError("no secure random bytes")
        }
        return bytes.map { String(format: "%02x", $0) }.joined()
    }()

    init(onEvent: @escaping (Event) -> Void) {
        self.onEvent = onEvent
    }

    func start() throws {
        guard let resources = Bundle.main.resourceURL else {
            throw CocoaError(.fileNoSuchFile)
        }
        let python = resources.appendingPathComponent("python/bin/python3.14")
        process.executableURL = python
        // -I: ignore PYTHON* variables and the user's site-packages. -B: never write
        // .pyc files into the signed bundle.
        process.arguments = ["-I", "-B", "-m", "gaffer_service", "--session-from-stdin"]
        process.environment = Self.cleanEnvironment()
        process.currentDirectoryURL = resources
        process.standardInput = stdinPipe
        process.standardOutput = stdoutPipe
        process.standardError = Self.logHandle() ?? FileHandle.nullDevice

        stdoutPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let chunk = handle.availableData
            DispatchQueue.main.async { self?.consume(chunk) }
        }
        process.terminationHandler = { [weak self] proc in
            let status = proc.terminationStatus
            DispatchQueue.main.async { self?.onEvent(.stopped(status: status)) }
        }
        try process.run()
        stdinPipe.fileHandleForWriting.write(Data((secret + "\n").utf8))
    }

    /// Stop the service and wait until it has gone.
    func stop() {
        try? stdinPipe.fileHandleForWriting.close()
        if process.isRunning {
            process.terminate()
            process.waitUntilExit()
        }
    }

    private func consume(_ chunk: Data) {
        guard !announced, !chunk.isEmpty else { return }
        buffer.append(chunk)
        guard let text = String(data: buffer, encoding: .utf8) else { return }
        for line in text.split(separator: "\n") where line.hasPrefix("GAFFER_SERVICE_READY port=") {
            if let port = Int(line.dropFirst("GAFFER_SERVICE_READY port=".count)) {
                announced = true
                buffer.removeAll()
                onEvent(.ready(port: port))
                return
            }
        }
    }

    /// The service gets only what it needs, so a user's shell setup (Homebrew PATH,
    /// PYTHONPATH and so on) can't change how it runs.
    private static func cleanEnvironment() -> [String: String] {
        let inherited = ProcessInfo.processInfo.environment
        var env: [String: String] = ["PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "en_US.UTF-8"]
        for key in ["HOME", "USER", "LOGNAME", "TMPDIR"] {
            if let value = inherited[key] { env[key] = value }
        }
        return env
    }

    /// Service log at ~/Library/Logs/Gaffer/service.log, for debugging.
    private static func logHandle() -> FileHandle? {
        let fm = FileManager.default
        guard let library = fm.urls(for: .libraryDirectory, in: .userDomainMask).first else { return nil }
        let dir = library.appendingPathComponent("Logs/Gaffer", isDirectory: true)
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
        let file = dir.appendingPathComponent("service.log")
        if !fm.fileExists(atPath: file.path) {
            fm.createFile(atPath: file.path, contents: nil)
        }
        guard let handle = try? FileHandle(forWritingTo: file) else { return nil }
        handle.seekToEndOfFile()
        return handle
    }
}
