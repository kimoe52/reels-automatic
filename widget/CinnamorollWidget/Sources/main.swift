import AppKit
import Foundation
import CryptoKit
import UniformTypeIdentifiers

private enum Palette {
    static let ink = color(0x29384A)
    static let blue = color(0x458AC4)
    static let blueDark = color(0x3578AE)
    static let sky = color(0xF5F8FA)
    static let selection = color(0xEEF6FD)
    static let paper = color(0xFFFFFF)
    static let line = color(0xE3E8EF)
    static let muted = color(0x728195)
    static let green = color(0x3C9A73)
    static let red = color(0xC45461)

    private static func color(_ hex: UInt32) -> NSColor {
        NSColor(srgbRed: CGFloat((hex >> 16) & 0xFF) / 255,
                green: CGFloat((hex >> 8) & 0xFF) / 255,
                blue: CGFloat(hex & 0xFF) / 255,
                alpha: 1)
    }
}

private final class FloatingWidgetPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }
}

private final class ListDocumentView: NSView {
    override var isFlipped: Bool { true }
}

// One whole row is clickable; read-only labels must not swallow selection clicks.
private final class DraftSelectionRow: NSButton {
    override func hitTest(_ point: NSPoint) -> NSView? {
        guard let hit = super.hitTest(point) else { return nil }
        return hit === self || hit.isDescendant(of: self) ? self : hit
    }
}

private typealias MascotImageView = UnifiedMascotImageView

private final class MascotButton: NSButton {
    private let dragThreshold: CGFloat = 4
    private var startMouse: NSPoint?
    private var startOrigin: NSPoint?
    private var moved = false

    override func mouseDown(with event: NSEvent) {
        startMouse = NSEvent.mouseLocation
        startOrigin = window?.frame.origin
        moved = false
        isHighlighted = true
    }

    override func mouseDragged(with event: NSEvent) {
        guard let startMouse, let startOrigin, let window else { return }
        let current = NSEvent.mouseLocation
        let dx = current.x - startMouse.x
        let dy = current.y - startMouse.y
        guard moved || hypot(dx, dy) >= dragThreshold else { return }
        moved = true
        window.setFrameOrigin(NSPoint(x: startOrigin.x + dx, y: startOrigin.y + dy))
    }

    override func mouseUp(with event: NSEvent) {
        isHighlighted = false
        if !moved, let action { NSApp.sendAction(action, to: target, from: self) }
        startMouse = nil
        startOrigin = nil
        moved = false
    }
}

private struct DraftFolder {
    let url: URL
    let planURL: URL
    let date: Date
    let sourceID: String
    let title: String
    let excerpt: String
    let label: String
}

private struct ReadyRender {
    let folderURL: URL
    let videoURL: URL
    let proofURL: URL
    let date: Date
    let label: String
}

private struct AwaitingAudioRender {
    let date: Date
    let label: String
}

private struct LayerRepairRender {
    let date: Date
    let label: String
}

private struct CardNewsPackage {
    let folderURL: URL
    let manifestURL: URL
    let date: Date
    let title: String
    let cardURLs: [URL]
}

private final class CinnamorollWidgetController: NSObject, NSApplicationDelegate, NSTextFieldDelegate, NSSearchFieldDelegate {
    private let compactSize = NSSize(width: 64, height: 64)
    private let expandedSize = NSSize(width: 440, height: 744)
    private let projectRoot: URL
    private let rootView = NSView()
    private var panel: FloatingWidgetPanel!
    private var mascot: NSImage?
    private var isExpanded = false
    private var isRunningPipeline = false
    private var isCheckingConfiguration = false
    private var isConfigured = false
    private var hasProjectAccess = false
    private var projectAccessURL: URL?
    private var lastSnapshotCount = 0
    private var storedPostCount = 0
    private var needsHistoryBackfill = true
    private var lastSnapshotDate: Date?
    private var accountHandle = "Threads 계정"
    private var drafts: [DraftFolder] = []
    private var readyRenders: [ReadyRender] = []
    private var cardNewsPackages: [CardNewsPackage] = []
    private var awaitingAudioRenders: [AwaitingAudioRender] = []
    private var layerRepairRenders: [LayerRepairRender] = []
    private var isWaitingForChatGPT = false
    private var isWaitingForWebImages = false
    private var selectedDraftURL: URL?
    private var currentProcess: Process?
    private var cancelRequested = false
    private var refreshTimer: Timer?
    private var runButton: NSButton?
    private var renderApprovedButton: NSButton?
    private var importCardsButton: NSButton?
    private var makeCardsButton: NSButton?
    private var makeReelButton: NSButton?
    private var stopButton: NSButton?
    private var lastStatus: String?
    private var lastStatusIsError = false
    private var isPreview = false
    private var connectionLabel: NSTextField?
    private var connectionDot: NSView?
    private var statusLabel: NSTextField?
    private var statusSpinner: NSProgressIndicator?
    private var statusActionButton: NSButton?
    private var storedPostsValue: NSTextField?
    private var draftCountValue: NSTextField?
    private var latestDraftLabel: NSTextField?
    private var latestDraftButton: NSButton?
    private var latestProofButton: NSButton?
    private var queueButton: NSButton?
    private var cardNewsFolderButton: NSButton?
    private var cardNewsPackageLabel: NSTextField?
    private var draftSearchField: NSSearchField?
    private var draftResultCountLabel: NSTextField?
    private var draftListStack: NSStackView?
    private var draftScrollView: NSScrollView?
    private var videoListStack: NSStackView?
    private var videoScrollView: NSScrollView?
    private var draftListSignature = ""
    private var videoListSignature = ""
    private var lastDraftQuery = ""

    private lazy var configuredPaths: [String: String] = {
        let file = projectRoot.appendingPathComponent("project-paths.json")
        guard let data = try? Data(contentsOf: file),
              let settings = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              settings["version"] as? Int == 1 else { return [:] }
        return settings["paths"] as? [String: String] ?? [:]
    }()

    private func projectPath(_ key: String, fallback: String) -> URL {
        let relative = configuredPaths[key] ?? fallback
        let parts = relative.split(separator: "/")
        let candidate = projectRoot.appendingPathComponent(relative, isDirectory: true)
        let root = projectRoot.resolvingSymlinksInPath().standardizedFileURL.path
        let actual = candidate.resolvingSymlinksInPath().standardizedFileURL.path
        guard !relative.isEmpty, !relative.hasPrefix("/"), !parts.contains(".."),
              actual.hasPrefix(root + "/") else {
            return projectRoot.appendingPathComponent(fallback, isDirectory: true)
        }
        return candidate
    }

    private var queueURL: URL {
        projectPath("queue", fallback: "automation/meta-threads/queue")
    }

    private var generatedCardsURL: URL {
        projectPath("cards_library", fallback: "content/card-news/generated")
    }

    private var reelsURL: URL {
        projectPath("reels_videos", fallback: "content/reels/완성 영상")
    }

    private var reelWorkURL: URL {
        projectPath("reels_work", fallback: "content/reels/제작 자료")
    }

    private var selectedDraftIsVisible: Bool {
        guard let selectedDraftURL,
              let draft = drafts.first(where: { $0.url == selectedDraftURL }) else { return false }
        let query = (draftSearchField?.stringValue ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return query.isEmpty || draft.title.localizedCaseInsensitiveContains(query)
            || draft.excerpt.localizedCaseInsensitiveContains(query)
            || draft.sourceID.localizedCaseInsensitiveContains(query)
    }

    private var waitingURL: URL {
        queueURL.appendingPathComponent(".chatgpt-waiting.json")
    }

    private var snapshotURL: URL {
        projectRoot.appendingPathComponent("automation/meta-threads/fetch/snapshots", isDirectory: true)
    }

    private var fetchStateURL: URL {
        projectRoot.appendingPathComponent("automation/meta-threads/state/threads_state.json")
    }

    private var fetchScriptURL: URL {
        projectRoot.appendingPathComponent("automation/meta-threads/fetch/fetch_posts.py")
    }

    private var dailyScriptURL: URL {
        projectRoot.appendingPathComponent("automation/meta-threads/run_daily.py")
    }

    private var logURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/CinnamorollContentWidget/latest-run.log")
    }

    private var pythonURL: URL? {
        ["/opt/homebrew/bin/python3", "/usr/local/bin/python3"].first {
            FileManager.default.isExecutableFile(atPath: $0)
        }.map { URL(fileURLWithPath: $0) }
    }

    init(projectRoot: URL) {
        self.projectRoot = projectRoot.standardizedFileURL
        super.init()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        restoreProjectAccess()
        NSApp.setActivationPolicy(.regular)
        installMenu()
        mascot = Bundle.main.url(forResource: "cinnamoroll-widget-mascot", withExtension: "png")
            .flatMap(NSImage.init(contentsOf:))
        if let mascot { NSApp.applicationIconImage = mascot }

        panel = FloatingWidgetPanel(contentRect: NSRect(origin: .zero, size: compactSize),
                                    styleMask: [.titled, .fullSizeContentView], backing: .buffered, defer: false)
        panel.titleVisibility = .hidden
        panel.titlebarAppearsTransparent = true
        [.closeButton, .miniaturizeButton, .zoomButton].forEach {
            panel.standardWindowButton($0)?.isHidden = true
        }
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        // Keep the utility above regular app windows, including browser tabs.
        panel.level = .statusBar
        panel.isFloatingPanel = false
        panel.hidesOnDeactivate = false
        panel.isMovableByWindowBackground = false
        panel.isReleasedWhenClosed = false
        panel.title = "시나모롤 콘텐츠 위젯"
        panel.setAccessibilityRole(.window)
        panel.setAccessibilitySubrole(.standardWindow)
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.contentView = rootView
        panel.appearance = NSAppearance(named: .aqua)
        rootView.frame = NSRect(origin: .zero, size: compactSize)
        rootView.autoresizingMask = [.width, .height]

        showCompact()
        placeAtUpperRight()
        panel.orderFrontRegardless()
        refreshLocalData()
        checkConfiguration()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows: Bool) -> Bool {
        showExpanded()
        return true
    }

