import AppKit
import Foundation
import WebKit
import Darwin

private enum HostError: LocalizedError {
    case missingResource(String)
    case portCollision
    case processExited(String)
    case startupTimedOut

    var errorDescription: String? {
        switch self {
        case .missingResource(let path):
            return "The application is incomplete because a required resource is missing: \(path)"
        case .portCollision:
            return "Another process is using one of OhIc's local ports. Quit any existing OhIc processes and open the app again."
        case .processExited(let service):
            return "The local \(service) service stopped during startup. Check ~/Library/Logs/OhIc for details."
        case .startupTimedOut:
            return "OhIc's local services did not become ready in time. Check ~/Library/Logs/OhIc for details."
        }
    }
}

private final class ServiceManager {
    private let resources: URL
    private let supportDirectory: URL
    private let logsDirectory: URL
    private var backendProcess: Process?
    private var frontendProcess: Process?
    private var logHandles: [FileHandle] = []
    private var ownsProcesses = false

    init() throws {
        guard let resources = Bundle.main.resourceURL else {
            throw HostError.missingResource("Contents/Resources")
        }
        self.resources = resources

        let fileManager = FileManager.default
        let library = try fileManager.url(
            for: .libraryDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        supportDirectory = library
            .appendingPathComponent("Application Support", isDirectory: true)
            .appendingPathComponent("OhIc", isDirectory: true)
        logsDirectory = library
            .appendingPathComponent("Logs", isDirectory: true)
            .appendingPathComponent("OhIc", isDirectory: true)

        for directory in [
            supportDirectory,
            supportDirectory.appendingPathComponent("data", isDirectory: true),
            supportDirectory.appendingPathComponent("cache", isDirectory: true),
            supportDirectory.appendingPathComponent("pycache", isDirectory: true),
            supportDirectory.appendingPathComponent("tmp", isDirectory: true),
            logsDirectory,
        ] {
            try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
        }
    }

    func start(completion: @escaping (Result<Void, Error>) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self else { return }
            let result: Result<Void, Error>
            do {
                try self.startSynchronously()
                result = .success(())
            } catch {
                self.stop()
                result = .failure(error)
            }
            DispatchQueue.main.async {
                completion(result)
            }
        }
    }

    private func startSynchronously() throws {
        var backendReady = isBackendReady()
        var frontendReady = isFrontendReady()

        if backendReady && frontendReady {
            return
        }
        if backendReady != frontendReady {
            // A second launch can overlap the first app's startup. Give the
            // partially ready pair a short window to become healthy before
            // reporting a genuine port collision.
            for _ in 0..<20 {
                Thread.sleep(forTimeInterval: 0.25)
                backendReady = isBackendReady()
                frontendReady = isFrontendReady()
                if backendReady && frontendReady {
                    return
                }
                if !backendReady && !frontendReady {
                    break
                }
            }
        }
        if backendReady != frontendReady {
            throw HostError.portCollision
        }

        let python = resources.appendingPathComponent("python/bin/python3")
        let backendEntry = resources.appendingPathComponent("backend_entry.py")
        let node = resources.appendingPathComponent("bin/node")
        let frontendEntry = resources.appendingPathComponent("frontend/server.js")
        for resource in [python, backendEntry, node, frontendEntry] where !FileManager.default.fileExists(atPath: resource.path) {
            throw HostError.missingResource(resource.path)
        }

        let environment = serviceEnvironment()
        backendProcess = try launch(
            executable: python,
            arguments: [backendEntry.path],
            workingDirectory: resources.appendingPathComponent("backend"),
            environment: environment,
            logName: "backend.log"
        )
        ownsProcesses = true
        frontendProcess = try launch(
            executable: node,
            arguments: [frontendEntry.path],
            workingDirectory: resources.appendingPathComponent("frontend"),
            environment: environment.merging(["HOSTNAME": "127.0.0.1", "PORT": "3000"]) { _, new in new },
            logName: "frontend.log"
        )

        for _ in 0..<240 {
            if backendProcess?.isRunning == false {
                throw HostError.processExited("analysis")
            }
            if frontendProcess?.isRunning == false {
                throw HostError.processExited("interface")
            }
            if isBackendReady() && isFrontendReady() {
                return
            }
            Thread.sleep(forTimeInterval: 0.25)
        }
        throw HostError.startupTimedOut
    }

