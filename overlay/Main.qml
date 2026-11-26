import QtQuick
import QtQuick.Window
import QtQml
import org.kde.layershell 1.0 as LS

QtObject {
    id: root
    property bool debug: true
    property bool expanded: false

    property var rope: null     // the Rope on the primary screen
    function pointTo(x, y) { if (rope) rope.show(x, y) }
    function clearRope() { if (rope) rope.hide() }

    property var conn: Connections {
        target: bridge
        function onCommand(cmd, args) {
            if (cmd === "expand") root.expanded = true
            else if (cmd === "collapse") root.expanded = false
            else if (cmd === "point") root.pointTo(args.x, args.y)
            else if (cmd === "clear") root.clearRope()
            else if (cmd === "debug") root.debug = !!args.on
            else if (cmd === "quit") bridge.quit()
        }
    }

    // Fullscreen click-through layer, one per screen.
    property var overlays: Instantiator {
        model: Qt.application.screens
        delegate: Window {
            required property var modelData
            screen: modelData
            visible: true
            color: "transparent"
            flags: Qt.FramelessWindowHint | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
            LS.Window.scope: "sentri-overlay"
            LS.Window.layer: LS.Window.LayerOverlay
            LS.Window.anchors: LS.Window.AnchorTop | LS.Window.AnchorBottom | LS.Window.AnchorLeft | LS.Window.AnchorRight
            LS.Window.exclusionZone: -1
            LS.Window.keyboardInteractivity: LS.Window.KeyboardInteractivityNone

            Rope {
                anchors.fill: parent
                visible: modelData === Qt.application.screens[0]
                anchor: Qt.point(width / 2, notchWin.height - 8)
                Component.onCompleted: if (visible) root.rope = this
            }
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

    // Notch: small interactive surface anchored top-centre on the primary screen.
    property var notch: Window {
        id: notchWin
        screen: Qt.application.screens[0]
        visible: true
        color: "transparent"
        flags: Qt.FramelessWindowHint
        width: root.expanded ? 360 : 190
        height: root.expanded ? 130 : 46
        Behavior on width { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
        Behavior on height { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
        LS.Window.scope: "sentri-notch"
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
            MouseArea { anchors.fill: parent; onClicked: root.expanded = !root.expanded }
        }
    }
}
