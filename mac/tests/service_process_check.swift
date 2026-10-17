// Compiled by test_quit.py together with mac/Sources/ServiceProcess.swift and ServiceLog.swift
// (this file as main.swift). It starts the bundled light service the way Gaffer does, with no
// window, no menu bar and no Bluetooth (the service runs in --demo mode), then acts out the end.
//
//   service_process_check <resources dir> <data dir> <log dir> quit|wait
//
// Prints "READY <port>" once the service is up.
//   quit: waits for a line on stdin, then calls ServiceProcess.stop(), what Quit Gaffer does.
//   wait: waits forever; the test kills this process the way a crash would.
import Foundation

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
