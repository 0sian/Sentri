import QtQuick
import QtQuick.Window
import QtQml
import org.kde.layershell 1.0 as LS

QtObject {
    id: root
    property bool debug: false
    property bool expanded: false

    // One Rope + Callout per screen (they register here by screen name). A guide lives on the
    // screen that contains its target, and the notch moves there too.
    property var slots: ({})
    property real notchHeight: 46
    property var activeScreen: screenList[0]
    property var activeSlot: null
    property var rope: activeSlot ? activeSlot.rope : null    // the live rope, for the notch tap
    function screenAt(x, y) {
        var best = null, bd = 1e18
        for (var i = 0; i < screenList.length; i++) {
            var s = screenList[i]
            var dx = Math.max(s.geometry.x - x, 0, x - (s.geometry.x + s.geometry.width)), dy = Math.max(s.geometry.y - y, 0, y - (s.geometry.y + s.geometry.height))
            var d = dx * dx + dy * dy
            if (d < bd) { bd = d; best = s }
        }
        return best
    }
    // x, y are compositor layout px (logical, global); the screen containing them gets the guide
    function pointTo(x, y, title, body, ttl) {
        var s = screenAt(x, y)
        if (!s) return
        if (eyeState === "sleep") setState("idle")
        if (activeSlot && activeSlot !== slots[s.name]) hideSlot(activeSlot)
        activeScreen = s
        activeSlot = slots[s.name]
        if (!activeSlot) return
        var lx = x - s.geometry.x, ly = y - s.geometry.y
        lookX = x; lookY = y; lookActive = true; driveGaze()
        activeSlot.rope.show(lx, ly)
        var c = activeSlot.callout
        c.title = title || ""; c.body = body || ""; c.target = Qt.point(lx, ly); c.place()
        showTimer.restart()
        if (ttl > 0) { ttlTimer.interval = ttl * 1000; ttlTimer.restart() } else ttlTimer.stop()
    }
    function hideSlot(sl) { sl.callout.shown = false; sl.rope.hide() }
    function clearRope() {
        showTimer.stop(); ttlTimer.stop()
        lookActive = false; driveGaze()
        if (activeSlot) hideSlot(activeSlot)
    }
    property var showTimer: Timer { interval: 650
        onTriggered: if (root.activeSlot && root.activeSlot.callout.body !== "") root.activeSlot.callout.shown = true }
    property var ttlTimer: Timer { onTriggered: root.clearRope() }

    // ---- Eyes: state from the daemon (state command), gaze from state or (later) the cursor ----
    property string eyeState: "idle"
    property real gazeX: 0
    property real gazeY: 0
    property bool blinking: false
    property real dizzy: 0
    readonly property real baseLid: ({ idle: 1, thinking: 1, talking: 1, working: 0.62, waiting: 1.12,
                                       error: 0.6, sleep: 0.06 })[eyeState] || 1
    readonly property real lid: blinking ? 0.06 : baseLid * moodLid
    function setState(name) {
        if (name === "wake") { eyeState = "idle"; doubleBlink.restart(); name = "idle" }
        else if (["idle", "thinking", "talking", "working", "waiting", "error", "sleep"].indexOf(name) < 0) return
        else eyeState = name
        gazeStep = 0
        dizzy = 0
        if (eyeState === "idle") { if (mood !== "neutral") moodTimer.restart() }
        else if (eyeState !== "talking") { mood = "neutral"; moodTimer.stop() }
        if (eyeState === "error") dizzyTimer.restart(); else dizzyTimer.stop()
        if (eyeState === "idle") sleepTimer.restart(); else sleepTimer.stop()
        driveGaze()
    }
    // ---- Moods (chat_mood): an expression over the talking/idle eyes, gone a few seconds after the reply ----
    property string mood: "neutral"
    readonly property var looks: ({
        neutral: {}, attentive: { lid: 1.1 }, surprised: { lid: 1.18, pupil: 0.6 }, excited: { lid: 1.12, pupil: 1.2 },
        happy: { bot: 0.4, lid: 1.12, gx: 0, gy: -0.4 }, laughing: { bot: 0.48, lid: 1.12, shake: true, gx: 0, gy: -0.4 }, angry: { top: 0.42, ang: 20 },
        sad: { top: 0.36, ang: -18, lid: 0.95, gx: 0, gy: 0.7 }, scared: { lid: 1.15, pupil: 0.55, shake: true },
        suspicious: { top: 0.42, bot: 0.15, gx: 0.9, gy: 0 }, confused: { lid: 1.08, topR: 0.34, angR: -14 },
        curious: { lid: 1.1, pupil: 1.1, gx: 0.7, gy: -0.6 }, proud: { top: 0.18, bot: 0.34, lid: 1.05, gy: -0.3, gx: 0 },
        shy: { lid: 0.88, pupil: 0.9, gx: -0.7, gy: 0.8 }, unimpressed: { top: 0.5, gx: 0, gy: 0 } })
    readonly property bool moodOn: mood !== "neutral" && (eyeState === "talking" || eyeState === "idle")
    readonly property var look: moodOn ? (looks[mood] || {}) : ({})
    function lk(k, d) { return look[k] !== undefined ? look[k] : d }
    readonly property real moodLid: lk("lid", 1)
    property var moodTimer: Timer { interval: 7000; onTriggered: { root.mood = "neutral"; root.driveGaze() } }
    function setMood(name) {
        if (!looks.hasOwnProperty(name)) return
        mood = name
        if (eyeState === "idle") moodTimer.restart(); else moodTimer.stop()
        driveGaze()
    }

    // ---- Where the eyes aim: a live guide target > a mood's gaze > the cursor > the state's own pattern ----
    property bool lookActive: false
    property real lookX: 0
    property real lookY: 0
    property bool cursorFollow: false
    property real curX: 0
    property real curY: 0
    function aim(x, y) {      // x, y in global layout px
        var s = activeScreen
        var nx = s.geometry.x + s.geometry.width / 2, ny = s.geometry.y + 24
        var dx = x - nx, dy = y - ny, m = Math.sqrt(dx * dx + dy * dy)
        if (m < 1) { gazeX = 0; gazeY = 0; return }
        var k = Math.min(1, m / 450)
        gazeX = dx / m * k; gazeY = dy / m * k
    }
    property var cursorStill: Timer { interval: 5000; onTriggered: { root.cursorFollow = false; root.driveGaze() } }
    function cursorAt(x, y) {
        curX = x; curY = y
        if (eyeState === "sleep") setState("idle")
        if (eyeState === "idle") sleepTimer.restart()
        cursorFollow = true; cursorStill.restart()
        if (!lookActive && (eyeState === "idle" || eyeState === "talking") && !(moodOn && look.gx !== undefined)) { aim(x, y) }
    }

    property int gazeStep: 0
    // one gaze move per tick, pattern per state
    function driveGaze() {
        var n = gazeStep++
        if (lookActive && eyeState !== "error" && eyeState !== "sleep") { aim(lookX, lookY); gazeTimer.stop(); return }
        if (moodOn && look.gx !== undefined) { gazeX = look.gx; gazeY = look.gy; gazeTimer.stop(); return }
        if (cursorFollow && (eyeState === "idle" || eyeState === "talking")) { aim(curX, curY); gazeTimer.stop(); return }
        switch (eyeState) {
        case "thinking": { var seq = [[-0.9, -1], [0.9, -1], [0.1, -1], [-0.7, -0.6], [0.8, -0.8]]
            var g = seq[Math.floor(Math.random() * seq.length)]; gazeX = g[0]; gazeY = g[1]
            gazeTimer.interval = 450 + Math.random() * 500; gazeTimer.restart(); break }
        case "working": gazeX = (n % 2) ? 0.9 : -0.9; gazeY = 0.55; gazeTimer.interval = 800; gazeTimer.restart(); break
        case "waiting": gazeX = 0; gazeY = (n % 2) ? 0.9 : -0.2; gazeTimer.interval = 900; gazeTimer.restart(); break
        case "talking": gazeX = 0; gazeY = 0.1; gazeTimer.stop(); break
        case "error": gazeTimer.stop(); break      // dizzyTimer drives it
        case "sleep": gazeX = 0; gazeY = 0.6; gazeTimer.stop(); break
        default:       // idle: mostly forward, a glance now and then
            if (n % 2 === 0) { gazeX = 0; gazeY = 0 }
            else { gazeX = (Math.random() < 0.5 ? -1 : 1) * (0.5 + Math.random() * 0.5); gazeY = (Math.random() - 0.5) * 0.8 }
            gazeTimer.interval = n % 2 ? 900 + Math.random() * 600 : 3000 + Math.random() * 5000
            gazeTimer.restart()
        }
    }
    property var gazeTimer: Timer { onTriggered: root.driveGaze() }
    property var blinkTimer: Timer {
        running: root.eyeState !== "sleep"; repeat: true; interval: 3000
        onTriggered: { root.blinking = true; blinkOpen.start(); interval = 2200 + Math.random() * 4300 }
    }
    property var blinkOpen: Timer { interval: 130; onTriggered: root.blinking = false }
    property var doubleBlink: Timer { interval: 220; repeat: true; property int n: 0
        onRunningChanged: if (running) n = 0
        onTriggered: { n++; root.blinking = (n % 2 === 1); if (n >= 4) { root.blinking = false; stop() } } }
    property var dizzyTimer: Timer { interval: 60; repeat: true; property int ticks: 0
        onRunningChanged: if (running) ticks = 0
        onTriggered: { ticks++; var a = ticks * 0.55; root.gazeX = Math.cos(a) * 0.9; root.gazeY = Math.sin(a) * 0.9
                       if (ticks > 24) { stop(); root.setState("idle") } } }
    property var sleepTimer: Timer { interval: 180000; onTriggered: root.setState("sleep") }
    Component.onCompleted: driveGaze()

    property var conn: Connections {
        target: bridge
        function onCommand(cmd, args) {
            if (cmd === "expand") root.expanded = true
            else if (cmd === "collapse") root.expanded = false
            else if (cmd === "point") root.pointTo(args.x, args.y, args.title, args.text, args.ttl || 0)
            else if (cmd === "clear") root.clearRope()
            else if (cmd === "state") root.setState(String(args.name))
            else if (cmd === "mood") root.setMood(String(args.name))
            else if (cmd === "cursor") root.cursorAt(Number(args.x), Number(args.y))
            else if (cmd === "debug") root.debug = !!args.on
            else if (cmd === "quit") bridge.quit()
        }
    }

    // Fullscreen click-through layer, one per screen.
    property var overlays: Instantiator {
        model: screenList
        delegate: Window {
            required property var modelData
            visible: false      // shown from onCompleted, once the screen is set: layer-shell picks its output at map time
            color: "transparent"
            flags: Qt.FramelessWindowHint | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
            LS.Window.scope: "sentri-overlay"
            LS.Window.screen: modelData
            LS.Window.layer: LS.Window.LayerOverlay
            LS.Window.anchors: LS.Window.AnchorTop | LS.Window.AnchorBottom | LS.Window.AnchorLeft | LS.Window.AnchorRight
            LS.Window.exclusionZone: -1
            LS.Window.keyboardInteractivity: LS.Window.KeyboardInteractivityNone

            Rope {
                id: ropeItem
                anchors.fill: parent
                anchor: Qt.point(width / 2, root.notchHeight - 8)
            }
            Callout {
                id: calloutItem
                visible: opacity > 0
                anchor: Qt.point(parent.width / 2, root.notchHeight - 8)
                keepOut: Qt.rect(parent.width / 2 - 260, 0, 520, root.notchHeight + 14)
            }
            Component.onCompleted: { root.slots[modelData.name] = { rope: ropeItem, callout: calloutItem }; visible = true }
            Component.onDestruction: delete root.slots[modelData.name]
            Rectangle {   // debug frame: proves the surface covers the screen
                anchors.fill: parent
                visible: root.debug
                color: "transparent"
                border.color: "#80ff3030"; border.width: 3
                Text { x: 12; y: 60; color: "#ff3030"; font.pixelSize: 14
                       text: modelData.name + "  " + width + "x" + height + "  dpr " + modelData.devicePixelRatio }
            }
        }
    }

    // Notch: small interactive surface anchored top-centre. One per screen (layer-shell fixes the
    // output when a surface is mapped), shown only on the active guide's screen.
    property var notches: Instantiator {
        model: screenList
        delegate: Window {
            id: notchWin
            required property var modelData
            visible: modelData === root.activeScreen
            color: "transparent"
            flags: Qt.FramelessWindowHint
            // Fixed size: resizing a layer-shell window every frame shows stale buffers. The shape
            // animates inside it and the input region is clipped to the shape.
            width: 360
            height: 130
            function updateMask() { bridge.setMask(notchWin, shape.x, 0, shape.width, shape.height) }
            onVisibleChanged: if (visible) Qt.callLater(updateMask)
            LS.Window.scope: "sentri-notch"
            LS.Window.screen: modelData
            LS.Window.exclusionZone: -1
            LS.Window.layer: LS.Window.LayerOverlay
            LS.Window.anchors: LS.Window.AnchorTop
            LS.Window.keyboardInteractivity: LS.Window.KeyboardInteractivityNone

            Rectangle {   // flat yellow body, flush with the top edge
                id: shape
                anchors.horizontalCenter: parent.horizontalCenter
                y: 0
                width: root.expanded ? 360 : 190
                height: root.expanded ? 130 : 46
                Behavior on width { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                Behavior on height { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                onWidthChanged: notchWin.updateMask()
                onHeightChanged: { root.notchHeight = height; notchWin.updateMask() }
                color: "#FFD60A"
                radius: 23
                Rectangle { x: 0; y: 0; width: parent.width; height: parent.radius; color: parent.color }
                Eyes {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 14
                    lid: root.lid; gazeX: root.gazeX; gazeY: root.gazeY
                    pupil: root.lk("pupil", 1); bot: root.lk("bot", 0); shake: root.lk("shake", false)
                    topL: root.lk("top", 0); topR: root.lk("topR", root.lk("top", 0))
                    angL: root.lk("ang", 0); angR: root.lk("angR", -root.lk("ang", 0))
                }
                Text { visible: root.expanded; anchors.centerIn: parent; anchors.verticalCenterOffset: 22
                       text: "ask me where something is"; color: "#2b2400"; font.pixelSize: 15 }
                MouseArea { anchors.fill: parent; onClicked: { if (root.rope && root.rope.active) root.clearRope(); else root.expanded = !root.expanded } }
            }
        }
    }
}