    private func serviceEnvironment() -> [String: String] {
        var environment = ProcessInfo.processInfo.environment
        let cache = supportDirectory.appendingPathComponent("cache", isDirectory: true)
        environment["OHIC_DATA_DIR"] = supportDirectory.appendingPathComponent("data").path
        environment["PYTHONHOME"] = resources.appendingPathComponent("python").path
        environment["PYTHONPATH"] = [
            resources.appendingPathComponent("backend").path,
            resources.appendingPathComponent("python-packages").path,
        ].joined(separator: ":")
        environment["PYTHONPYCACHEPREFIX"] = supportDirectory.appendingPathComponent("pycache").path
        environment["XDG_CACHE_HOME"] = cache.path
        environment["MPLCONFIGDIR"] = cache.appendingPathComponent("matplotlib").path
        environment["TMPDIR"] = supportDirectory.appendingPathComponent("tmp").path
        environment["PATH"] = [
            resources.appendingPathComponent("bin").path,
            environment["PATH"] ?? "/usr/bin:/bin:/usr/sbin:/sbin",
        ].joined(separator: ":")
        environment["DYLD_LIBRARY_PATH"] = [
            resources.appendingPathComponent("lib").path,
            environment["DYLD_LIBRARY_PATH"],
        ].compactMap { $0 }.joined(separator: ":")
        return environment
    }

    private func launch(
        executable: URL,
        arguments: [String],
        workingDirectory: URL,
        environment: [String: String],
        logName: String
    ) throws -> Process {
        let logURL = logsDirectory.appendingPathComponent(logName)
        if !FileManager.default.fileExists(atPath: logURL.path) {
            FileManager.default.createFile(atPath: logURL.path, contents: nil)
        }
        let logHandle = try FileHandle(forWritingTo: logURL)
        try logHandle.seekToEnd()
        logHandles.append(logHandle)

        let process = Process()
        process.executableURL = executable
        process.arguments = arguments
        process.currentDirectoryURL = workingDirectory
        process.environment = environment
        process.standardOutput = logHandle
        process.standardError = logHandle
        try process.run()
        return process
    }

    private func isBackendReady() -> Bool {
        guard let response = fetch(URL(string: "http://127.0.0.1:8000/api/health")!) else { return false }
        return response.statusCode == 200 && String(data: response.data, encoding: .utf8)?.contains("status") == true
    }

    private func isFrontendReady() -> Bool {
        guard let response = fetch(URL(string: "http://127.0.0.1:3000")!) else { return false }
        guard response.statusCode == 200, let body = String(data: response.data, encoding: .utf8) else { return false }
        return body.contains("OhIc") || body.contains("Private local video studio")
    }

    private func fetch(_ url: URL) -> (statusCode: Int, data: Data)? {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 1
        configuration.timeoutIntervalForResource = 1
        let session = URLSession(configuration: configuration)
        let semaphore = DispatchSemaphore(value: 0)
        var result: (Int, Data)?
        let task = session.dataTask(with: url) { data, response, _ in
            if let http = response as? HTTPURLResponse, let data {
                result = (http.statusCode, data)
            }
            semaphore.signal()
        }
        task.resume()
        if semaphore.wait(timeout: .now() + 1.25) == .timedOut {
            task.cancel()
        }
        session.invalidateAndCancel()
        return result
    }

    func stop() {
        guard ownsProcesses else { return }
        ownsProcesses = false
        let processes = [frontendProcess, backendProcess].compactMap { $0 }
        for process in processes where process.isRunning {
            process.terminate()
        }
        let deadline = Date().addingTimeInterval(3)
        while processes.contains(where: { $0.isRunning }) && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.05)
        }
        for process in processes where process.isRunning {
            kill(process.processIdentifier, SIGKILL)
        }
        frontendProcess = nil
        backendProcess = nil
        for handle in logHandles {
            try? handle.close()
        }
        logHandles.removeAll()
    }
}

