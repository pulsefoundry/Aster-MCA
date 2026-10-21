import AppKit
import WebKit

final class AsterApp: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate {
    private var window: NSWindow!
    private var web: WKWebView!
    private var status: NSTextField!
    private var progress: NSProgressIndicator!
    private var backend: Process?
    private var readyTimer: Timer?
    private var sessionFolder: URL?
    private var dataRoot: URL!
    private var logURL: URL!
    private var logHandle: FileHandle?
    private var baseURL: URL?
    private var quitting = false
    private var pendingQuit = false
    private var startupDeadline = Date()

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let fm = FileManager.default
        let resources = Bundle.main.resourceURL!
        let fallback = fm.homeDirectoryForCurrentUser.appendingPathComponent("Documents/Aster Nano")
        if let config = try? Data(contentsOf: resources.appendingPathComponent("workspace.json")),
           let object = try? JSONSerialization.jsonObject(with: config) as? [String: String],
           let path = object["workspace"],
           fm.fileExists(atPath: path + "/work/at32-continuous-2026-10-14") {
            dataRoot = URL(fileURLWithPath: path)
        } else { dataRoot = fallback }
        let logs = fm.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/Aster Nano")
        do {
            try fm.createDirectory(at: logs, withIntermediateDirectories: true)
            try fm.createDirectory(at: dataRoot.appendingPathComponent("work/at32-gui-recordings"), withIntermediateDirectories: true)
        } catch { fail("无法创建数据目录", detail: error.localizedDescription); return }
        logURL = logs.appendingPathComponent("desktop-\(Int(Date().timeIntervalSince1970)).log")
        configureMenu()
        configureWindow()
        startBackend(resources: resources)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func configureMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem(); let app = NSMenu(); appItem.submenu = app
        app.addItem(withTitle: "关于 Aster Nano", action: #selector(about), keyEquivalent: "").target = self
        app.addItem(.separator())
        app.addItem(withTitle: "隐藏 Aster Nano", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        app.addItem(.separator())
        app.addItem(withTitle: "退出 Aster Nano", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        main.addItem(appItem)
        let fileItem = NSMenuItem(); fileItem.title = "文件"; let file = NSMenu(title: "文件"); fileItem.submenu = file
        file.addItem(withTitle: "打开采集数据文件夹", action: #selector(openData), keyEquivalent: "o").target = self
        file.addItem(withTitle: "查看运行日志", action: #selector(openLogs), keyEquivalent: "").target = self
        file.addItem(.separator())
        file.addItem(withTitle: "关闭窗口", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        main.addItem(fileItem)
        let editItem = NSMenuItem(); editItem.title = "编辑"; let edit = NSMenu(title: "编辑"); editItem.submenu = edit
        for (title, action, key) in [("撤销", "undo:", "z"), ("剪切", "cut:", "x"), ("复制", "copy:", "c"), ("粘贴", "paste:", "v"), ("全选", "selectAll:", "a")] {
            edit.addItem(withTitle: title, action: Selector(action), keyEquivalent: key)
        }
        main.addItem(editItem)
        let windowItem = NSMenuItem(); windowItem.title = "窗口"; let windows = NSMenu(title: "窗口"); windowItem.submenu = windows
        windows.addItem(withTitle: "最小化", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windows.addItem(withTitle: "缩放", action: #selector(NSWindow.performZoom(_:)), keyEquivalent: "")
        main.addItem(windowItem); NSApp.windowsMenu = windows
        NSApp.mainMenu = main
    }

    private func configureWindow() {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1190, height: 900),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Aster Nano · 能谱"
        window.minSize = NSSize(width: 950, height: 700)
        window.delegate = self
        window.isReleasedWhenClosed = false
        window.setFrameAutosaveName("AsterNanoSpectrum")
        window.center()
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        web = WKWebView(frame: window.contentView!.bounds, configuration: config)
        web.autoresizingMask = [.width, .height]
        web.navigationDelegate = self
        web.isHidden = true
        window.contentView!.addSubview(web)
        status = NSTextField(labelWithString: "正在打开本地能谱…")
        status.font = .systemFont(ofSize: 17)
        status.alignment = .center
        status.translatesAutoresizingMaskIntoConstraints = false
        progress = NSProgressIndicator()
        progress.style = .spinning; progress.controlSize = .regular
        progress.translatesAutoresizingMaskIntoConstraints = false
        window.contentView!.addSubview(status); window.contentView!.addSubview(progress)
        NSLayoutConstraint.activate([
            status.centerXAnchor.constraint(equalTo: window.contentView!.centerXAnchor),
            status.centerYAnchor.constraint(equalTo: window.contentView!.centerYAnchor),
            progress.centerXAnchor.constraint(equalTo: status.centerXAnchor),
            progress.bottomAnchor.constraint(equalTo: status.topAnchor, constant: -20)
        ])
        progress.startAnimation(nil)
        window.makeKeyAndOrderFront(nil)
    }

    private func startBackend(resources: URL) {
        do {
            let folder = FileManager.default.temporaryDirectory.appendingPathComponent("AsterNano-\(UUID().uuidString)")
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            sessionFolder = folder
            let ready = folder.appendingPathComponent("ready.json")
            FileManager.default.createFile(atPath: logURL.path, contents: nil)
            logHandle = try FileHandle(forWritingTo: logURL)
            let task = Process()
            task.executableURL = resources.appendingPathComponent("backend/aster-backend")
            task.arguments = ["--desktop", "--port", "8775", "--ready-file", ready.path, "--parent-pid", String(ProcessInfo.processInfo.processIdentifier)]
            task.environment = ["PATH":"/usr/bin:/bin", "HOME":FileManager.default.homeDirectoryForCurrentUser.path,
                                "ASTER_DATA_ROOT":dataRoot.path, "PYTHONUNBUFFERED":"1", "LC_CTYPE":"UTF-8"]
            task.standardOutput = logHandle; task.standardError = logHandle
            // Python bootstrapping calls getcwd before our application starts.
            // Use the local session directory; all acquisition paths already
            // use the explicit ASTER_DATA_ROOT passed above.
            task.currentDirectoryURL = folder
            task.terminationHandler = { [weak self] process in
                DispatchQueue.main.async { self?.backendEnded(code: process.terminationStatus) }
            }
            backend = task
            try task.run()
            startupDeadline = Date().addingTimeInterval(20)
            readyTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
                self?.checkReady(file: ready)
            }
        } catch { fail("无法启动采集程序", detail: error.localizedDescription) }
    }

    private func checkReady(file: URL) {
        if quitting { return }
        if let data = try? Data(contentsOf: file),
           let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let text = payload["url"] as? String, let url = URL(string: text),
           url.scheme == "http", url.host == "127.0.0.1", url.port == 8775,
           let pid = payload["pid"] as? Int, pid == Int(backend?.processIdentifier ?? 0) {
            readyTimer?.invalidate(); readyTimer = nil
            baseURL = url; web.load(URLRequest(url: url))
        } else if Date() > startupDeadline {
            readyTimer?.invalidate(); readyTimer = nil
            fail("启动时间过长", detail: "请查看运行日志。退出时会停止本应用的采集进程。")
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard !quitting else { return }
        web.isHidden = false; status.isHidden = true; progress.stopAnimation(nil); progress.isHidden = true
    }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        if !quitting { fail("能谱窗口加载失败", detail: error.localizedDescription) }
    }
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        let url = action.request.url
        decisionHandler(url?.scheme == baseURL?.scheme && url?.host == "127.0.0.1" && url?.port == 8775 ? .allow : .cancel)
    }

    private func backendEnded(code: Int32) {
        readyTimer?.invalidate(); readyTimer = nil
        if quitting {
            cleanup()
            if pendingQuit { NSApp.reply(toApplicationShouldTerminate: true) }
        } else {
            fail("采集程序已退出", detail: "请重新打开应用。若网页版程序仍在运行，请先退出它；同时只能运行一个采集程序。\n退出码：\(code)\n日志：\(logURL?.path ?? "无")")
        }
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool { NSApp.terminate(nil); return false }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if quitting { return pendingQuit ? .terminateLater : .terminateNow }
        quitting = true
        readyTimer?.invalidate(); readyTimer = nil
        if let task = backend, task.isRunning {
            pendingQuit = true
            web.isHidden = true; status.stringValue = "正在停止采集、校验并保存…"
            status.isHidden = false; progress.isHidden = false; progress.startAnimation(nil)
            task.terminate()
            return .terminateLater
        }
        cleanup(); return .terminateNow
    }
    private func cleanup() {
        try? logHandle?.close()
        if let folder = sessionFolder { try? FileManager.default.removeItem(at: folder) }
    }
    private func fail(_ message: String, detail: String) {
        let alert = NSAlert(); alert.messageText = message; alert.informativeText = detail
        alert.alertStyle = .warning; alert.addButton(withTitle: "退出")
        alert.runModal(); NSApp.terminate(nil)
    }
    @objc private func openData() { NSWorkspace.shared.open(dataRoot.appendingPathComponent("work/at32-gui-recordings")) }
    @objc private func openLogs() { if let url = logURL { NSWorkspace.shared.activateFileViewerSelecting([url]) } }
    @objc private func about() {
        NSApp.orderFrontStandardAboutPanel(options: [
            .applicationName: "Aster Nano", .applicationVersion: "0.2 · 桌面版",
            .version: "AT32 · 1 MS/s · 道数谱", .credits: NSAttributedString(string: "本机采集与处理，完整原始波形自动保存。\n当前谱未做能量标定。")
        ])
    }
}

let app = NSApplication.shared
let delegate = AsterApp()
app.delegate = delegate
app.run()