    func applicationDidBecomeActive(_ notification: Notification) {
        guard panel != nil else { return }
        panel.level = .statusBar
        panel.orderFrontRegardless()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    private func installMenu() {
        let mainMenu = NSMenu()
        let item = NSMenuItem()
        let menu = NSMenu()
        let renderItem = menu.addItem(withTitle: "검수된 기존 카드로 릴스 다시 만들기", action: #selector(renderApprovedCards), keyEquivalent: "r")
        renderItem.target = self
        let cardsItem = menu.addItem(withTitle: "파일에서 카드 골라 릴스 만들기", action: #selector(importCardImages), keyEquivalent: "i")
        cardsItem.target = self
        let selectedCardsItem = menu.addItem(withTitle: "선택한 글로 카드뉴스 만들기", action: #selector(makeSelectedCards), keyEquivalent: "g")
        selectedCardsItem.target = self
        let safariItem = menu.addItem(withTitle: "Safari 연결 확인", action: #selector(checkSafariImages), keyEquivalent: "k")
        safariItem.target = self
        let logItem = menu.addItem(withTitle: "실행 기록 열기", action: #selector(openLog), keyEquivalent: "l")
        logItem.target = self
        let connectItem = menu.addItem(withTitle: "저장 파일 접근 허용", action: #selector(connectProjectFolder), keyEquivalent: "o")
        connectItem.target = self
        let stopItem = menu.addItem(withTitle: "현재 작업 중단", action: #selector(stopPipeline), keyEquivalent: ".")
        stopItem.target = self
        menu.addItem(.separator())
        menu.addItem(withTitle: "시나모롤 콘텐츠 위젯 종료", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        item.submenu = menu
        mainMenu.addItem(item)
        NSApp.mainMenu = mainMenu
    }

    private func placeAtUpperRight() {
        guard let screen = NSScreen.main else { return }
        let visible = screen.visibleFrame
        panel.setFrameOrigin(NSPoint(x: visible.maxX - compactSize.width - 20,
                                     y: visible.maxY - compactSize.height - 24))
    }

    private func resizeKeepingTopRight(_ size: NSSize) {
        let old = panel.frame
        panel.setFrame(NSRect(x: old.maxX - size.width, y: old.maxY - size.height,
                              width: size.width, height: size.height), display: true, animate: true)
    }

    private func clearContent() {
        rootView.subviews.forEach { $0.removeFromSuperview() }
        rootView.wantsLayer = true
        rootView.layer?.masksToBounds = true
    }

    private func showCompact() {
        isExpanded = false
        refreshTimer?.invalidate()
        refreshTimer = nil
        clearContent()
        rootView.layer?.backgroundColor = NSColor.clear.cgColor
        rootView.layer?.cornerRadius = 0
        rootView.layer?.borderWidth = 0
        panel.hasShadow = false
        panel.isMovableByWindowBackground = false
        resizeKeepingTopRight(compactSize)

        let imageView = MascotImageView(frame: rootView.bounds)
        imageView.outlineOutset = MascotPresentation.cinnamorollOutlineOutset
        imageView.visualScale = MascotPresentation.cinnamorollVisualScale
        imageView.autoresizingMask = [.width, .height]
        imageView.image = mascot
        rootView.addSubview(imageView)

        let button = MascotButton(frame: rootView.bounds)
        button.autoresizingMask = [.width, .height]
        button.title = ""
        button.isBordered = false
        button.target = self
        button.action = #selector(toggleExpanded)
        button.toolTip = "클릭해서 Threads 초안 위젯 열기 · 드래그해서 옮기기"
        button.setAccessibilityLabel("Threads 콘텐츠 위젯 열기")
        rootView.addSubview(button)
    }

    private func showExpanded() {
        isExpanded = true
        clearContent()
        resizeKeepingTopRight(expandedSize)
        panel.level = .statusBar
        panel.hasShadow = true
        panel.isMovableByWindowBackground = true
        rootView.layer?.backgroundColor = Palette.paper.cgColor
        rootView.layer?.cornerRadius = 16
        rootView.layer?.borderColor = Palette.line.cgColor
        rootView.layer?.borderWidth = 1

        let collapse = makeQuietButton("접기", action: #selector(collapseWidget))
        collapse.contentTintColor = Palette.muted
        rootView.addSubview(collapse)
        NSLayoutConstraint.activate([
            collapse.topAnchor.constraint(equalTo: rootView.topAnchor, constant: 16),
            collapse.trailingAnchor.constraint(equalTo: rootView.trailingAnchor, constant: -18),
            collapse.widthAnchor.constraint(equalToConstant: 42),
            collapse.heightAnchor.constraint(equalToConstant: 24)
        ])

        let connection = makeConnectionBadge()
        rootView.addSubview(connection)
        NSLayoutConstraint.activate([
            connection.centerYAnchor.constraint(equalTo: collapse.centerYAnchor),
            connection.leadingAnchor.constraint(equalTo: rootView.leadingAnchor, constant: 18),
            connection.trailingAnchor.constraint(lessThanOrEqualTo: collapse.leadingAnchor, constant: -8),
            connection.heightAnchor.constraint(equalToConstant: 16)
        ])

        let stats = makeStats()
        rootView.addSubview(stats.view)
        NSLayoutConstraint.activate([
            stats.view.topAnchor.constraint(equalTo: collapse.bottomAnchor, constant: 12),
            stats.view.leadingAnchor.constraint(equalTo: rootView.leadingAnchor, constant: 18),
            stats.view.trailingAnchor.constraint(lessThanOrEqualTo: rootView.trailingAnchor, constant: -18),
            stats.view.heightAnchor.constraint(equalToConstant: 18)
        ])
        storedPostsValue = stats.firstValue
        draftCountValue = stats.secondValue

        let action = makePrimaryButton("새 글 불러오기", action: #selector(runPipeline))
        runButton = action
        rootView.addSubview(action)
        NSLayoutConstraint.activate([
            action.topAnchor.constraint(equalTo: stats.view.bottomAnchor, constant: 14),
            action.leadingAnchor.constraint(equalTo: rootView.leadingAnchor, constant: 18),
            action.trailingAnchor.constraint(equalTo: rootView.trailingAnchor, constant: -18),
            action.heightAnchor.constraint(equalToConstant: 36)
        ])

        let draftHeading = makeLabel("카드뉴스 만들 글", size: 12, weight: .semibold, color: Palette.ink)
        rootView.addSubview(draftHeading)
        NSLayoutConstraint.activate([
            draftHeading.topAnchor.constraint(equalTo: action.bottomAnchor, constant: 13),
            draftHeading.leadingAnchor.constraint(equalTo: action.leadingAnchor)
        ])
        let resultCount = makeLabel("", size: 10, weight: .regular, color: Palette.muted)
        draftResultCountLabel = resultCount
        rootView.addSubview(resultCount)
        NSLayoutConstraint.activate([
            resultCount.centerYAnchor.constraint(equalTo: draftHeading.centerYAnchor),
            resultCount.trailingAnchor.constraint(equalTo: action.trailingAnchor)
        ])

        let search = NSSearchField()
        search.translatesAutoresizingMaskIntoConstraints = false
        search.placeholderString = "글 제목이나 내용 검색"
        search.font = .systemFont(ofSize: 11)
        search.delegate = self
        draftSearchField = search
        rootView.addSubview(search)
        NSLayoutConstraint.activate([
            search.topAnchor.constraint(equalTo: draftHeading.bottomAnchor, constant: 5),
            search.leadingAnchor.constraint(equalTo: action.leadingAnchor),
            search.trailingAnchor.constraint(equalTo: action.trailingAnchor),
            search.heightAnchor.constraint(equalToConstant: 26)
        ])

        let (draftScroll, draftStack) = makeList()
        draftListStack = draftStack
        draftScrollView = draftScroll
        rootView.addSubview(draftScroll)
        NSLayoutConstraint.activate([
            draftScroll.topAnchor.constraint(equalTo: search.bottomAnchor, constant: 5),
            draftScroll.leadingAnchor.constraint(equalTo: action.leadingAnchor),
            draftScroll.trailingAnchor.constraint(equalTo: action.trailingAnchor),
            draftScroll.heightAnchor.constraint(equalToConstant: 156)
        ])

        let createCards = makePrimaryButton("선택한 글로 카드뉴스 만들기", action: #selector(makeSelectedCards))
        makeCardsButton = createCards
        rootView.addSubview(createCards)
        NSLayoutConstraint.activate([
            createCards.topAnchor.constraint(equalTo: draftScroll.bottomAnchor, constant: 8),
            createCards.leadingAnchor.constraint(equalTo: action.leadingAnchor),
            createCards.trailingAnchor.constraint(equalTo: action.trailingAnchor),
            createCards.heightAnchor.constraint(equalToConstant: 34)
        ])

        let cardHeading = makeLabel("검수 완료 카드뉴스", size: 12, weight: .semibold, color: Palette.ink)
        rootView.addSubview(cardHeading)
        NSLayoutConstraint.activate([
            cardHeading.topAnchor.constraint(equalTo: createCards.bottomAnchor, constant: 11),
            cardHeading.leadingAnchor.constraint(equalTo: action.leadingAnchor)
        ])
        let openCardFolder = makeQuietButton("카드뉴스 모음", action: #selector(openGeneratedCards))
        cardNewsFolderButton = openCardFolder
        rootView.addSubview(openCardFolder)
        NSLayoutConstraint.activate([
            openCardFolder.centerYAnchor.constraint(equalTo: cardHeading.centerYAnchor),
            openCardFolder.trailingAnchor.constraint(equalTo: action.trailingAnchor),
            openCardFolder.heightAnchor.constraint(equalToConstant: 24)
        ])

        let cardPackage = makeLabel("아직 검수 완료된 카드가 없어요", size: 11, weight: .regular, color: Palette.muted)
        cardPackage.maximumNumberOfLines = 2
        cardPackage.cell?.wraps = true
        cardNewsPackageLabel = cardPackage
        rootView.addSubview(cardPackage)
        NSLayoutConstraint.activate([
            cardPackage.topAnchor.constraint(equalTo: cardHeading.bottomAnchor, constant: 4),
            cardPackage.leadingAnchor.constraint(equalTo: action.leadingAnchor),
            cardPackage.trailingAnchor.constraint(equalTo: action.trailingAnchor),
            cardPackage.heightAnchor.constraint(equalToConstant: 28)
        ])

        let createReel = makeSecondaryButton("최근 카드뉴스로 릴스 만들기", action: #selector(makeReelFromLatestCards))
        createReel.toolTip = "검수 완료 카드뉴스 모음의 최신 카드 묶음을 자동으로 연결해 세로 영상을 만듭니다"
        makeReelButton = createReel
        rootView.addSubview(createReel)
        NSLayoutConstraint.activate([
            createReel.topAnchor.constraint(equalTo: cardPackage.bottomAnchor, constant: 4),
            createReel.leadingAnchor.constraint(equalTo: action.leadingAnchor),
            createReel.trailingAnchor.constraint(equalTo: action.trailingAnchor),
            createReel.heightAnchor.constraint(equalToConstant: 34)
        ])

        let statusBox = NSView()
        statusBox.translatesAutoresizingMaskIntoConstraints = false
        statusBox.wantsLayer = true
        statusBox.layer?.backgroundColor = Palette.sky.cgColor
        statusBox.layer?.cornerRadius = 6
        rootView.addSubview(statusBox)
        NSLayoutConstraint.activate([
            statusBox.topAnchor.constraint(equalTo: createReel.bottomAnchor, constant: 8),
            statusBox.leadingAnchor.constraint(equalTo: action.leadingAnchor),
            statusBox.trailingAnchor.constraint(equalTo: action.trailingAnchor),
            statusBox.heightAnchor.constraint(equalToConstant: 36)
        ])
        let spinner = NSProgressIndicator()
        spinner.translatesAutoresizingMaskIntoConstraints = false
        spinner.style = .spinning
        spinner.controlSize = .small
        spinner.isDisplayedWhenStopped = false
        spinner.isHidden = true
        statusBox.addSubview(spinner)
        statusSpinner = spinner

        let status = makeLabel(lastStatus ?? "Threads 설정 확인 중…", size: 11, weight: .regular, color: Palette.muted)
        status.lineBreakMode = .byWordWrapping
        status.maximumNumberOfLines = 2
        status.cell?.wraps = true
        statusLabel = status
        statusBox.addSubview(status)
        let logButton = makeQuietButton("기록", action: #selector(statusAction))
        statusActionButton = logButton
        logButton.toolTip = "토큰을 숨긴 실행 기록 · 접근 오류 시 카드·영상 저장 위치 확인"
        statusBox.addSubview(logButton)
        NSLayoutConstraint.activate([
            spinner.leadingAnchor.constraint(equalTo: statusBox.leadingAnchor, constant: 8),
            spinner.centerYAnchor.constraint(equalTo: statusBox.centerYAnchor),
            spinner.widthAnchor.constraint(equalToConstant: 14),
            spinner.heightAnchor.constraint(equalToConstant: 14),
            status.leadingAnchor.constraint(equalTo: statusBox.leadingAnchor, constant: 28),
            status.centerYAnchor.constraint(equalTo: spinner.centerYAnchor),
            logButton.trailingAnchor.constraint(equalTo: statusBox.trailingAnchor, constant: -5),
            logButton.centerYAnchor.constraint(equalTo: statusBox.centerYAnchor),
            logButton.widthAnchor.constraint(equalToConstant: 38),
            logButton.heightAnchor.constraint(equalToConstant: 24)
        ])

        let stop = makeQuietButton("중단", action: #selector(stopPipeline))
        stop.contentTintColor = Palette.red
        stop.isHidden = true
        stopButton = stop
        statusBox.addSubview(stop)
        NSLayoutConstraint.activate([
            stop.trailingAnchor.constraint(equalTo: logButton.leadingAnchor, constant: -2),
            stop.centerYAnchor.constraint(equalTo: statusBox.centerYAnchor),
            stop.widthAnchor.constraint(equalToConstant: 40),
            stop.heightAnchor.constraint(equalToConstant: 24)
        ])
        status.trailingAnchor.constraint(equalTo: stop.leadingAnchor, constant: -3).isActive = true

        let divider = NSView()
        divider.translatesAutoresizingMaskIntoConstraints = false
        divider.wantsLayer = true
        divider.layer?.backgroundColor = Palette.line.cgColor
        rootView.addSubview(divider)
        NSLayoutConstraint.activate([
            divider.topAnchor.constraint(equalTo: statusBox.bottomAnchor, constant: 12),
            divider.leadingAnchor.constraint(equalTo: action.leadingAnchor),
            divider.trailingAnchor.constraint(equalTo: action.trailingAnchor),
            divider.heightAnchor.constraint(equalToConstant: 1)
        ])

        let recentTitle = makeLabel("최근 완성 영상", size: 12, weight: .semibold, color: Palette.ink)
        rootView.addSubview(recentTitle)
        NSLayoutConstraint.activate([
            recentTitle.topAnchor.constraint(equalTo: divider.bottomAnchor, constant: 9),
            recentTitle.leadingAnchor.constraint(equalTo: action.leadingAnchor)
        ])

        let openQueueButton = makeQuietButton("릴스 폴더", action: #selector(openReelsFolder))
        queueButton = openQueueButton
        rootView.addSubview(openQueueButton)
        NSLayoutConstraint.activate([
            openQueueButton.trailingAnchor.constraint(equalTo: rootView.trailingAnchor, constant: -17),
            openQueueButton.centerYAnchor.constraint(equalTo: recentTitle.centerYAnchor),
            openQueueButton.heightAnchor.constraint(equalToConstant: 24)
        ])

        let (videoScroll, videoStack) = makeList()
        videoListStack = videoStack
        videoScrollView = videoScroll
        rootView.addSubview(videoScroll)
        NSLayoutConstraint.activate([
            videoScroll.topAnchor.constraint(equalTo: recentTitle.bottomAnchor, constant: 5),
            videoScroll.leadingAnchor.constraint(equalTo: action.leadingAnchor),
            videoScroll.trailingAnchor.constraint(equalTo: action.trailingAnchor),
            videoScroll.heightAnchor.constraint(equalToConstant: 122)
        ])

        let safety = makeLabel("원문 유지 · 검수 후 게시 · 자동 게시 안 함", size: 10, weight: .regular, color: Palette.muted)
        rootView.addSubview(safety)
        NSLayoutConstraint.activate([
            safety.leadingAnchor.constraint(equalTo: rootView.leadingAnchor, constant: 18),
            safety.trailingAnchor.constraint(equalTo: rootView.trailingAnchor, constant: -18),
            safety.topAnchor.constraint(equalTo: videoScroll.bottomAnchor, constant: 7),
            safety.heightAnchor.constraint(equalToConstant: 14),
            safety.bottomAnchor.constraint(lessThanOrEqualTo: rootView.bottomAnchor, constant: -12)
        ])

        rootView.layoutSubtreeIfNeeded()
        draftListSignature = ""
        videoListSignature = ""
        refreshLocalData()
        setConnection(isConfigured, checking: isCheckingConfiguration)
        if isRunningPipeline {
            setStatus(lastStatus ?? "작업 중…")
            statusSpinner?.isHidden = false
            statusSpinner?.startAnimation(nil)
        } else if let lastStatus {
            setStatus(lastStatus, error: lastStatusIsError)
        } else if isConfigured {
            showIdleStatus()
        } else if !isCheckingConfiguration {
            checkConfiguration()
        }
        guard !isPreview else { return }
        refreshTimer?.invalidate()
        refreshTimer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            self?.refreshLocalData()
        }
        NSApp.activate(ignoringOtherApps: true)
        panel.level = .statusBar
        panel.orderFrontRegardless()
    }

    private func makeList() -> (NSScrollView, NSStackView) {
        let scroll = NSScrollView()
        scroll.translatesAutoresizingMaskIntoConstraints = false
        scroll.hasVerticalScroller = true
        scroll.autohidesScrollers = true
        scroll.scrollerStyle = .overlay
        scroll.drawsBackground = false
        scroll.borderType = .noBorder
        scroll.wantsLayer = true
        scroll.layer?.backgroundColor = Palette.paper.cgColor
        scroll.layer?.cornerRadius = 10
        scroll.layer?.borderColor = Palette.line.cgColor
        scroll.layer?.borderWidth = 1
        scroll.layer?.masksToBounds = true
        let document = ListDocumentView(frame: NSRect(x: 0, y: 0, width: 404, height: 156))
        document.autoresizingMask = [.width]
        let stack = NSStackView()
        stack.translatesAutoresizingMaskIntoConstraints = false
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 6
        document.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.topAnchor.constraint(equalTo: document.topAnchor, constant: 6),
            stack.leadingAnchor.constraint(equalTo: document.leadingAnchor, constant: 6),
            stack.trailingAnchor.constraint(equalTo: document.trailingAnchor, constant: -6)
        ])
        scroll.documentView = document
        return (scroll, stack)
    }

    private func fitList(_ scroll: NSScrollView, stack: NSStackView, offset: CGFloat = 0) {
        guard let document = scroll.documentView else { return }
        document.setFrameSize(NSSize(width: scroll.contentView.bounds.width,
                                     height: max(scroll.contentView.bounds.height, stack.fittingSize.height + 12)))
        document.layoutSubtreeIfNeeded()
        let maximumY = max(0, document.frame.height - scroll.contentView.bounds.height)
        scroll.contentView.scroll(to: NSPoint(x: 0, y: min(maximumY, max(0, offset))))
        scroll.reflectScrolledClipView(scroll.contentView)
    }

    private static func compactText(_ text: String) -> String {
        text.replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func listTitle(_ title: String) -> String {
        var text = compactText(title)
        while let first = text.first, ["📌", "📍", "•"].contains(String(first)) {
            text.removeFirst()
            text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return text
    }

    private static func listExcerpt(title: String, fullText: String) -> String {
        let heading = compactText(title)
        var text = compactText(fullText)
        if !heading.isEmpty, text.hasPrefix(heading) { text.removeFirst(heading.count) }
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func makeListText(_ text: String, size: CGFloat, weight: NSFont.Weight,
                              color: NSColor) -> NSTextField {
        let label = makeLabel(text, size: size, weight: weight, color: color)
        label.maximumNumberOfLines = 1
        label.cell?.usesSingleLineMode = true
        label.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        return label
    }

    private func draftMetadata(_ draft: DraftFolder) -> String {
        let parts = draft.url.deletingLastPathComponent().lastPathComponent.split(separator: "-")
        let date: String
        if parts.count == 3, let month = Int(parts[1]), let day = Int(parts[2]) {
            date = "\(month)월 \(day)일"
        } else {
            date = shortDate(draft.date)
        }
        let details = draft.label.components(separatedBy: " · ").dropFirst(2)
        return ([date] + details).joined(separator: " · ")
    }

    private func makeDraftRow(_ draft: DraftFolder, index: Int, selected: Bool) -> DraftSelectionRow {
        let row = DraftSelectionRow(title: "", target: self, action: #selector(selectDraft(_:)))
        row.translatesAutoresizingMaskIntoConstraints = false
        row.setButtonType(.pushOnPushOff)
        row.isBordered = false
        row.state = selected ? .on : .off
        row.tag = index
        row.wantsLayer = true
        row.layer?.cornerRadius = 7
        row.layer?.backgroundColor = (selected ? Palette.selection : Palette.paper).cgColor
        row.layer?.borderColor = Palette.blue.withAlphaComponent(0.3).cgColor
        row.layer?.borderWidth = selected ? 1 : 0
        if let cell = row.cell as? NSButtonCell {
            cell.showsStateBy = []
            cell.highlightsBy = []
        }
        row.toolTip = "\(draft.title)\n\(draft.excerpt)\n\(draft.label)"
        row.setAccessibilityLabel("\(selected ? "선택됨, " : "")\(draft.title), \(draft.label)")
        let indicator = NSImageView()
        indicator.translatesAutoresizingMaskIntoConstraints = false
        indicator.image = NSImage(systemSymbolName: selected ? "checkmark.circle.fill" : "circle", accessibilityDescription: nil)
        indicator.contentTintColor = selected ? Palette.blueDark : Palette.line
        row.addSubview(indicator)
        let title = makeListText(Self.listTitle(draft.title), size: 11.5, weight: .semibold, color: Palette.ink)
        let preview = Self.listExcerpt(title: draft.title, fullText: draft.excerpt)
        let excerpt = makeListText(preview, size: 10.5, weight: .regular, color: Palette.muted)
        let metadata = makeListText(draftMetadata(draft), size: 9.5, weight: .regular, color: Palette.muted)
        for label in [title, excerpt, metadata] { row.addSubview(label) }
        NSLayoutConstraint.activate([
            indicator.leadingAnchor.constraint(equalTo: row.leadingAnchor, constant: 10),
            indicator.topAnchor.constraint(equalTo: row.topAnchor, constant: 11),
            indicator.widthAnchor.constraint(equalToConstant: 15),
            indicator.heightAnchor.constraint(equalToConstant: 15),
            title.leadingAnchor.constraint(equalTo: indicator.trailingAnchor, constant: 9),
            title.trailingAnchor.constraint(equalTo: row.trailingAnchor, constant: -12),
            title.topAnchor.constraint(equalTo: row.topAnchor, constant: 9),
            title.heightAnchor.constraint(equalToConstant: 16),
            excerpt.leadingAnchor.constraint(equalTo: title.leadingAnchor),
            excerpt.trailingAnchor.constraint(equalTo: title.trailingAnchor),
            excerpt.topAnchor.constraint(equalTo: title.bottomAnchor, constant: 3),
            excerpt.heightAnchor.constraint(equalToConstant: 14),
            metadata.leadingAnchor.constraint(equalTo: title.leadingAnchor),
            metadata.trailingAnchor.constraint(equalTo: title.trailingAnchor),
            metadata.topAnchor.constraint(equalTo: excerpt.bottomAnchor, constant: 4),
            metadata.heightAnchor.constraint(equalToConstant: 12)
        ])
        return row
    }

    private func renderDraftChoices() {
        guard let stack = draftListStack, let scroll = draftScrollView else { return }
        let query = (draftSearchField?.stringValue ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let signature = drafts.map { "\($0.url.path)|\($0.title)|\($0.excerpt)|\($0.label)|\($0.date.timeIntervalSince1970)" }.joined(separator: "\n")
            + "|selected=\(selectedDraftURL?.path ?? "")|query=\(query)"
        guard signature != draftListSignature else { return }
        let previousOffset = query == lastDraftQuery ? scroll.contentView.bounds.origin.y : 0
        lastDraftQuery = query
        draftListSignature = signature
        stack.arrangedSubviews.forEach { view in
            stack.removeArrangedSubview(view)
            view.removeFromSuperview()
        }
        let filtered = drafts.enumerated().filter { _, draft in
            query.isEmpty || draft.title.localizedCaseInsensitiveContains(query)
                || draft.excerpt.localizedCaseInsensitiveContains(query)
                || draft.sourceID.localizedCaseInsensitiveContains(query)
        }
        draftResultCountLabel?.stringValue = "\(filtered.count)개"
        for (index, draft) in filtered {
            let choice = makeDraftRow(draft, index: index, selected: draft.url == selectedDraftURL)
            stack.addArrangedSubview(choice)
            NSLayoutConstraint.activate([
                choice.widthAnchor.constraint(equalTo: stack.widthAnchor),
                choice.heightAnchor.constraint(equalToConstant: 68)
            ])
        }
        if filtered.isEmpty {
            let empty = makeLabel(query.isEmpty ? "불러온 글이 없어요 · 새 글 불러오기를 눌러주세요" : "검색한 글이 없어요",
                                  size: 10, weight: .regular, color: Palette.muted)
            stack.addArrangedSubview(empty)
            NSLayoutConstraint.activate([empty.widthAnchor.constraint(equalTo: stack.widthAnchor), empty.heightAnchor.constraint(equalToConstant: 50)])
        }
        fitList(scroll, stack: stack, offset: previousOffset)
        refreshPipelineAction()
    }

    private func renderVideoChoices() {
        guard let stack = videoListStack, let scroll = videoScrollView else { return }
        let signature = readyRenders.map { "\($0.videoURL.path)|\($0.date.timeIntervalSince1970)" }.joined(separator: "\n")
        guard signature != videoListSignature else { return }
        videoListSignature = signature
        stack.arrangedSubviews.forEach { view in
            stack.removeArrangedSubview(view)
            view.removeFromSuperview()
        }
        if readyRenders.isEmpty {
            let empty = makeLabel("완성 영상이 생기면 여기에 모여요", size: 10, weight: .regular, color: Palette.muted)
            stack.addArrangedSubview(empty)
            NSLayoutConstraint.activate([empty.widthAnchor.constraint(equalTo: stack.widthAnchor), empty.heightAnchor.constraint(equalToConstant: 50)])
        } else {
            for render in readyRenders {
                let row = NSView()
                row.translatesAutoresizingMaskIntoConstraints = false
                let components = render.label.components(separatedBy: "\n")
                let title = makeListText(components.first ?? render.folderURL.lastPathComponent,
                                         size: 11.5, weight: .medium, color: Palette.ink)
                row.addSubview(title)
                let date = makeListText(components.dropFirst().first ?? shortDate(render.date), size: 10,
                                        weight: .regular, color: Palette.muted)
                row.addSubview(date)
                let openButton = makeSecondaryButton("영상 열기", action: #selector(openVideo(_:)))
                openButton.identifier = NSUserInterfaceItemIdentifier(render.videoURL.path)
                openButton.toolTip = render.videoURL.path
                openButton.setAccessibilityLabel("\(title.stringValue) 영상 열기")
                row.addSubview(openButton)
                let separator = NSView()
                separator.translatesAutoresizingMaskIntoConstraints = false
                separator.wantsLayer = true
                separator.layer?.backgroundColor = Palette.line.withAlphaComponent(0.65).cgColor
                separator.isHidden = render.videoURL == readyRenders.last?.videoURL
                row.addSubview(separator)
                stack.addArrangedSubview(row)
                NSLayoutConstraint.activate([
                    row.widthAnchor.constraint(equalTo: stack.widthAnchor),
                    row.heightAnchor.constraint(equalToConstant: 52),
                    title.leadingAnchor.constraint(equalTo: row.leadingAnchor, constant: 10),
                    title.trailingAnchor.constraint(equalTo: openButton.leadingAnchor, constant: -12),
                    title.topAnchor.constraint(equalTo: row.topAnchor, constant: 7),
                    title.heightAnchor.constraint(equalToConstant: 16),
                    date.leadingAnchor.constraint(equalTo: title.leadingAnchor),
                    date.trailingAnchor.constraint(equalTo: title.trailingAnchor),
                    date.topAnchor.constraint(equalTo: title.bottomAnchor, constant: 4),
                    date.heightAnchor.constraint(equalToConstant: 14),
                    openButton.trailingAnchor.constraint(equalTo: row.trailingAnchor, constant: -10),
                    openButton.centerYAnchor.constraint(equalTo: row.centerYAnchor),
                    openButton.widthAnchor.constraint(equalToConstant: 68),
                    openButton.heightAnchor.constraint(equalToConstant: 27),
                    separator.leadingAnchor.constraint(equalTo: title.leadingAnchor),
                    separator.trailingAnchor.constraint(equalTo: openButton.trailingAnchor),
                    separator.bottomAnchor.constraint(equalTo: row.bottomAnchor),
                    separator.heightAnchor.constraint(equalToConstant: 1)
                ])
            }
        }
        fitList(scroll, stack: stack)
    }

    private func makeConnectionBadge() -> NSView {
        let badge = NSView()
        badge.translatesAutoresizingMaskIntoConstraints = false
        let dot = NSView()
        dot.translatesAutoresizingMaskIntoConstraints = false
        dot.wantsLayer = true
        dot.layer?.backgroundColor = Palette.blue.cgColor
        dot.layer?.cornerRadius = 3.5
        connectionDot = dot
        let label = makeLabel("Threads 설정 확인 중", size: 10, weight: .medium, color: Palette.blueDark)
        connectionLabel = label
        badge.addSubview(dot)
        badge.addSubview(label)
        NSLayoutConstraint.activate([
            dot.leadingAnchor.constraint(equalTo: badge.leadingAnchor),
            dot.centerYAnchor.constraint(equalTo: badge.centerYAnchor),
            dot.widthAnchor.constraint(equalToConstant: 7),
            dot.heightAnchor.constraint(equalToConstant: 7),
            label.leadingAnchor.constraint(equalTo: dot.trailingAnchor, constant: 6),
            label.trailingAnchor.constraint(equalTo: badge.trailingAnchor),
            label.centerYAnchor.constraint(equalTo: badge.centerYAnchor)
        ])
        return badge
    }

    private func makeStats() -> (view: NSView, firstValue: NSTextField, secondValue: NSTextField) {
        let first = makeLabel("0", size: 11, weight: .semibold, color: Palette.ink)
        let second = makeLabel("0", size: 11, weight: .semibold, color: Palette.ink)
        first.font = .monospacedDigitSystemFont(ofSize: 11, weight: .semibold)
        second.font = first.font
        let storedLabel = makeLabel("보관 글", size: 11, weight: .regular, color: Palette.muted)
        storedLabel.toolTip = "이 프로그램에 저장된 글의 누적 수 · 중복 제외 · Threads 전체 게시글 수는 아님"
        first.toolTip = storedLabel.toolTip
        let container = NSStackView(views: [
            storedLabel, first,
            makeLabel("·", size: 11, weight: .regular, color: Palette.muted),
            makeLabel("완성 영상", size: 11, weight: .regular, color: Palette.muted), second
        ])
        container.translatesAutoresizingMaskIntoConstraints = false
        container.orientation = .horizontal
        container.alignment = .centerY
        container.spacing = 6
        return (container, first, second)
    }

    private func makeLabel(_ text: String, size: CGFloat, weight: NSFont.Weight, color: NSColor) -> NSTextField {
        let label = NSTextField(labelWithString: text)
        label.translatesAutoresizingMaskIntoConstraints = false
        label.font = .systemFont(ofSize: size, weight: weight)
        label.textColor = color
        label.lineBreakMode = .byTruncatingTail
        return label
    }

    private func makePrimaryButton(_ title: String, action: Selector) -> NSButton {
        let button = NSButton(title: title, target: self, action: action)
        button.translatesAutoresizingMaskIntoConstraints = false
        button.isBordered = false
        button.font = .systemFont(ofSize: 13, weight: .semibold)
        button.attributedTitle = NSAttributedString(string: title, attributes: [
            .font: button.font!, .foregroundColor: NSColor.white
        ])
        button.contentTintColor = .white
        button.wantsLayer = true
        button.layer?.backgroundColor = Palette.blue.cgColor
        button.layer?.cornerRadius = 8
        button.setAccessibilityLabel(title)
        return button
    }

    private func makeQuietButton(_ title: String, action: Selector) -> NSButton {
        let button = NSButton(title: title, target: self, action: action)
        button.translatesAutoresizingMaskIntoConstraints = false
        button.isBordered = false
        button.font = .systemFont(ofSize: 11, weight: .medium)
        button.contentTintColor = Palette.blueDark
        button.setAccessibilityLabel(title)
        return button
    }

    private func makeSecondaryButton(_ title: String, action: Selector) -> NSButton {
        let button = makeQuietButton(title, action: action)
        button.contentTintColor = Palette.ink
        button.wantsLayer = true
        button.layer?.backgroundColor = Palette.paper.cgColor
        button.layer?.borderWidth = 1
        button.layer?.borderColor = Palette.line.cgColor
        button.layer?.cornerRadius = 8
        return button
    }

    private func refreshLocalData() {
        // Avoid reading protected Documents on launch before the user selects
        // this exact project. A synchronous privacy prompt can freeze the panel.
        guard isPreview || projectAccessURL != nil else {
            hasProjectAccess = false
            drafts = []
            readyRenders = []
            cardNewsPackages = []
            selectedDraftURL = nil
            storedPostsValue?.stringValue = "—"
            draftCountValue?.stringValue = "—"
            latestDraftLabel?.stringValue = "저장된 카드·영상을 읽을 권한이 필요해요"
            latestDraftButton?.isEnabled = false
            latestProofButton?.isEnabled = false
            draftListSignature = ""
            videoListSignature = ""
            renderDraftChoices()
            renderVideoChoices()
            refreshPipelineAction()
            return
        }
        hasProjectAccess = (try? Data(contentsOf: dailyScriptURL)) != nil
        if let data = try? Data(contentsOf: fetchStateURL),
           let state = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            needsHistoryBackfill = state["history_complete"] as? Bool != true
        } else {
            needsHistoryBackfill = true
        }
        let snapshots = (try? FileManager.default.contentsOfDirectory(at: snapshotURL,
                                                                      includingPropertiesForKeys: [.contentModificationDateKey],
                                                                      options: [.skipsHiddenFiles])) ?? []
        let orderedSnapshots = snapshots
            .filter { $0.lastPathComponent.hasPrefix("threads-") && $0.pathExtension == "json" }
            .sorted { $0.lastPathComponent > $1.lastPathComponent }
        lastSnapshotCount = 0
        lastSnapshotDate = nil
        var detectedHandle: String?
        for (index, snapshot) in orderedSnapshots.enumerated() {
            guard let data = try? Data(contentsOf: snapshot),
                  let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { continue }
            if index == 0 {
                lastSnapshotCount = object["new_count"] as? Int ?? 0
                if let raw = object["fetched_at"] as? String {
                    let formatter = ISO8601DateFormatter()
                    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
                    lastSnapshotDate = formatter.date(from: raw) ?? ISO8601DateFormatter().date(from: raw)
                }
            }
            if detectedHandle == nil,
               let posts = object["posts"] as? [[String: Any]],
               let raw = posts.first?["username"] as? String {
                let username = raw.trimmingCharacters(in: .whitespacesAndNewlines)
                if !username.isEmpty {
                    detectedHandle = username.hasPrefix("@") ? username : "@\(username)"
                }
            }
            if index > 0 && detectedHandle != nil { break }
        }
        accountHandle = detectedHandle ?? "Threads 계정"
        drafts = loadDraftFolders()
        readyRenders = loadReadyRenders()
        cardNewsPackages = loadCardNewsPackages()
        if selectedDraftURL == nil || !drafts.contains(where: { $0.url == selectedDraftURL }) {
            selectedDraftURL = drafts.first?.url
        }
        awaitingAudioRenders = loadAwaitingAudioRenders()
        layerRepairRenders = loadLayerRepairRenders()
        isWaitingForChatGPT = FileManager.default.fileExists(atPath: waitingURL.path)
        isWaitingForWebImages = false
        if let data = try? Data(contentsOf: queueURL.appendingPathComponent(".chatgpt-web-images-current.json")),
           let current = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let path = current["job"] as? String {
            let job = URL(fileURLWithPath: path).resolvingSymlinksInPath().standardizedFileURL
            let prefix = queueURL.resolvingSymlinksInPath().standardizedFileURL.path + "/"
            if job.path.hasPrefix(prefix),
               let stateData = try? Data(contentsOf: job),
               let state = try? JSONSerialization.jsonObject(with: stateData) as? [String: Any] {
                let stateName = state["status"] as? String
                isWaitingForWebImages = stateName != "complete" && stateName != "images_ready"
            }
        }
        storedPostsValue?.stringValue = "\(storedPostCount)"
        draftCountValue?.stringValue = "\(readyRenders.count)"
        if let latestCards = cardNewsPackages.first {
            cardNewsPackageLabel?.stringValue = "\(latestCards.title) · 카드 \(latestCards.cardURLs.count)장 · \(shortDate(latestCards.date))"
            cardNewsPackageLabel?.toolTip = latestCards.folderURL.path
        } else {
            cardNewsPackageLabel?.stringValue = "아직 검수 완료된 카드가 없어요"
            cardNewsPackageLabel?.toolTip = generatedCardsURL.path
        }
        renderDraftChoices()
        renderVideoChoices()
        refreshPipelineAction()
    }

    private static func threadPlanURL(in folder: URL) -> URL? {
        let original = folder.appendingPathComponent("card-plan.json")
        guard let data = try? Data(contentsOf: folder.appendingPathComponent("source-thread.json")),
              let thread = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              thread["version"] as? Int == 2, thread["verified"] as? Bool == true else { return original }
        if thread["uses_user_override"] as? Bool == true { return original }
        if thread["numbered_gap"] is [String: Any] { return original }
        if let excluded = thread["excluded"] as? [[String: Any]],
           excluded.contains(where: { $0["reason"] as? String == "missing_parent" }) { return original }
        guard let relative = thread["plan_file"] as? String else {
            return original
        }
        guard !relative.hasPrefix("/"), !relative.split(separator: "/").contains("..") else { return nil }
        let root = folder.resolvingSymlinksInPath().standardizedFileURL.path + "/"
        let target = folder.appendingPathComponent(relative).resolvingSymlinksInPath().standardizedFileURL
        guard target.path.hasPrefix(root), FileManager.default.fileExists(atPath: target.path) else { return nil }
        return target
    }

    private func loadDraftFolders() -> [DraftFolder] {
        let dateFolders = (try? FileManager.default.contentsOfDirectory(at: queueURL,
                                                                         includingPropertiesForKeys: [.isDirectoryKey],
                                                                         options: [.skipsHiddenFiles])) ?? []
        var result: [DraftFolder] = []
        var storedIDs = Set<String>()
        for dateFolder in dateFolders {
            guard (try? dateFolder.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true,
                  dateFolder.lastPathComponent.range(of: #"^20\d\d-\d\d-\d\d$"#, options: .regularExpression) != nil else { continue }
            let children = (try? FileManager.default.contentsOfDirectory(at: dateFolder,
                                                                          includingPropertiesForKeys: [.isDirectoryKey, .contentModificationDateKey],
                                                                          options: [.skipsHiddenFiles])) ?? []
            for folder in children {
                guard (try? folder.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true,
                      let sourceData = try? Data(contentsOf: folder.appendingPathComponent("source.json")),
                      let source = try? JSONSerialization.jsonObject(with: sourceData) as? [String: Any] else { continue }
                if let id = source["id"] as? String, !id.isEmpty { storedIDs.insert(id) }
                guard FileManager.default.fileExists(atPath: folder.appendingPathComponent("card-copy.md").path),
                      FileManager.default.fileExists(atPath: folder.appendingPathComponent("reel-script.md").path) else { continue }
                guard let planURL = Self.threadPlanURL(in: folder),
                      let planData = try? Data(contentsOf: planURL),
                      let plan = try? JSONSerialization.jsonObject(with: planData) as? [String: Any],
                      plan["content_ready"] as? Bool == true else { continue }
                let modified = (try? folder.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
                var displayText = source["text"] as? String ?? ""
                var replyCount = 0
                var replyNote = ""
                if let threadData = try? Data(contentsOf: folder.appendingPathComponent("source-thread.json")),
                   let thread = try? JSONSerialization.jsonObject(with: threadData) as? [String: Any],
                   thread["version"] as? Int == 2, thread["verified"] as? Bool == true {
                    let excluded = thread["excluded"] as? [[String: Any]] ?? []
                    if excluded.contains(where: { $0["reason"] as? String == "missing_parent" }) {
                        replyNote = " · 후속 댓글 연결 확인 필요"
                    } else if thread["numbered_gap"] is [String: Any] {
                        replyNote = " · 후속 원문 누락 확인 필요"
                    } else if thread["plan_error"] as? String != nil {
                        replyNote = " · 전체 원문 카드 배분 필요"
                    } else if plan["source_complete_thread"] as? Bool == true {
                        displayText = thread["text"] as? String ?? displayText
                        replyCount = thread["reply_count"] as? Int ?? 0
                    }
                }
                if displayText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                   plan["source_file"] as? String == "source-full.txt",
                   let fullText = try? String(contentsOf: folder.appendingPathComponent("source-full.txt"), encoding: .utf8) {
                    displayText = fullText
                }
                if displayText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                   let cards = plan["cards"] as? [[String: Any]],
                   let firstCardText = cards.first?["source_text"] as? String {
                    displayText = firstCardText
                }
                guard Self.hasUsableDraftText(displayText) else { continue }
                let title = displayText.split(whereSeparator: \.isNewline).first.map(String.init) ?? "Threads 글"
                let excerpt = displayText.replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression)
                let label = "\(accountHandle) · \(shortDate(modified))" + (replyCount > 0 ? " · 이어 쓴 댓글 \(replyCount)개 포함" : replyNote)
                result.append(DraftFolder(url: folder, planURL: planURL, date: modified,
                                          sourceID: source["id"] as? String ?? folder.lastPathComponent,
                                          title: title, excerpt: excerpt, label: label))
            }
        }
        storedPostCount = storedIDs.count
        return result.sorted { $0.date > $1.date }
    }

    private func loadCardNewsPackages() -> [CardNewsPackage] {
        let folders = (try? FileManager.default.contentsOfDirectory(at: generatedCardsURL,
                                                                     includingPropertiesForKeys: [.isDirectoryKey, .contentModificationDateKey],
                                                                     options: [.skipsHiddenFiles])) ?? []
        let root = generatedCardsURL.resolvingSymlinksInPath().standardizedFileURL
        var packages: [CardNewsPackage] = []
        for folder in folders where (try? folder.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true {
            let manifest = folder.appendingPathComponent("cards.json")
            guard let data = try? Data(contentsOf: manifest),
                  let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  object["reviewed"] as? Bool == true,
                  let records = object["cards"] as? [[String: Any]], (4...12).contains(records.count) else { continue }
            var files: [URL] = []
            var valid = true
            for (index, record) in records.enumerated() {
                guard record["number"] as? Int == index + 1, record["review"] as? String == "pass",
                      let relative = record["file"] as? String, !relative.hasPrefix("/"),
                      !relative.split(separator: "/").contains(".."),
                      let expected = record["source_sha256"] as? String else { valid = false; break }
                let file = folder.appendingPathComponent(relative).resolvingSymlinksInPath().standardizedFileURL
                guard file.path.hasPrefix(root.path + "/"),
                      let image = try? Data(contentsOf: file),
                      SHA256.hash(data: image).map({ String(format: "%02x", $0) }).joined() == expected else {
                    valid = false; break
                }
                files.append(file)
            }
            guard valid else { continue }
            let modified = (try? manifest.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            packages.append(CardNewsPackage(folderURL: folder, manifestURL: manifest, date: modified,
                                            title: object["title"] as? String ?? "카드뉴스", cardURLs: files))
        }
        return packages.sorted { $0.date > $1.date }
    }

    private func loadReadyRenders() -> [ReadyRender] {
        var result: [ReadyRender] = []
        for folder in productionFolders() {
            let marker = folder.appendingPathComponent("renders/latest.json")
            guard let data = try? Data(contentsOf: marker),
                  let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  object["status"] as? String == "ready_for_review",
                  let videoPath = object["video"] as? String,
                  let proofPath = object["proof"] as? String,
                  isCurrentRender(object, folder: folder, marker: marker) else { continue }
            let videoURL = URL(fileURLWithPath: videoPath)
            let proofURL = URL(fileURLWithPath: proofPath)
            guard FileManager.default.fileExists(atPath: videoURL.path),
                  FileManager.default.fileExists(atPath: proofURL.path) else { continue }
            let modified = (try? marker.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            let title = packageTitle(folder) ?? accountHandle
            let label = "\(title)\n\(shortDate(modified)) · 검수 대기"
            result.append(ReadyRender(folderURL: folder, videoURL: videoURL, proofURL: proofURL,
                                      date: modified, label: label))
        }
        return result.sorted { $0.date > $1.date }
    }

    private func isCurrentRender(_ markerData: [String: Any], folder: URL, marker: URL) -> Bool {
        let package = folder.resolvingSymlinksInPath().standardizedFileURL
        func contained(_ relative: String) -> URL? {
            guard !relative.isEmpty, !relative.hasPrefix("/"),
                  !relative.split(separator: "/").contains("..") else { return nil }
            let path = package.appendingPathComponent(relative).resolvingSymlinksInPath().standardizedFileURL
            return path.path.hasPrefix(package.path + "/") ? path : nil
        }
        func sha(_ file: URL) -> String? {
            guard let data = try? Data(contentsOf: file) else { return nil }
            return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        }
        if let inputs = markerData["source_inputs"] as? [[String: Any]] {
            guard !inputs.isEmpty else { return false }
            return inputs.allSatisfy { item in
                guard let relative = item["file"] as? String, let expected = item["sha256"] as? String,
                      let file = contained(relative) else { return false }
                return sha(file) == expected
            }
        }
        // Older approved packages predate hash-bound markers. Keep their
        // previews only while neither their plan nor source files are newer.
        let modified = (try? marker.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
        let manifest = package.appendingPathComponent("reel-production.json")
        guard let data = try? Data(contentsOf: manifest),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let cards = object["cards"] as? [[String: Any]] else {
            let spec = package.appendingPathComponent("card-render/spec.json")
            return ((try? spec.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantFuture) <= modified
        }
        if let plan = object["motion_plan"] as? [String: Any],
           plan["generator"] as? String == "auto_plan",
           cards.contains(where: { ($0["layers_file"] as? String)?.isEmpty != false }) {
            return false
        }
        guard ((try? manifest.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantFuture) <= modified else { return false }
        return cards.allSatisfy { card in
            guard let relative = card["file"] as? String, let file = contained(relative),
                  ((try? file.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantFuture) <= modified else { return false }
            return (card["source_sha256"] as? String).map { sha(file) == $0 } ?? true
        }
    }

    private func loadAwaitingAudioRenders() -> [AwaitingAudioRender] {
        var result: [AwaitingAudioRender] = []
        for folder in productionFolders() {
            let marker = folder.appendingPathComponent("renders/latest.json")
            guard let data = try? Data(contentsOf: marker),
                  let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  object["status"] as? String == "awaiting_audio" else { continue }
            let modified = (try? marker.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            let label = "릴스 음원 선택 대기 · \(shortDate(modified))"
            result.append(AwaitingAudioRender(date: modified, label: label))
        }
        return result.sorted { $0.date > $1.date }
    }

    private func loadLayerRepairRenders() -> [LayerRepairRender] {
        var result: [LayerRepairRender] = []
        for folder in productionFolders() {
            let marker = folder.appendingPathComponent("renders/latest.json")
            guard let data = try? Data(contentsOf: marker),
                  let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  object["status"] as? String == "needs_layer_repair" else { continue }
            let modified = (try? marker.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            let count = (object["repair_cards"] as? [Any])?.count ?? 0
            let label = "원본 레이어 복구 필요 · \(count)장 · \(shortDate(modified))"
            result.append(LayerRepairRender(date: modified, label: label))
        }
        return result.sorted { $0.date > $1.date }
    }

    private func productionFolders() -> [URL] {
        func folders(_ parent: URL) -> [URL] {
            let children = (try? FileManager.default.contentsOfDirectory(
                at: parent, includingPropertiesForKeys: [.isDirectoryKey],
                options: [.skipsHiddenFiles])) ?? []
            return children.filter {
                (try? $0.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true
            }
        }
        let dated = folders(queueURL).filter {
            $0.lastPathComponent.range(of: #"^20\d\d-\d\d-\d\d$"#, options: .regularExpression) != nil
        }
        return dated.flatMap(folders) +
            folders(projectRoot.appendingPathComponent("content/card-news", isDirectory: true)) +
            folders(projectPath("reels_root", fallback: "content/reels")) +
            folders(reelWorkURL)
    }

    private func packageTitle(_ folder: URL) -> String? {
        let manifest = folder.appendingPathComponent("reel-production.json")
        guard let data = try? Data(contentsOf: manifest),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let title = object["deck_title"] as? String, !title.isEmpty else { return nil }
        return title
    }

    private func latestApprovedManifest() -> URL? {
        productionFolders().compactMap { folder -> (URL, Date)? in
            let manifest = folder.appendingPathComponent("reel-production.json")
            guard let data = try? Data(contentsOf: manifest),
                  let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  object["reviewed"] as? Bool == true else { return nil }
            let automatic = (object["motion_plan"] as? [String: Any])?["generator"] as? String == "auto_plan"
                || object["source_kind"] as? String == "card_render"
            if automatic {
                guard let cards = object["cards"] as? [[String: Any]], !cards.isEmpty,
                      cards.allSatisfy({ ($0["layers_file"] as? String)?.isEmpty == false }) else {
                    return nil
                }
            }
            let hasGeneratedCardSpec = FileManager.default.fileExists(
                atPath: folder.appendingPathComponent("card-render/spec.json").path)
            // Generated cards with the new element-story renderer are safe to
            // select: the local pipeline analyzes their recorded layout first.
            let generatedAutoPackage = object["source_kind"] as? String == "card_render"
            guard !hasGeneratedCardSpec || !generatedAutoPackage ||
                    object["renderer"] as? String == "hyperframes_element_story" else {
                return nil
            }
            let modified = (try? manifest.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast
            return (manifest, modified)
        }.sorted { $0.1 > $1.1 }.first?.0
    }

    func localRenderCheck() -> [String: Any] {
        var result: [String: Any] = ["readyVideoCount": loadReadyRenders().count]
        if let manifest = latestApprovedManifest() {
            result["selectedManifest"] = manifest.path
            result["renderArguments"] = [dailyScriptURL.path, "--only-render", "--manifest", manifest.path]
            if let data = try? Data(contentsOf: manifest),
               let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                result["autoMotion"] = object["renderer"] as? String == "hyperframes_element_story"
            }
        }
        if let latest = loadReadyRenders().first {
            result["latestVideo"] = latest.videoURL.path
            result["latestProof"] = latest.proofURL.path
            result["latestTitle"] = packageTitle(latest.folderURL) ?? latest.folderURL.lastPathComponent
        }
        return result
    }

    func runtimeCheck() -> [String: Any] {
        var result = localRenderCheck()
        if let data = try? Data(contentsOf: fetchStateURL),
           let state = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            needsHistoryBackfill = state["history_complete"] as? Bool != true
        }
        result["projectRoot"] = projectRoot.path
        result["reelsFolder"] = reelsURL.path
        result["reelsWorkFolder"] = reelWorkURL.path
        result["python"] = pythonURL?.path ?? "없음"
        result["scriptsExist"] = [fetchScriptURL, dailyScriptURL].allSatisfy {
            FileManager.default.fileExists(atPath: $0.path)
        }
        result["fetchArguments"] = fetchArguments
        result["historyBackfillNeeded"] = needsHistoryBackfill
        result["cardsArguments"] = [dailyScriptURL.path, "--web-images", "--plan", "<selected card-plan.json>", "--no-reel"]
        result["legacyCardsArguments"] = [dailyScriptURL.path, "--only-cards"]
        result["safariCheckArguments"] = [dailyScriptURL.path, "--web-images-check"]
        result["imageArguments"] = [dailyScriptURL.path, "--from-images"]
        result["automaticPublishing"] = false
        let drafts = loadDraftFolders()
        result["storedPostCount"] = storedPostCount
        result["selectablePostCount"] = drafts.count
        result["postsWithAuthorReplies"] = drafts.filter { $0.planURL.deletingLastPathComponent().lastPathComponent.hasPrefix("complete-thread-") }.count
        result["requiresProjectFolderSelection"] = true
        result["log"] = logURL.path
        return result
    }

    func selfTest() -> [String: Any] {
        let sample = "Bearer fixture-secret\naccess_token=fixture-token\nhttps://example.com/test?token=fixture-query"
        let clean = Self.sanitized(sample)
        let awaiting = Self.cardWorkflowStatus(status: 1,
            output: #"{"waiting":true,"handoff_state":"awaiting_answer"}"#)
        let partial = Self.cardWorkflowStatus(status: 1,
            output: #"{"ok":1,"waiting":true,"handoff_state":"partial_answer"}"#)
        let retry = Self.cardWorkflowStatus(status: 1,
            output: #"{"waiting":true,"handoff_state":"retry_processing"}"#)
        let blocked = Self.cardWorkflowStatus(status: 1,
            output: #"{"waiting":true,"handoff_state":"blocked","note":"/private/source.json"}"#)
        let complete = Self.cardWorkflowStatus(status: 0,
            output: #"{"posts":2,"ok":2,"waiting":false,"handoff_state":"complete"}"#)
        let empty = Self.cardWorkflowStatus(status: 0,
            output: #"{"posts":0,"note":"카드로 만들 새 글이 없습니다"}"#)
        let mixedWait = Self.cardWorkflowStatus(status: 1,
            output: #"{"ok":1,"handoff_state":"awaiting_answer","results":[{"state":"failed","retry_processing":true}]}"#)
        let reelPending = Self.cardWorkflowStatus(status: 1,
            output: #"{"posts":1,"ok":0,"cards_ok":1,"handoff_state":"complete"}"#)
        let webComplete = Self.webImageStatus(status: 0, output: #"{"web_image_state":"complete","cards_saved":5}"#)
        let webBrowser = Self.webImageStatus(status: 1, output: #"{"web_image_state":"browser_pending","cards_saved":1,"note":"Safari 설정 필요"}"#)
        let webReview = Self.webImageStatus(status: 1, output: #"{"web_image_state":"needs_review","cards_saved":5}"#)
        let webRender = Self.webImageStatus(status: 1, output: #"{"web_image_state":"render_pending","cards_saved":5}"#)
        let webCheck = Self.webImageStatus(status: 0, output: #"{"web_image_state":"preflight_ok"}"#)
        let checks: [String: Bool] = [
            "reelsFolderOpensReadableVideos": reelsURL.lastPathComponent == "완성 영상",
            "sharedPathConfigurationConnected": configuredPaths["reels_work"] == "content/reels/제작 자료",
            "listPreviewDoesNotRepeatHeading": Self.listExcerpt(title: "📌 제목", fullText: "📌 제목\n다음 본문") == "다음 본문",
            "listPreviewKeepsDifferentOpening": Self.listExcerpt(title: "제목", fullText: "다른 본문") == "다른 본문",
            "listTitleOnlyRemovesLeadingDecoration": Self.listTitle("📌 제목 🌙") == "제목 🌙",
            "listEmptyBodyDoesNotRepeatHeading": Self.listExcerpt(title: "제목", fullText: "제목").isEmpty,
            "draftPlaceholderRejected": !Self.hasUsableDraftText("원문 텍스트가 없어 문안을 만들 수 없습니다."),
            "realDraftTextAccepted": Self.hasUsableDraftText("실제 게시글 원문입니다\n두 번째 줄"),
            "fetchDoesNotRender": fetchArguments.contains("--skip-render") && fetchArguments.contains("--skip-cards"),
            "credentialsRedacted": !clean.contains("fixture-"),
            "networkErrorReadable": !Self.safeError("File \"/opt/homebrew/python.py\"\nThreads API 연결 실패: nodename nor servname").contains("/opt/"),
            "authErrorReadable": Self.safeError("HTTP 401 OAuthException").contains("인증 만료"),
            "missingRuntimeReadable": Self.safeError("python3: can't open file '/missing/script.py'").contains("실행 파일"),
            "projectConnected": [dailyScriptURL, fetchScriptURL].allSatisfy { FileManager.default.fileExists(atPath: $0.path) },
            "runtimeConnected": pythonURL != nil,
            "historyBackfillRouted": Self.fetchArguments(script: dailyScriptURL, backfill: true)
                .contains("--backfill-history"),
            "incrementalFetchRouted": !Self.fetchArguments(script: dailyScriptURL, backfill: false)
                .contains("--backfill-history"),
            "rejectsBroaderFolderGrant": !isProjectFolder(projectRoot.deletingLastPathComponent()),
            "cardAnswerWaitIsNotFailure": !awaiting.error && awaiting.message.contains("복사"),
            "partialCardsRemainVisible": partial.error && partial.message.contains("1개 완료"),
            "cardSaveFailureOffersLocalRetry": retry.error && retry.message.contains("보관") &&
                !retry.message.contains("복사"),
            "blockedCardsDoNotLeakPaths": blocked.error && !blocked.message.contains("/private/"),
            "cardCompletionCountVisible": !complete.error && complete.message.contains("2개 완료"),
            "emptyCardQueueNotCalledComplete": !empty.error && !empty.message.contains("제작 완료"),
            "mixedCardFailureIsNotHiddenByAnswerWait": mixedWait.error && mixedWait.message.contains("제작 실패"),
            "unfinishedReelNotCalledSuccessful": reelPending.error && reelPending.message.contains("남은 영상"),
            "webImagesCompletionRequiresVideo": !webComplete.error && webComplete.message.contains("릴스 완성"),
            "webBrowserFailureNotCalledComplete": webBrowser.error && webBrowser.message.contains("Safari 설정"),
            "webUnreviewedImagesBlockReel": webReview.error && webReview.message.contains("릴스 중단"),
            "webRenderPendingOffersRetry": webRender.error && webRender.message.contains("이어받기"),
            "webConnectionCheckDoesNotClaimNoPriorImages": !webCheck.error && webCheck.message.contains("새 요청") && !webCheck.message.contains("아직 이미지")
        ]
        return ["checks": checks, "passed": checks.values.allSatisfy { $0 }]
    }

    // Render the same AppKit view offscreen, without touching the user's desktop.
    private func checkListInteractions() -> [String: Bool] {
        guard let stack = draftListStack, let scroll = draftScrollView,
              let search = draftSearchField else { return ["listViewsConnected": false] }
        let originalSelection = selectedDraftURL
        let originalQuery = search.stringValue
        var checks: [String: Bool] = [
            "draftDocumentStartsAtTop": scroll.documentView?.isFlipped == true,
            "videoDocumentStartsAtTop": videoScrollView?.documentView?.isFlipped == true,
            "listFitsAvailableWidth": stack.arrangedSubviews.allSatisfy {
                $0.frame.width <= scroll.contentView.bounds.width && $0.frame.width > 0
            }
        ]
        if drafts.count > 1, let second = stack.arrangedSubviews.dropFirst().first as? NSButton {
            second.performClick(nil)
            checks["clickSelectsCorrectPost"] = selectedDraftURL == drafts[1].url
            scroll.contentView.scroll(to: NSPoint(x: 0, y: 74))
            scroll.reflectScrolledClipView(scroll.contentView)
            let previousOffset = scroll.contentView.bounds.origin.y
            if let row = stack.arrangedSubviews.first as? NSButton { row.performClick(nil) }
            checks["selectionPreservesScroll"] = abs(scroll.contentView.bounds.origin.y - previousOffset) < 1
            search.stringValue = drafts[1].sourceID
            draftListSignature = ""
            renderDraftChoices()
            if let result = stack.arrangedSubviews.first as? NSButton {
                result.performClick(nil)
                checks["filteredRowSelectsOriginalPost"] = selectedDraftURL == drafts[1].url
            } else {
                checks["filteredRowSelectsOriginalPost"] = false
            }
            checks["newSearchStartsAtTop"] = scroll.contentView.bounds.origin.y == 0
        }
        search.stringValue = "no-matching-post-4d9f25d9"
        draftListSignature = ""
        renderDraftChoices()
        checks["emptySearchHasNoSelectableRow"] = !stack.arrangedSubviews.contains { $0 is DraftSelectionRow }
            && draftResultCountLabel?.stringValue == "0개"
        search.stringValue = originalQuery
        selectedDraftURL = originalSelection
        draftListSignature = ""
        renderDraftChoices()
        rootView.layoutSubtreeIfNeeded()
        return checks
    }

    func renderPreview(to output: URL, errorState: Bool) throws -> [String: Any] {
        isPreview = true
        isConfigured = true
        mascot = Bundle.main.url(forResource: "cinnamoroll-widget-mascot", withExtension: "png")
            .flatMap(NSImage.init(contentsOf:))
        panel = FloatingWidgetPanel(contentRect: NSRect(origin: .zero, size: expandedSize),
                                    styleMask: [.borderless], backing: .buffered, defer: false)
        panel.isReleasedWhenClosed = false
        panel.title = "시나모롤 콘텐츠 위젯 미리보기"
        panel.appearance = NSAppearance(named: .aqua)
        panel.contentView = rootView
        rootView.frame = NSRect(origin: .zero, size: expandedSize)
        showExpanded()
        if errorState { setStatus(Self.safeError("Threads API 연결 실패: nodename nor servname"), error: true) }
        let listChecks = checkListInteractions()
        rootView.layoutSubtreeIfNeeded()
        guard let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil,
            pixelsWide: Int(expandedSize.width * 2), pixelsHigh: Int(expandedSize.height * 2),
            bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
            colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) else {
            throw NSError(domain: "WidgetPreview", code: 1)
        }
        bitmap.size = expandedSize
        rootView.cacheDisplay(in: rootView.bounds, to: bitmap)
        guard let data = bitmap.representation(using: .png, properties: [:]) else {
            throw NSError(domain: "WidgetPreview", code: 2)
        }
        try FileManager.default.createDirectory(at: output.deletingLastPathComponent(), withIntermediateDirectories: true)
        try data.write(to: output, options: .atomic)
        func allSubviews(_ view: NSView) -> [NSView] { view.subviews.flatMap { [$0] + allSubviews($0) } }
        let controls = allSubviews(rootView).compactMap { view -> [String: Any]? in
            guard view is NSButton || view is NSTextField else { return nil }
            let frame = view.convert(view.bounds, to: rootView)
            let text = (view as? NSTextField)?.stringValue ?? (view as? NSButton)?.title ?? ""
            var ancestor = view.superview
            var scrollContent = false
            while let parent = ancestor {
                if parent is ListDocumentView { scrollContent = true; break }
                ancestor = parent.superview
            }
            return ["text": String(text.prefix(120)), "insidePanel": rootView.bounds.insetBy(dx: -1, dy: -1).contains(frame),
                    "scrollContent": scrollContent,
                    "x": frame.minX, "y": frame.minY, "width": frame.width, "height": frame.height,
                    "enabled": (view as? NSButton)?.isEnabled ?? true]
        }
        return ["preview": output.path, "controls": controls, "listChecks": listChecks,
                "allListChecksPassed": listChecks.values.allSatisfy { $0 },
                "allControlsInsidePanel": controls.allSatisfy {
                    $0["scrollContent"] as? Bool == true || $0["insidePanel"] as? Bool == true
                }]
    }

    private func shortDate(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "ko_KR")
        formatter.dateFormat = "M월 d일"
        return formatter.string(from: date)
    }

    private func showLastFetchStatus() {
        if let date = lastSnapshotDate {
            setStatus("\(shortDate(date)) 조회 · 새로 추가 \(lastSnapshotCount)개")
        } else {
            setStatus("새 글을 불러오거나 카드 이미지를 선택하세요")
        }
    }

    private func showIdleStatus() {
        if readyRenders.isEmpty, !layerRepairRenders.isEmpty {
            setStatus("미완성 카드가 있어요 · 카드 이미지를 다시 선택하세요")
        } else if readyRenders.isEmpty, !awaitingAudioRenders.isEmpty {
            setStatus("카드 완성 · 릴스 음원 선택 대기 \(awaitingAudioRenders.count)개")
        } else {
            showLastFetchStatus()
        }
    }

    private func setConnection(_ configured: Bool, checking: Bool = false) {
        isConfigured = configured
        isCheckingConfiguration = checking
        connectionLabel?.stringValue = !hasProjectAccess ? "저장 파일 접근 필요" : checking ? "Threads 설정 확인 중" :
            configured ? "Threads 설정 있음 · 수동 조회" : "Threads 설정 없음 · 이미지 제작은 가능"
        connectionDot?.layer?.backgroundColor = !hasProjectAccess ? Palette.red.cgColor : checking ? Palette.blue.cgColor :
            configured ? Palette.green.cgColor : Palette.red.cgColor
        refreshPipelineAction()
    }

    private func refreshPipelineAction() {
        importCardsButton?.isEnabled = !isRunningPipeline && hasProjectAccess
        statusActionButton?.title = hasProjectAccess ? "기록" : "접근 허용"
        statusActionButton?.setAccessibilityLabel(statusActionButton?.title ?? "기록")
        renderApprovedButton?.isEnabled = !isRunningPipeline && hasProjectAccess && latestApprovedManifest() != nil
        queueButton?.isEnabled = hasProjectAccess
        makeCardsButton?.isEnabled = !isRunningPipeline && hasProjectAccess
            && (isWaitingForChatGPT || isWaitingForWebImages || selectedDraftIsVisible)
        makeCardsButton?.title = isWaitingForChatGPT ? "기존 카드 답변 이어받기" :
            isWaitingForWebImages ? "카드뉴스 제작 이어받기" : "선택한 글로 카드뉴스 만들기"
        makeCardsButton?.setAccessibilityLabel(makeCardsButton?.title ?? "선택한 글로 카드뉴스 만들기")
        makeReelButton?.isEnabled = !isRunningPipeline && hasProjectAccess && !cardNewsPackages.isEmpty
        cardNewsFolderButton?.isEnabled = hasProjectAccess
        stopButton?.isHidden = !isRunningPipeline
        stopButton?.isEnabled = isRunningPipeline && !cancelRequested
        runButton?.isEnabled = !isRunningPipeline && isConfigured && !isCheckingConfiguration
        if !isRunningPipeline { setPrimaryTitle(needsHistoryBackfill ? "전체 글 불러오기" : "새 글 불러오기") }
    }

    private func pendingWebPlanURL() -> URL? {
        guard let data = try? Data(contentsOf: queueURL.appendingPathComponent(".chatgpt-web-images-current.json")),
              let current = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let jobPath = current["job"] as? String, let planPath = current["plan"] as? String else { return nil }
        let queue = queueURL.resolvingSymlinksInPath().standardizedFileURL
        let job = URL(fileURLWithPath: jobPath).resolvingSymlinksInPath().standardizedFileURL
        let plan = URL(fileURLWithPath: planPath).resolvingSymlinksInPath().standardizedFileURL
        guard job.path.hasPrefix(queue.path + "/"), plan.path.hasPrefix(queue.path + "/"),
              let stateData = try? Data(contentsOf: job),
              let state = try? JSONSerialization.jsonObject(with: stateData) as? [String: Any],
              let status = state["status"] as? String,
              status != "complete", status != "images_ready",
              FileManager.default.fileExists(atPath: plan.path) else { return nil }
        return plan
    }

    @objc private func selectDraft(_ sender: NSButton) {
        guard drafts.indices.contains(sender.tag) else { return }
        selectedDraftURL = sender.state == .on ? drafts[sender.tag].url : nil
        draftListSignature = ""
        renderDraftChoices()
    }

    func controlTextDidChange(_ notification: Notification) {
        guard let field = notification.object as? NSSearchField, field === draftSearchField else { return }
        draftListSignature = ""
        renderDraftChoices()
    }

    @objc private func makeSelectedCards() {
        guard !isRunningPipeline, hasProjectAccess else { return }
        if isWaitingForChatGPT {
            makeChatGPTCards()
            return
        }
        // A pending Safari job is resumed only while the UI says it is waiting.
        // Otherwise honor the post the user explicitly selected.
        let plan = isWaitingForWebImages ? pendingWebPlanURL() :
            drafts.first(where: { $0.url == selectedDraftURL })?.planURL
        guard let plan else {
            setStatus("글을 선택한 뒤 카드뉴스 만들기를 눌러주세요", error: true)
            return
        }
        beginWork("선택한 글로 카드뉴스 생성·원문 검수 중…")
        runPython(arguments: [dailyScriptURL.path, "--web-images", "--plan", plan.path, "--no-reel"]) { [weak self] status, output in
            guard let self else { return }
            if self.endWork() { return }
            let result = Self.webImageStatus(status: status, output: output)
            if status == 0, let entry = Self.parseJSONLines(output).last(where: { $0["web_image_state"] != nil }),
               entry["web_image_state"] as? String == "images_ready" {
                self.setStatus("카드 \(entry["cards_saved"] as? Int ?? 0)장 검수 완료 · 카드뉴스 모음에 저장 · 아래에서 릴스를 만들 수 있어요")
            } else {
                self.setStatus(result.message, error: result.error)
            }
        }
    }

    @objc private func makeReelFromLatestCards() {
        guard !isRunningPipeline, hasProjectAccess, let cards = cardNewsPackages.first else {
            setStatus("릴스로 만들 검수 완료 카드가 없어요 · 먼저 글을 선택해 카드뉴스를 만들어주세요", error: true)
            return
        }
        beginWork("\(cards.title) · 카드 \(cards.cardURLs.count)장으로 릴스 만드는 중…")
        runPython(arguments: [dailyScriptURL.path, "--from-images"] + cards.cardURLs.map(\.path)
                  + ["--title", cards.title]) { [weak self] status, output in
            guard let self else { return }
            if self.endWork() { return }
            let completed = Self.parseJSONLines(output).compactMap { $0["packages"] as? [[String: Any]] }
                .flatMap { $0 }.filter { $0["status"] as? String == "ready_for_review" }.count
            self.setStatus(status == 0 && completed > 0 ? "릴스 완성 · 최근 완성 영상 목록에서 열 수 있어요" :
                Self.safeError(output), error: status != 0 || completed == 0)
        }
    }

    @objc private func stopPipeline() {
        guard isRunningPipeline, let process = currentProcess, process.isRunning else { return }
        cancelRequested = true
        stopButton?.isEnabled = false
        setStatus("중단 요청 중… 완료된 카드는 그대로 보관돼요")
        process.terminate()
    }

    @objc private func openGeneratedCards() {
        guard hasProjectAccess else { return }
        try? FileManager.default.createDirectory(at: generatedCardsURL, withIntermediateDirectories: true)
        open(generatedCardsURL)
    }

    @objc private func openReelsFolder() {
        guard hasProjectAccess else { return }
        try? FileManager.default.createDirectory(at: reelsURL, withIntermediateDirectories: true)
        open(reelsURL)
    }

    @objc private func openVideo(_ sender: NSButton) {
        guard let path = sender.identifier?.rawValue else { return }
        open(URL(fileURLWithPath: path))
    }

    private func checkConfiguration() {
        guard !isCheckingConfiguration && !isRunningPipeline else { return }
        guard hasProjectAccess else {
            setConnection(false)
            setStatus("카드·영상 파일을 읽도록 접근 허용이 필요해요")
            return
        }
        isCheckingConfiguration = true
        setConnection(isConfigured, checking: true)
        runPython(arguments: [fetchScriptURL.path, "--check-only"]) { [weak self] status, output in
            guard let self else { return }
            let configured = status == 0 && (Self.parseJSONLines(output).first?["configured"] as? Bool ?? false)
            self.setConnection(configured, checking: false)
            if self.lastStatus != nil {
                self.setStatus(self.lastStatus!, error: self.lastStatusIsError)
            } else if configured {
                self.showIdleStatus()
            } else {
                self.setStatus(Self.safeError(output), error: true)
            }
        }
    }

    @objc private func runPipeline() {
        guard !isRunningPipeline, isConfigured else { return }
        let backfilling = needsHistoryBackfill
        beginWork(backfilling ? "과거 글과 첨부 이미지를 빠짐없이 가져오는 중…" : "새 게시물과 첨부 이미지를 가져오는 중…")
        setPrimaryTitle(backfilling ? "전체 글 확인 중…" : "새 글 확인 중…")
        runPython(arguments: fetchArguments) { [weak self] status, output in
            guard let self else { return }
            if self.endWork() { return }
            let entries = Self.parseJSONLines(output)
            if status == 0 {
                let fetched = entries.first(where: { $0["new"] != nil })?["new"] as? Int ?? 0
                let transformed = entries.first(where: { $0["posts"] != nil })?["posts"] as? Int ?? 0
                self.setStatus(backfilling ? "과거 글 조회 완료 · 추가 \(fetched)개 · 보관 \(self.storedPostCount)개" :
                    fetched == 0 ? "새 글 없음 · 기존 초안은 그대로 유지" :
                    "조회 완료 · 새 글 \(fetched)개 · 초안 \(transformed)개")
            } else {
                self.setStatus(Self.safeError(output), error: true)
            }
        }
    }

    private static func fetchArguments(script: URL, backfill: Bool) -> [String] {
        [script.path, "--skip-cards", "--skip-render"] + (backfill ? ["--backfill-history"] : [])
    }

    private var fetchArguments: [String] {
        Self.fetchArguments(script: dailyScriptURL, backfill: needsHistoryBackfill)
    }

    @objc private func makeChatGPTCards() {
        guard !isRunningPipeline, hasProjectAccess,
              isWaitingForChatGPT || isWaitingForWebImages || !drafts.isEmpty else { return }
        let legacy = isWaitingForChatGPT
        beginWork(legacy ? "복사한 ChatGPT 답변으로 카드 만드는 중…" : "Safari 이미지 생성·검수·릴스 준비 중…")
        runPython(arguments: [dailyScriptURL.path, legacy ? "--only-cards" : "--web-images"]) { [weak self] status, output in
            guard let self else { return }
            if self.endWork() { return }
            let result = legacy ? Self.cardWorkflowStatus(status: status, output: output) :
                Self.webImageStatus(status: status, output: output)
            self.setStatus(result.message, error: result.error)
        }
    }

    @objc private func checkSafariImages() {
        guard !isRunningPipeline, hasProjectAccess else { return }
        beginWork("Safari 연결 확인 중 · 프롬프트 전송 안 함")
        runPython(arguments: [dailyScriptURL.path, "--web-images-check"]) { [weak self] status, output in
            guard let self else { return }
            if self.endWork() { return }
            let result = Self.webImageStatus(status: status, output: output)
            self.setStatus(result.message, error: result.error)
        }
    }

    private func beginWork(_ message: String) {
        cancelRequested = false
        isRunningPipeline = true
        refreshPipelineAction()
        setStatus(message)
        statusSpinner?.isHidden = false
        statusSpinner?.startAnimation(nil)
    }

    @discardableResult
    private func endWork() -> Bool {
        let cancelled = cancelRequested
        cancelRequested = false
        currentProcess = nil
        isRunningPipeline = false
        statusSpinner?.stopAnimation(nil)
        statusSpinner?.isHidden = true
        refreshLocalData()
        if cancelled { setStatus("작업을 중단했어요 · 저장된 카드는 그대로 보관돼요") }
        return cancelled
    }

    private func setStatus(_ message: String, error: Bool = false) {
        lastStatus = message
        lastStatusIsError = error
        statusLabel?.stringValue = message
        statusLabel?.textColor = error ? Palette.red : Palette.muted
        statusLabel?.toolTip = message
    }

    @objc private func renderApprovedCards() {
        guard !isRunningPipeline, hasProjectAccess, let manifest = latestApprovedManifest() else { return }
        beginWork("최근 카드의 요소별 영상 만드는 중…")
        runPython(arguments: [dailyScriptURL.path, "--only-render", "--manifest", manifest.path]) { [weak self] status, output in
            guard let self else { return }
            if self.endWork() { return }
            let packages = Self.parseJSONLines(output).compactMap { $0["packages"] as? [[String: Any]] }.flatMap { $0 }
            let completed = packages.filter { $0["status"] as? String == "ready_for_review" }.count
            self.setStatus(status == 0 && completed > 0 ? "영상 완성 · 영상 열기로 확인하세요" :
                Self.safeError(output), error: status != 0 || completed == 0)
        }
    }

    @objc private func importCardImages() {
        guard !isRunningPipeline, hasProjectAccess else { return }
        let picker = NSOpenPanel()
        picker.title = "카드 이미지로 릴스 만들기"
        picker.message = "4~12장 카드 선택 · 파일명의 페이지 번호 순서 · 원본 글과 그림 유지"
        picker.prompt = "릴스 만들기"
        picker.canChooseDirectories = false
        picker.allowsMultipleSelection = true
        picker.allowedContentTypes = [.png, .jpeg, .webP]
        guard picker.runModal() == .OK else { return }
        let images = picker.urls.sorted { $0.lastPathComponent.localizedStandardCompare($1.lastPathComponent) == .orderedAscending }
        guard (4...12).contains(images.count) else {
            setStatus("카드 이미지 4~12장을 선택하세요", error: true)
            return
        }
        beginWork("요소·배경 분리 → 모션·효과음 → 세로 영상")
        runPython(arguments: [dailyScriptURL.path, "--from-images"] + images.map(\.path)) { [weak self] status, output in
            guard let self else { return }
            if self.endWork() { return }
            let packages = Self.parseJSONLines(output).compactMap { $0["packages"] as? [[String: Any]] }.flatMap { $0 }
            let completed = packages.filter { $0["status"] as? String == "ready_for_review" }.count
            self.setStatus(status == 0 && completed > 0 ? "영상 완성 · 영상 열기로 확인하세요" :
                Self.safeError(output), error: status != 0 || completed == 0)
        }
    }

    private func setPrimaryTitle(_ title: String) {
        guard let button = runButton, let font = button.font else { return }
        button.attributedTitle = NSAttributedString(string: title, attributes: [
            .font: font, .foregroundColor: NSColor.white
        ])
        button.setAccessibilityLabel(title)
    }

    private func runPython(arguments: [String], completion: @escaping (Int32, String) -> Void) {
        guard FileManager.default.fileExists(atPath: dailyScriptURL.path),
              FileManager.default.fileExists(atPath: fetchScriptURL.path) else {
            completion(1, "자동화 프로그램 경로를 찾을 수 없습니다")
            return
        }
        guard let pythonURL else {
            completion(1, "Python 3.12 이상 실행 파일을 찾을 수 없습니다")
            return
        }
        let process = Process()
        process.executableURL = pythonURL
        process.arguments = arguments
        process.currentDirectoryURL = projectRoot
        var environment = ProcessInfo.processInfo.environment
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        environment["PATH"] = "\(home)/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        environment["VIBE_CONTENT_ROOT"] = projectRoot.path
        environment["PYTHONUNBUFFERED"] = "1"
        process.environment = environment
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe

        do {
            try process.run()
            currentProcess = process
            pipe.fileHandleForWriting.closeFile()
            DispatchQueue.global(qos: .utility).async {
                var data = Data()
                var pending = Data()
                while true {
                    let chunk = pipe.fileHandleForReading.availableData
                    if chunk.isEmpty { break }
                    data.append(chunk)
                    if arguments.contains("--web-images") {
                        pending.append(chunk)
                        while let end = pending.firstIndex(of: 10) {
                            let lineData = pending.prefix(upTo: end)
                            pending.removeSubrange(...end)
                            if let line = String(data: lineData, encoding: .utf8),
                               let message = Self.webImageProgress(line) {
                                DispatchQueue.main.async { self.setStatus(message) }
                            }
                        }
                    }
                }
                process.waitUntilExit()
                let output = String(data: data, encoding: .utf8) ?? "프로그램 출력 읽기 실패"
                DispatchQueue.main.async {
                    if self.currentProcess?.processIdentifier == process.processIdentifier {
                        self.currentProcess = nil
                    }
                    if process.terminationStatus != 0 || !arguments.contains("--check-only") {
                        self.writeLog(arguments: arguments, status: process.terminationStatus, output: output)
                    }
                    completion(process.terminationStatus, output)
                }
            }
        } catch {
            pipe.fileHandleForWriting.closeFile()
            pipe.fileHandleForReading.closeFile()
            let output = "프로그램을 시작하지 못했습니다: \(error.localizedDescription)"
            writeLog(arguments: arguments, status: 1, output: output)
            completion(1, output)
        }
    }

    private static func parseJSONLines(_ output: String) -> [[String: Any]] {
        output.split(whereSeparator: \.isNewline).compactMap { line in
            guard let data = String(line).data(using: .utf8),
                  let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
            return object
        }
    }

    private static func webImageProgress(_ line: String) -> String? {
        guard let event = parseJSONLines(line).last else { return nil }
        let card = event["card"] as? Int ?? 0
        switch event["stage"] as? String {
        case "browser_opened": return "Safari 연결됨 · 카드 이미지 생성 중"
        case "image_requested": return "\(card)장 이미지 \(event["attempt"] as? Int == 2 ? "수정" : "생성") 중"
        case "review_requested": return "\(card)장 원문 대조 검수 중"
        case "image_saved": return "\(card)장 원본 저장 · 원문 대조 검수 중"
        case "reviewed": return "\(card)장 검수 · \(event["verdict"] as? String == "pass" ? "통과" : "수정·확인 필요")"
        case "render_requested": return "카드 검수 통과 · 요소 분리·모션·효과음·릴스 제작 중"
        default: return nil
        }
    }

    private static func webImageStatus(status: Int32, output: String) -> (message: String, error: Bool) {
        guard let result = parseJSONLines(output).last(where: { $0["web_image_state"] != nil }) else {
            return (safeError(output), true)
        }
        let count = result["cards_saved"] as? Int ?? 0
        switch result["web_image_state"] as? String {
        case "preflight_ok": return ("Safari 연결 확인됨 · 새 요청은 보내지 않음", status != 0)
        case "complete": return status == 0 ? ("카드 \(count)장·릴스 완성 · 영상 열기로 검수하세요", false) : ("완성 상태 확인 실패 · 실행 기록을 확인하세요", true)
        case "images_ready": return ("카드 \(count)장 검수·저장 완료 · 아래 ‘최근 카드뉴스로 릴스 만들기’를 누르세요", false)
        case "needs_review": return ("카드 \(count)장 보관 · 검수 미통과로 릴스 중단", true)
        case "render_pending": return ("카드 \(count)장 검수됨 · 이어받기로 영상 제작 재시도", true)
        case "browser_pending", "needs_attention":
            let note = result["note"] as? String ?? "실행 기록을 확인하세요"
            return (String(sanitized(note).prefix(110)), true)
        default: return ("웹 이미지 작업이 아직 완료되지 않았어요", true)
        }
    }

    // A retained handoff can mean a missing answer OR a local processing error.
    // Read the program result instead of treating any waiting file as a request
    // for the user to copy the same answer again.
    private static func cardWorkflowStatus(status: Int32, output: String) -> (message: String, error: Bool) {
        let entries = parseJSONLines(output)
        let result = entries.last(where: { $0["handoff_state"] != nil || $0["posts"] != nil })
        let completed = result?["ok"] as? Int ?? 0
        let prefix = completed > 0 ? "카드 \(completed)개 완료 · " : ""
        if status == 0 {
            if result?["posts"] as? Int == 0 { return ("새로 제작할 카드 없음 · 기존 결과는 유지", false) }
            return (completed > 0 ? "카드 \(completed)개 완료 · 초안 폴더에서 확인하세요" :
                "카드 처리 완료 · 초안 폴더에서 확인하세요", false)
        }
        switch result?["handoff_state"] as? String {
        case "awaiting_answer":
            let results = result?["results"] as? [[String: Any]] ?? []
            if results.contains(where: { $0["retry_processing"] as? Bool == true }) {
                return (prefix + "일부 제작 실패 · 미수신 답변을 복사하고 이어받으세요", true)
            }
            return (prefix + "ChatGPT 답변을 복사한 뒤 이어받기를 누르세요", false)
        case "partial_answer":
            return (prefix + "누락·검수 실패 답변이 있어요 · 수정 답변을 복사하고 이어받으세요", true)
        case "retry_processing":
            return (prefix + "카드 제작 실패 · 답변은 보관했어요 · 이어받기로 다시 시도하세요", true)
        case "blocked":
            return (prefix + "이어받기 중단 · 실행 기록에서 원인을 확인하세요", true)
        case "complete":
            return ("카드 문안 처리 완료 · 남은 영상 작업은 실행 기록을 확인하세요", true)
        default:
            return (safeError(output), true)
        }
    }

    private static func safeError(_ output: String) -> String {
        let text = sanitized(output)
        if text.contains("THREADS_ACCESS_TOKEN이 없습니다") { return "Threads 설정 없음 · 카드 이미지 제작은 가능" }
        if text.contains("401") || text.contains("OAuthException") || text.contains("토큰이 만료") {
            return "Threads 인증 만료 · 계정 연결을 다시 확인해야 해요"
        }
        if text.contains("Threads API 연결 실패") || text.contains("nodename nor servname") || text.contains("timed out") {
            return "Threads 연결 실패 · 인터넷 연결 후 다시 조회하세요"
        }
        if text.contains("Permission denied") || text.contains("Operation not permitted") {
            return "카드·영상 파일 접근이 막혔어요 · 접근 허용을 확인하세요"
        }
        if text.contains("No module named") { return "필요한 실행 모듈이 없어요 · 실행 기록을 확인하세요" }
        if text.contains("can't open file") || text.contains("No such file or directory") {
            return "실행 파일을 찾지 못했어요 · 실행 기록을 확인하세요"
        }
        let lines = text.split(whereSeparator: \.isNewline).map(String.init)
        let lastLine = lines.last(where: {
            !$0.trimmingCharacters(in: .whitespaces).hasPrefix("File \"") && !$0.hasPrefix("Traceback")
        }) ?? "완료 결과가 없어요 · 실행 기록을 확인하세요"
        return String(lastLine.prefix(110))
    }

    private static func hasUsableDraftText(_ text: String) -> Bool {
        let normalized = text.replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalized.isEmpty else { return false }
        let placeholders = [
            "원문 텍스트가 없어 문안을 만들 수 없습니다",
            "원문 분량 부족 — 이 장은 제작 전 재구성 필요",
            "원문 분량 부족 — 결론 확인 필요"
        ]
        return !placeholders.contains(where: normalized.contains)
    }

    private static func sanitized(_ output: String) -> String {
        var text = output
        for (key, value) in ProcessInfo.processInfo.environment where
            !value.isEmpty && value.count > 8 &&
            (key.contains("TOKEN") || key.contains("SECRET") || key.contains("API_KEY")) {
            text = text.replacingOccurrences(of: value, with: "[숨김]")
        }
        for pattern in [#"(?i)bearer\s+[^\s\"']+"#,
                        #"(?i)(?:access_token|api_key|client_secret|refresh_token)[\"']?\s*[:=]\s*[\"']?[^\s\"'&,}]+"#,
                        #"(?i)https?://[^\s\"'<>?]+\?[^\s\"'<>]+"#] {
            text = text.replacingOccurrences(of: pattern, with: "[인증정보 숨김]", options: .regularExpression)
        }
        return text
    }

    private func writeLog(arguments: [String], status: Int32, output: String) {
        let text = "시나모롤 콘텐츠 위젯\n시간: \(ISO8601DateFormatter().string(from: Date()))\n" +
            "Python: \(pythonURL?.path ?? "없음")\n프로젝트: \(projectRoot.path)\n" +
            "명령: \(arguments.joined(separator: " "))\n종료 코드: \(status)\n\n" + Self.sanitized(output)
        do {
            try FileManager.default.createDirectory(at: logURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            try text.write(to: logURL, atomically: true, encoding: .utf8)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: logURL.path)
        } catch {
            // Diagnostics must not turn a successful media render into failure.
            NSLog("콘텐츠 위젯 실행 기록 저장 실패")
        }
    }

    private func open(_ url: URL?) {
        guard let url, FileManager.default.fileExists(atPath: url.path) else {
            setStatus("열 파일이 없어요 · 폴더에서 결과를 확인하세요", error: true)
            return
        }
        if !NSWorkspace.shared.open(url) { setStatus("파일을 열지 못했어요 · 연결 앱을 확인하세요", error: true) }
    }

    @objc private func openQueue() { if hasProjectAccess { open(queueURL) } }

    @objc private func openLatestVideo() { open(readyRenders.first?.videoURL) }

    @objc private func openLatestProof() { open(readyRenders.first?.proofURL) }

    @objc private func openLog() { open(logURL) }

    @objc private func statusAction() {
        hasProjectAccess ? openLog() : connectProjectFolder()
    }

    private func isProjectFolder(_ url: URL) -> Bool {
        url.resolvingSymlinksInPath().standardizedFileURL.path.decomposedStringWithCanonicalMapping ==
            projectRoot.resolvingSymlinksInPath().standardizedFileURL.path.decomposedStringWithCanonicalMapping
    }

    // The system file picker grants access only after explicit folder selection.
    // Never fall back to authorizing Documents or another broader directory.
    @objc private func connectProjectFolder() {
        guard !isRunningPipeline else { return }
        let picker = NSOpenPanel()
        picker.title = "카드·영상 저장 위치 확인"
        picker.message = "이 프로그램의 카드·영상이 저장된 ‘바이브코딩 릴스’ 폴더만 읽고 저장합니다 · 다른 폴더와 계정 권한은 변경하지 않음"
        picker.prompt = "이 위치 허용"
        picker.directoryURL = projectRoot
        picker.canChooseDirectories = true
        picker.canChooseFiles = false
        picker.allowsMultipleSelection = false
        guard picker.runModal() == .OK, let folder = picker.url else { return }
        guard isProjectFolder(folder) else {
            setStatus("카드·영상이 저장된 ‘바이브코딩 릴스’ 폴더만 선택하세요", error: true)
            return
        }
        projectAccessURL?.stopAccessingSecurityScopedResource()
        projectAccessURL = folder
        _ = folder.startAccessingSecurityScopedResource()
        do {
            let bookmark = try folder.bookmarkData(options: [.withSecurityScope],
                                                   includingResourceValuesForKeys: nil, relativeTo: nil)
            UserDefaults.standard.set(bookmark, forKey: "projectFolderBookmark")
        } catch {
            // A temporary grant can still work even if a persistent bookmark is unavailable.
            writeLog(arguments: ["project-folder-bookmark"], status: 1, output: error.localizedDescription)
        }
        refreshLocalData()
        lastStatus = nil
        checkConfiguration()
    }

    private func restoreProjectAccess() {
        guard let bookmark = UserDefaults.standard.data(forKey: "projectFolderBookmark") else { return }
        var stale = false
        guard let folder = try? URL(resolvingBookmarkData: bookmark, options: [.withSecurityScope],
                                    relativeTo: nil, bookmarkDataIsStale: &stale), isProjectFolder(folder) else { return }
        projectAccessURL = folder
        _ = folder.startAccessingSecurityScopedResource()
        if stale, let renewed = try? folder.bookmarkData(options: [.withSecurityScope],
                                                        includingResourceValuesForKeys: nil, relativeTo: nil) {
            UserDefaults.standard.set(renewed, forKey: "projectFolderBookmark")
        }
    }

    @objc private func toggleExpanded() {
        isExpanded ? showCompact() : showExpanded()
    }

    @objc private func collapseWidget() { showCompact() }
}

private func resolveProjectRoot() -> URL {
    let environment = ProcessInfo.processInfo.environment
    var candidates: [URL] = []
    if let path = environment["VIBE_CONTENT_ROOT"] { candidates.append(URL(fileURLWithPath: path, isDirectory: true)) }
    if let path = Bundle.main.object(forInfoDictionaryKey: "ContentProjectRoot") as? String {
        candidates.append(URL(fileURLWithPath: path, isDirectory: true))
    }
    var ancestor = Bundle.main.bundleURL.deletingLastPathComponent()
    for _ in 0..<8 {
        candidates.append(ancestor)
        let parent = ancestor.deletingLastPathComponent()
        if parent.path == ancestor.path { break }
        ancestor = parent
    }
    candidates.append(FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Documents/Project/돈 자동화/바이브코딩 릴스", isDirectory: true))
    for candidate in candidates {
        let root = candidate.standardizedFileURL
        if FileManager.default.fileExists(atPath: root.appendingPathComponent("automation/meta-threads/run_daily.py").path),
           FileManager.default.fileExists(atPath: root.appendingPathComponent("automation/meta-threads/fetch/fetch_posts.py").path) {
            return root
        }
    }
    return candidates.first?.standardizedFileURL ?? Bundle.main.bundleURL
}

@main
private enum CinnamorollWidgetApp {
    static func main() {
        let controller = CinnamorollWidgetController(projectRoot: resolveProjectRoot())
        if CommandLine.arguments.contains("--check-render") || CommandLine.arguments.contains("--check-runtime") ||
            CommandLine.arguments.contains("--self-test") {
            let report = CommandLine.arguments.contains("--self-test") ? controller.selfTest() :
                CommandLine.arguments.contains("--check-runtime") ? controller.runtimeCheck() : controller.localRenderCheck()
            if let data = try? JSONSerialization.data(withJSONObject: report, options: [.sortedKeys]),
               let output = String(data: data, encoding: .utf8) { print(output) }
            if report["passed"] as? Bool == false { exit(1) }
            return
        }
        if let index = CommandLine.arguments.firstIndex(of: "--preview"), index + 1 < CommandLine.arguments.count {
            _ = NSApplication.shared
            do {
                let report = try controller.renderPreview(to: URL(fileURLWithPath: CommandLine.arguments[index + 1]),
                    errorState: CommandLine.arguments.contains("--preview-error"))
                let data = try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys])
                print(String(data: data, encoding: .utf8)!)
            } catch {
                fputs("위젯 미리보기 실패: \(error)\n", stderr)
                exit(1)
            }
            return
        }
        let app = NSApplication.shared
        app.delegate = controller
        app.run()
    }
}