private final class BrowserController: NSViewController, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
    private(set) var webView: WKWebView!

    override func loadView() {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.allowsAirPlayForMediaPlayback = true
        configuration.mediaTypesRequiringUserActionForPlayback = []

        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsMagnification = true
        view = webView
    }

    func openWorkspace() {
        webView.load(URLRequest(url: URL(string: "http://127.0.0.1:3000")!))
    }

    @objc func reloadWorkspace() {
        webView.reload()
    }

    private func isLocalApplicationURL(_ url: URL) -> Bool {
        guard let scheme = url.scheme?.lowercased() else { return true }
        if ["about", "blob", "data"].contains(scheme) { return true }
        guard ["http", "https"].contains(scheme) else { return false }
        return url.host == "127.0.0.1" || url.host == "localhost"
    }

    func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationAction: WKNavigationAction,
        preferences: WKWebpagePreferences,
        decisionHandler: @escaping (WKNavigationActionPolicy, WKWebpagePreferences) -> Void
    ) {
        if navigationAction.shouldPerformDownload {
            decisionHandler(.download, preferences)
            return
        }
        if let url = navigationAction.request.url, !isLocalApplicationURL(url) {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel, preferences)
            return
        }
        decisionHandler(.allow, preferences)
    }

    func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationResponse: WKNavigationResponse,
        decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void
    ) {
        let disposition = (navigationResponse.response as? HTTPURLResponse)?
            .value(forHTTPHeaderField: "Content-Disposition")?.lowercased() ?? ""
        if !navigationResponse.canShowMIMEType || disposition.contains("attachment") {
            decisionHandler(.download)
        } else {
            decisionHandler(.allow)
        }
    }

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
        download.delegate = self
    }

    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
        download.delegate = self
    }

    func download(
        _ download: WKDownload,
        decideDestinationUsing response: URLResponse,
        suggestedFilename: String,
        completionHandler: @escaping (URL?) -> Void
    ) {
        let panel = NSSavePanel()
        panel.canCreateDirectories = true
        panel.nameFieldStringValue = suggestedFilename
        if let window = view.window {
            panel.beginSheetModal(for: window) { result in
                completionHandler(result == .OK ? panel.url : nil)
            }
        } else {
            completionHandler(panel.runModal() == .OK ? panel.url : nil)
        }
    }

    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        presentAlert(message: "Download failed", detail: error.localizedDescription)
    }

    func webView(
        _ webView: WKWebView,
        runJavaScriptAlertPanelWithMessage message: String,
        initiatedByFrame frame: WKFrameInfo,
        completionHandler: @escaping () -> Void
    ) {
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "OK")
        run(alert: alert) { _ in completionHandler() }
    }

    func webView(
        _ webView: WKWebView,
        runJavaScriptConfirmPanelWithMessage message: String,
        initiatedByFrame frame: WKFrameInfo,
        completionHandler: @escaping (Bool) -> Void
    ) {
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "Continue")
        alert.addButton(withTitle: "Cancel")
        run(alert: alert) { response in completionHandler(response == .alertFirstButtonReturn) }
    }

    func webView(
        _ webView: WKWebView,
        runJavaScriptTextInputPanelWithPrompt prompt: String,
        defaultText: String?,
        initiatedByFrame frame: WKFrameInfo,
        completionHandler: @escaping (String?) -> Void
    ) {
        let alert = NSAlert()
        alert.messageText = prompt
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: "Cancel")
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 320, height: 24))
        field.stringValue = defaultText ?? ""
        alert.accessoryView = field
        run(alert: alert) { response in
            completionHandler(response == .alertFirstButtonReturn ? field.stringValue : nil)
        }
    }

    func webView(
        _ webView: WKWebView,
        runOpenPanelWith parameters: WKOpenPanelParameters,
        initiatedByFrame frame: WKFrameInfo,
        completionHandler: @escaping ([URL]?) -> Void
    ) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canChooseDirectories = parameters.allowsDirectories
        panel.canChooseFiles = true
        if let window = view.window {
            panel.beginSheetModal(for: window) { result in
                completionHandler(result == .OK ? panel.urls : nil)
            }
        } else {
            completionHandler(panel.runModal() == .OK ? panel.urls : nil)
        }
    }

    private func run(alert: NSAlert, completion: @escaping (NSApplication.ModalResponse) -> Void) {
        if let window = view.window {
            alert.beginSheetModal(for: window, completionHandler: completion)
        } else {
            completion(alert.runModal())
        }
    }

    private func presentAlert(message: String, detail: String) {
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = message
        alert.informativeText = detail
        alert.addButton(withTitle: "OK")
        run(alert: alert) { _ in }
    }
}

