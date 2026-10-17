import Foundation

/// Gaffer's side of contracts/api.md: the `look` WebSocket and the three HTTP calls
/// the shortcuts make. Everything runs on the main queue.
///
/// The shell made the session secret, so it sends the cookie itself and never needs
/// the one-time sign-in link for its own calls.
final class ServiceClient: NSObject, URLSessionWebSocketDelegate {
    enum Link: Equatable {
        case idle
        case connecting
        case connected
        case reconnecting
        case stopped
    }

    /// Why a call failed, in words a person can read. Never a path or a raw error.
    enum Failure: Error, Equatable {
        case notRunning
        case unreachable
        case noSuchLook(Int)
        case refused(String)

        var message: String {
            switch self {
            case .notRunning: return "Gaffer's light service isn't running."
            case .unreachable: return "Gaffer couldn't reach its light service."
            case .noSuchLook(let slot): return "There is no look in slot \(slot)."
            case .refused(let text): return text
            }
        }
    }

    /// Reconnect back-off: the first retry after 0.25 s, doubling each time, never
    /// more than 5 s apart. The numbers are a timing choice, not a contract: the
    /// first keeps the menu-bar name from lagging after a blip, the second keeps a
    /// service that is down from being polled more than a few times a second
    /// forever. The loop ends when stop() is called (the service process exited or
    /// Gaffer is quitting).
    static let firstRetry: TimeInterval = 0.25
    static let longestRetry: TimeInterval = 5

    /// How long one HTTP call may take before the press counts as failed, so a hung
    /// service ends a shortcut press with a beep instead of nothing.
    static let requestTimeout: TimeInterval = 5

    /// Current look name, or nil for none (or while the socket is down).
    var onLook: ((String?) -> Void)?
    var onLink: ((Link) -> Void)?
    private(set) var link: Link = .idle {
        didSet { if link != oldValue { onLink?(link) } }
    }

    private var port = 0
    private var secret = ""
    private var session: URLSession!
    private var task: URLSessionWebSocketTask?
    private var attempt = 0
    private var retry: DispatchWorkItem?
    private var stopped = true
    /// Bumped for every socket, so a late callback from an old one is ignored.
    private var generation = 0

    override init() {
        super.init()
        let config = URLSessionConfiguration.ephemeral
        config.httpShouldSetCookies = false
        config.timeoutIntervalForRequest = Self.requestTimeout
        session = URLSession(configuration: config, delegate: self, delegateQueue: .main)
    }

    // MARK: Lifecycle

    func start(port: Int, secret: String) {
        stop()
        self.port = port
        self.secret = secret
        stopped = false
        attempt = 0
        connect()
    }

    /// End for good: no more reconnects. Called when the service has gone.
    func stop() {
        stopped = true
        generation += 1
        retry?.cancel()
        retry = nil
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        link = .stopped
    }

    // MARK: WebSocket

    private func request(_ path: String, method: String = "GET") -> URLRequest {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(port)\(path)")!)
        request.httpMethod = method
        request.setValue("gaffer_session=\(secret)", forHTTPHeaderField: "Cookie")
        request.timeoutInterval = Self.requestTimeout
        return request
    }

    private func connect() {
        guard !stopped else { return }
        generation += 1
        let mine = generation
        link = attempt == 0 ? .connecting : .reconnecting
        var request = URLRequest(url: URL(string: "ws://127.0.0.1:\(port)/ws")!)
        request.setValue("gaffer_session=\(secret)", forHTTPHeaderField: "Cookie")
        let task = session.webSocketTask(with: request)
        self.task = task
        task.resume()
        listen(task, generation: mine)
    }

    private func listen(_ task: URLSessionWebSocketTask, generation mine: Int) {
        task.receive { [weak self] result in
            DispatchQueue.main.async {
                guard let self, mine == self.generation, !self.stopped else { return }
                switch result {
                case .success(let message):
                    if case .string(let text) = message { self.handle(text) }
                    self.listen(task, generation: mine)
                case .failure:
                    self.socketEnded()
                }
            }
        }
    }

    private func handle(_ text: String) {
        guard let data = text.data(using: .utf8),
              let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              object["type"] as? String == "look" else { return }
        onLook?(Self.cleanName(object["name"] as? String))
    }

    /// The name as it should read: no line breaks or control characters, and nil if empty.
    static func cleanName(_ raw: String?) -> String? {
        guard let raw else { return nil }
        let cleaned = String(raw.unicodeScalars.filter { !CharacterSet.controlCharacters.contains($0) })
            .trimmingCharacters(in: .whitespaces)
        return cleaned.isEmpty ? nil : cleaned
    }

    private func socketEnded() {
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        onLook?(nil)  // never show a look the service can no longer vouch for
        scheduleReconnect()
    }

    private func scheduleReconnect() {
        guard !stopped, retry == nil else { return }
        link = .reconnecting
        let delay = min(Self.firstRetry * pow(2, Double(attempt)), Self.longestRetry)
        attempt += 1
        let work = DispatchWorkItem { [weak self] in
            guard let self else { return }
            self.retry = nil
            self.connect()  // connect() checks `stopped` again
        }
        retry = work
        DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: work)
    }

    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask,
                    didOpenWithProtocol protocol: String?) {
        guard webSocketTask === task, !stopped else { return }
        attempt = 0
        link = .connected
    }

    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask,
                    didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) {
        guard webSocketTask === task, !stopped else { return }
        socketEnded()
    }

    // MARK: HTTP

    private func call(_ method: String, _ path: String,
                      completion: @escaping (Result<Data, Failure>) -> Void) {
        guard !stopped else { return completion(.failure(.notRunning)) }
        session.dataTask(with: request(path, method: method)) { data, response, error in
            DispatchQueue.main.async {
                guard error == nil, let http = response as? HTTPURLResponse else {
                    return completion(.failure(.unreachable))
                }
                if (200..<300).contains(http.statusCode) { return completion(.success(data ?? Data())) }
                let body = (try? JSONSerialization.jsonObject(with: data ?? Data())) as? [String: Any]
                let message = body?["message"] as? String
                completion(.failure(.refused(message ?? "Gaffer's light service said no (\(http.statusCode)).")))
            }
        }.resume()
    }

    /// Apply the look in slot 1 to 9: the Nth entry of GET /api/looks.
    func applyLook(slot: Int, completion: @escaping (Result<Void, Failure>) -> Void) {
        call("GET", "/api/looks") { [weak self] result in
            switch result {
            case .failure(let failure):
                completion(.failure(failure))
            case .success(let data):
                let looks = ((try? JSONSerialization.jsonObject(with: data)) as? [String: Any])?["looks"] as? [[String: Any]]
                guard let looks, slot >= 1, slot <= looks.count, let id = looks[slot - 1]["id"] as? String else {
                    return completion(.failure(.noSuchLook(slot)))
                }
                // {id} is one path segment: encode everything but unreserved characters.
                let unreserved = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
                guard let encoded = id.addingPercentEncoding(withAllowedCharacters: unreserved) else {
                    return completion(.failure(.noSuchLook(slot)))
                }
                self?.call("POST", "/api/looks/\(encoded)/apply") { completion($0.map { _ in () }) }
            }
        }
    }

    func allOff(completion: @escaping (Result<Void, Failure>) -> Void) {
        call("POST", "/api/all-off") { completion($0.map { _ in () }) }
    }

    func nextCue(completion: @escaping (Result<Void, Failure>) -> Void) {
        call("POST", "/api/cues/active/go") { completion($0.map { _ in () }) }
    }
}
