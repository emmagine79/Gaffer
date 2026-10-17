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
/// (see service/gaffer/session.py). The service exits when that pipe
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
    /// Where the bundled Python lives (Gaffer.app/Contents/Resources). Tests point it at a copy.
    private let resources: URL?
    /// Extra service options. Only tests use them (for example --demo, which starts no Bluetooth scan).
    private let extraArguments: [String]
    /// Where service.log goes. nil means ~/Library/Logs/Gaffer.
    private let logDirectory: URL?
    /// Random secret for this launch: 32 bytes from the system's secure generator, as hex.
    let secret: String = {
        var bytes = [UInt8](repeating: 0, count: 32)
        guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else {
            fatalError("no secure random bytes")
        }
        return bytes.map { String(format: "%02x", $0) }.joined()
    }()

    init(resources: URL? = nil, extraArguments: [String] = [], logDirectory: URL? = nil,
         onEvent: @escaping (Event) -> Void) {
        self.resources = resources
        self.extraArguments = extraArguments
        self.logDirectory = logDirectory
        self.onEvent = onEvent
    }

    func start() throws {
        guard let resources = resources ?? Bundle.main.resourceURL else {
            throw CocoaError(.fileNoSuchFile)
        }
        let python = resources.appendingPathComponent("python/bin/python3.14")
        process.executableURL = python
        // -I: ignore PYTHON* variables and the user's site-packages. -B: never write
        // .pyc files into the signed bundle.
        process.arguments = ["-I", "-B", "-m", "gaffer", "--session-from-stdin"] + extraArguments
        process.environment = Self.cleanEnvironment()
        process.currentDirectoryURL = resources
        process.standardInput = stdinPipe
        process.standardOutput = stdoutPipe
        let logFolder = logDirectory ?? ServiceLog.defaultDirectory
        let log = ServiceLog.open(in: logFolder)
        if log == nil {
            // NSLog writes to the unified log (and to stderr), so there is a trace of why the service has no log file.
            NSLog("Gaffer: could not open service.log in %@, so the light service will log nowhere", logFolder.path)
        }
        process.standardError = log ?? FileHandle.nullDevice

        stdoutPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let chunk = handle.availableData
            guard !chunk.isEmpty else {
                // End of file: the service has gone. Without this the handler fires
                // again at once, forever, and Gaffer keeps several cores busy.
                handle.readabilityHandler = nil
                return
            }
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
}