private final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private let smokeMode = ProcessInfo.processInfo.environment["OHIC_SMOKE_TEST"] == "1"
    private var window: NSWindow?
    private var serviceManager: ServiceManager?
    private var browserController: BrowserController?
    private var statusLabel: NSTextField?
    private var signalSources: [DispatchSourceSignal] = []

    func applicationDidFinishLaunching(_ notification: Notification) {
        installSignalHandlers()
        if smokeMode {
            NSApp.setActivationPolicy(.prohibited)
        } else {
            NSApp.setActivationPolicy(.regular)
            configureMenu()
            showLoadingWindow()
            NSApp.activate(ignoringOtherApps: true)
        }

        do {
            let manager = try ServiceManager()
            serviceManager = manager
            manager.start { [weak self] result in
                self?.servicesDidStart(result)
            }
        } catch {
            servicesDidStart(.failure(error))
        }
    }

    private func servicesDidStart(_ result: Result<Void, Error>) {
        switch result {
        case .success:
            if smokeMode {
                print("native-host-ready")
                fflush(stdout)
                return
            }
            let browser = BrowserController()
            browserController = browser
            window?.contentViewController = browser
            window?.makeFirstResponder(browser.webView)
            browser.openWorkspace()
        case .failure(let error):
            if smokeMode {
                fputs("native-host-error: \(error.localizedDescription)\n", stderr)
                fflush(stderr)
                NSApp.terminate(nil)
                return
            }
            statusLabel?.stringValue = "Unable to start OhIc"
            let alert = NSAlert()
            alert.alertStyle = .critical
            alert.messageText = "OhIc could not start"
            alert.informativeText = error.localizedDescription
            alert.addButton(withTitle: "Quit")
            if let window {
                alert.beginSheetModal(for: window) { _ in NSApp.terminate(nil) }
            } else {
                alert.runModal()
                NSApp.terminate(nil)
            }
        }
    }

    private func showLoadingWindow() {
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1440, height: 900),
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        window.title = "OhIc"
        window.minSize = NSSize(width: 1000, height: 680)
        window.titlebarAppearsTransparent = true
        window.backgroundColor = NSColor(red: 0.035, green: 0.05, blue: 0.04, alpha: 1)
        window.center()
        window.delegate = self

        let content = NSView()
        content.wantsLayer = true
        content.layer?.backgroundColor = window.backgroundColor.cgColor

        let title = NSTextField(labelWithString: "OhIc")
        title.font = .systemFont(ofSize: 44, weight: .bold)
        title.textColor = .white
        title.translatesAutoresizingMaskIntoConstraints = false

        let status = NSTextField(labelWithString: "Starting your private video workspace…")
        status.font = .systemFont(ofSize: 15, weight: .medium)
        status.textColor = NSColor(white: 0.72, alpha: 1)
        status.translatesAutoresizingMaskIntoConstraints = false
        statusLabel = status

        let progress = NSProgressIndicator()
        progress.style = .spinning
        progress.controlSize = .small
        progress.translatesAutoresizingMaskIntoConstraints = false
        progress.startAnimation(nil)

        content.addSubview(title)
        content.addSubview(status)
        content.addSubview(progress)
        NSLayoutConstraint.activate([
            title.centerXAnchor.constraint(equalTo: content.centerXAnchor),
            title.centerYAnchor.constraint(equalTo: content.centerYAnchor, constant: -34),
            status.centerXAnchor.constraint(equalTo: content.centerXAnchor),
            status.topAnchor.constraint(equalTo: title.bottomAnchor, constant: 16),
            progress.centerXAnchor.constraint(equalTo: content.centerXAnchor),
            progress.topAnchor.constraint(equalTo: status.bottomAnchor, constant: 20),
        ])

        window.contentView = content
        window.makeKeyAndOrderFront(nil)
        self.window = window
    }

    private func configureMenu() {
        let mainMenu = NSMenu()

        let applicationItem = NSMenuItem()
        mainMenu.addItem(applicationItem)
        let applicationMenu = NSMenu()
        applicationMenu.addItem(withTitle: "About OhIc", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        applicationMenu.addItem(.separator())
        applicationMenu.addItem(withTitle: "Quit OhIc", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        applicationItem.submenu = applicationMenu

        let editItem = NSMenuItem()
        mainMenu.addItem(editItem)
        let editMenu = NSMenu(title: "Edit")
        editMenu.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        let redo = editMenu.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "Z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        editMenu.addItem(.separator())
        editMenu.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = editMenu

        let viewItem = NSMenuItem()
        mainMenu.addItem(viewItem)
        let viewMenu = NSMenu(title: "View")
        let reload = viewMenu.addItem(withTitle: "Reload", action: #selector(reloadWorkspace), keyEquivalent: "r")
        reload.target = self
        viewMenu.addItem(.separator())
        viewMenu.addItem(withTitle: "Enter Full Screen", action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f").keyEquivalentModifierMask = [.command, .control]
        viewItem.submenu = viewMenu

        let windowItem = NSMenuItem()
        mainMenu.addItem(windowItem)
        let windowMenu = NSMenu(title: "Window")
        windowMenu.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windowMenu.addItem(withTitle: "Zoom", action: #selector(NSWindow.performZoom(_:)), keyEquivalent: "")
        windowItem.submenu = windowMenu
        NSApp.windowsMenu = windowMenu
        NSApp.mainMenu = mainMenu
    }

    private func installSignalHandlers() {
        for signalNumber in [SIGTERM, SIGINT] {
            signal(signalNumber, SIG_IGN)
            let source = DispatchSource.makeSignalSource(signal: signalNumber, queue: .main)
            source.setEventHandler {
                NSApp.terminate(nil)
            }
            source.resume()
            signalSources.append(source)
        }
    }

    @objc private func reloadWorkspace() {
        browserController?.reloadWorkspace()
    }

    func applicationWillTerminate(_ notification: Notification) {
        serviceManager?.stop()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }
}

private let application = NSApplication.shared
private let delegate = AppDelegate()
application.delegate = delegate
application.run()
