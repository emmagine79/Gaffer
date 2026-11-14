// Compiled by test_quit.py together with mac/Sources/ServiceProcess.swift and ServiceLog.swift
// (this file as main.swift). It starts the bundled light service the way Gaffer does, with no
// window, no menu bar and no Bluetooth (the service runs in --demo mode), then acts out the end.
//
//   service_process_check <resources dir> <data dir> <log dir> quit|wait|gone
//
// Prints "READY <port>" once the service is up.
//   quit: waits for a line on stdin, then calls ServiceProcess.stop(), what Quit Gaffer does.
//   wait: waits forever; the test kills this process the way a crash would.
//   gone: <resources dir> holds a stand-in python that exits at once. Waits for the stop to be
//         reported, then gives the secret to the dead service again and prints "SURVIVED" if
//         that did not end this process. Prints no READY.
import Foundation

// As in the app (main.swift): a write to a service that has gone must fail, not end this process.
signal(SIGPIPE, SIG_IGN)
let args = CommandLine.arguments
guard args.count == 5 else {
    FileHandle.standardError.write(Data("usage: resources data-dir log-dir quit|wait\n".utf8))
    exit(2)
}
let resources = URL(fileURLWithPath: args[1])
let dataDir = args[2]
let logDir = URL(fileURLWithPath: args[3])
let mode = args[4]

var port: Int?
var stopped = false
let service = ServiceProcess(resources: resources, extraArguments: ["--demo", "--data", dataDir], logDirectory: logDir) { event in
    switch event {
    case .ready(let p): port = p
    case .stopped: stopped = true
    }
}
do { try service.start() } catch {
    print("FAILED \(error)")
    exit(1)
}
if mode == "gone" {
    let deadline = Date(timeIntervalSinceNow: 30)
    while !stopped && Date() < deadline {
        RunLoop.main.run(mode: .default, before: Date(timeIntervalSinceNow: 0.05))
    }
    guard stopped else { print("FAILED the stop was not reported"); exit(1) }
    service.sendSecret()  // the pipe has no reader now: the old write(_:) crashes here
    print("SURVIVED")
    exit(0)
}
// The service's events arrive on the main queue, so keep the main run loop turning.
let deadline = Date(timeIntervalSinceNow: 60)
while port == nil && !stopped && Date() < deadline {
    RunLoop.main.run(mode: .default, before: Date(timeIntervalSinceNow: 0.05))
}
guard let readyPort = port else {
    print("FAILED the service did not announce a port")
    exit(1)
}
print("READY \(readyPort)")
fflush(stdout)

if mode == "quit" {
    _ = readLine()  // the test says when
    service.stop()
    print("STOPPED")
    fflush(stdout)
} else {
    while true { RunLoop.main.run(mode: .default, before: Date(timeIntervalSinceNow: 1)) }
}
