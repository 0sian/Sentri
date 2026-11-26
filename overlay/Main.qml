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

    property var conn: Connections {
        target: bridge
        function onCommand(cmd, args) {
            if (cmd === "expand") root.expanded = true
            else if (cmd === "collapse") root.expanded = false
            else if (cmd === "point") root.pointTo(args.x, args.y, args.title, args.text, args.ttl || 0)
            else if (cmd === "clear") root.clearRope()
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
            width: root.expanded ? 360 : 190
            height: root.expanded ? 130 : 46
            Behavior on width { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
            Behavior on height { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
            onHeightChanged: root.notchHeight = height
            LS.Window.scope: "sentri-notch"
            LS.Window.screen: modelData
            LS.Window.exclusionZone: -1
            LS.Window.layer: LS.Window.LayerOverlay
            LS.Window.anchors: LS.Window.AnchorTop
            LS.Window.keyboardInteractivity: LS.Window.KeyboardInteractivityNone

            Rectangle {   // flat yellow body, flush with the top edge
                anchors.fill: parent
                color: "#FFD60A"
                radius: 23
                Rectangle { x: 0; y: 0; width: parent.width; height: parent.radius; color: parent.color }
                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 14; spacing: 22
                    Repeater { model: 2
                        Rectangle { width: 12; height: 20; radius: 6; color: "white"
                                    border.color: "#2b2400"; border.width: 1.5 } }
                }
                Text { visible: root.expanded; anchors.centerIn: parent; anchors.verticalCenterOffset: 22
                       text: "ask me where something is"; color: "#2b2400"; font.pixelSize: 15 }
                MouseArea { anchors.fill: parent; onClicked: { if (root.rope && root.rope.active) root.clearRope(); else root.expanded = !root.expanded } }
            }
        }
    }
}
