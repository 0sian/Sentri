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
        activeSlot.rope.show(lx, ly)
        var c = activeSlot.callout
        c.title = title || ""; c.body = body || ""; c.target = Qt.point(lx, ly); c.place()
        showTimer.restart()
        if (ttl > 0) { ttlTimer.interval = ttl * 1000; ttlTimer.restart() } else ttlTimer.stop()
    }
    function hideSlot(sl) { sl.callout.shown = false; sl.rope.hide() }
    function clearRope() {
        showTimer.stop(); ttlTimer.stop()
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
    readonly property real lid: blinking ? 0.06 : baseLid
    function setState(name) {
        if (name === "wake") { eyeState = "idle"; doubleBlink.restart(); name = "idle" }
        else if (["idle", "thinking", "talking", "working", "waiting", "error", "sleep"].indexOf(name) < 0) return
        else eyeState = name
        gazeStep = 0
        dizzy = 0
        if (eyeState === "error") dizzyTimer.restart(); else dizzyTimer.stop()
        if (eyeState === "idle") sleepTimer.restart(); else sleepTimer.stop()
        driveGaze()
    }
    property int gazeStep: 0
    // one gaze move per tick, pattern per state
    function driveGaze() {
        var n = gazeStep++
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
                }
                Text { visible: root.expanded; anchors.centerIn: parent; anchors.verticalCenterOffset: 22
                       text: "ask me where something is"; color: "#2b2400"; font.pixelSize: 15 }
                MouseArea { anchors.fill: parent; onClicked: { if (root.rope && root.rope.active) root.clearRope(); else root.expanded = !root.expanded } }
            }
        }
    }
}
