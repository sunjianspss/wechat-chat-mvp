import AppKit
import ApplicationServices
import CoreGraphics
import Foundation

func fail(_ message: String) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(1)
}

func appMatches(_ runningApp: NSRunningApplication, _ query: String) -> Bool {
    let lowered = query.lowercased()
    let aliases = aliasesFor(query)
    if let name = runningApp.localizedName?.lowercased(), aliases.contains(name) {
        return true
    }
    if let bundleIdentifier = runningApp.bundleIdentifier?.lowercased(), aliases.contains(bundleIdentifier) {
        return true
    }
    if aliases.contains(lowered) { return true }
    return false
}

func aliasesFor(_ query: String) -> Set<String> {
    let lowered = query.lowercased()
    if lowered == "wechat" || query == "微信" || lowered == "com.tencent.xinwechat" {
        return Set(["wechat", "微信", "com.tencent.xinwechat", "com.tencent.wechat"])
    }
    return Set([lowered])
}

func activateApp(_ query: String) {
    guard let app = NSWorkspace.shared.runningApplications.first(where: { appMatches($0, query) }) else {
        fail("App is not running: \(query)")
    }
    app.activate(options: [.activateAllWindows])
    if let bundleURL = app.bundleURL {
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.activates = true
        let semaphore = DispatchSemaphore(value: 0)
        NSWorkspace.shared.openApplication(at: bundleURL, configuration: configuration) { _, _ in
            semaphore.signal()
        }
        _ = semaphore.wait(timeout: .now() + 1.0)
    }
    raiseWindows(pid: app.processIdentifier)
}

func raiseWindows(pid: pid_t) {
    let axApp = AXUIElementCreateApplication(pid)
    AXUIElementSetAttributeValue(axApp, kAXFrontmostAttribute as CFString, kCFBooleanTrue)

    var rawWindows: CFTypeRef?
    let result = AXUIElementCopyAttributeValue(axApp, kAXWindowsAttribute as CFString, &rawWindows)
    guard result == .success, let windows = rawWindows as? [AXUIElement] else {
        return
    }
    for window in windows {
        AXUIElementPerformAction(window, kAXRaiseAction as CFString)
        AXUIElementSetAttributeValue(window, kAXMainAttribute as CFString, kCFBooleanTrue)
        AXUIElementSetAttributeValue(window, kAXFocusedAttribute as CFString, kCFBooleanTrue)
    }
}

func windowBounds(_ query: String) {
    let options: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
    guard let windows = CGWindowListCopyWindowInfo(options, kCGNullWindowID) as? [[String: Any]] else {
        fail("Cannot list windows")
    }
    let aliases = aliasesFor(query)
    var candidates: [(name: String, x: Double, y: Double, width: Double, height: Double)] = []
    for window in windows {
        let owner = (window[kCGWindowOwnerName as String] as? String ?? "").lowercased()
        let name = window[kCGWindowName as String] as? String ?? ""
        let layer = window[kCGWindowLayer as String] as? Int ?? -1
        guard aliases.contains(owner) && layer == 0 else {
            continue
        }
        guard let bounds = window[kCGWindowBounds as String] as? [String: Any],
              let x = bounds["X"] as? Double,
              let y = bounds["Y"] as? Double,
              let width = bounds["Width"] as? Double,
              let height = bounds["Height"] as? Double,
              width > 100,
              height > 100 else {
            continue
        }
        candidates.append((name: name, x: x, y: y, width: width, height: height))
    }
    if let chosen = candidates.first(where: { aliases.contains($0.name.lowercased()) })
        ?? candidates.sorted(by: { ($0.width * $0.height) < ($1.width * $1.height) }).first {
        print("\(Int(chosen.x)),\(Int(chosen.y)),\(Int(chosen.width)),\(Int(chosen.height))")
        return
    }
    fail("No visible window found for app: \(query)")
}

func postPageUp(count: Int) {
    let keyCode: CGKeyCode = 116
    for _ in 0..<max(1, count) {
        CGEvent(keyboardEventSource: nil, virtualKey: keyCode, keyDown: true)?.post(tap: .cghidEventTap)
        usleep(30_000)
        CGEvent(keyboardEventSource: nil, virtualKey: keyCode, keyDown: false)?.post(tap: .cghidEventTap)
        usleep(60_000)
    }
}

func moveMouse(x: Double, y: Double) {
    let point = CGPoint(x: x, y: y)
    CGEvent(mouseEventSource: nil, mouseType: .mouseMoved, mouseCursorPosition: point, mouseButton: .left)?
        .post(tap: .cghidEventTap)
    usleep(80_000)
}

func clickMouse(x: Double, y: Double) {
    let point = CGPoint(x: x, y: y)
    moveMouse(x: x, y: y)
    CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left)?
        .post(tap: .cghidEventTap)
    usleep(40_000)
    CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left)?
        .post(tap: .cghidEventTap)
    usleep(120_000)
}

func postScrollUp(count: Int, x: Double? = nil, y: Double? = nil) {
    if let x = x, let y = y {
        moveMouse(x: x, y: y)
    }
    for _ in 0..<max(1, count) {
        CGEvent(
            scrollWheelEvent2Source: nil,
            units: .line,
            wheelCount: 1,
            wheel1: 8,
            wheel2: 0,
            wheel3: 0
        )?.post(tap: .cghidEventTap)
        usleep(60_000)
    }
}

let args = CommandLine.arguments
guard args.count >= 2 else {
    fail("Usage: mac_control <bounds|activate|click|pageup|wheel|wheelAt> ...")
}

switch args[1] {
case "bounds":
    guard args.count >= 3 else { fail("Usage: mac_control bounds <app-name>") }
    windowBounds(args[2])
case "activate":
    guard args.count >= 3 else { fail("Usage: mac_control activate <app-name>") }
    activateApp(args[2])
case "click":
    guard args.count >= 4, let x = Double(args[2]), let y = Double(args[3]) else {
        fail("Usage: mac_control click <x> <y>")
    }
    clickMouse(x: x, y: y)
case "pageup":
    let count = args.count >= 3 ? (Int(args[2]) ?? 1) : 1
    postPageUp(count: count)
case "wheel":
    let count = args.count >= 3 ? (Int(args[2]) ?? 1) : 1
    postScrollUp(count: count)
case "wheelAt":
    guard args.count >= 5,
          let x = Double(args[2]),
          let y = Double(args[3]),
          let count = Int(args[4]) else {
        fail("Usage: mac_control wheelAt <x> <y> <count>")
    }
    postScrollUp(count: count, x: x, y: y)
default:
    fail("Unknown command: \(args[1])")
}
