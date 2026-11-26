import QtQuick

// Instruction card. It sits beside the target, never on it, never off-screen, never under the notch.
// Candidate positions are tried in order of angle around the target, starting with the direction the
// rope arrives from (so the card lands beyond the target, clear of the rope), then rotating away.
Item {
    id: card
    property point target: Qt.point(0, 0)      // where the rope ends
    property point anchor: Qt.point(0, 0)      // where the rope starts (notch)
    property real targetRadius: 36             // keep-out radius around the target
    property rect keepOut: Qt.rect(0, 0, 0, 0) // extra rectangle to avoid (the notch)
    property string title: ""
    property string body: ""
    property bool shown: false
    property real margin: 24
    property real gap: 30
    property alias cardWidth: panel.width

    visible: opacity > 0
    opacity: shown ? 1 : 0
    scale: shown ? 1 : 0.94
    transformOrigin: Item.Center
    Behavior on opacity { NumberAnimation { duration: 160 } }
    Behavior on scale { NumberAnimation { duration: 220; easing.type: Easing.OutBack } }
    width: panel.width; height: panel.height

    function fits(x, y, w, h) {
        if (x < margin || y < margin || x + w > parent.width - margin || y + h > parent.height - margin) return false
        var k = keepOut
        if (k.width > 0 && x < k.x + k.width && x + w > k.x && y < k.y + k.height && y + h > k.y) return false
        return true
    }
    function clearOfTarget(x, y, w, h) {   // distance from target to the card rectangle
        var dx = Math.max(x - target.x, 0, target.x - (x + w)), dy = Math.max(y - target.y, 0, target.y - (y + h))
        return Math.hypot(dx, dy) >= targetRadius
    }
    function place() {
        var w = panel.width, h = panel.height
        var base = Math.atan2(target.y - anchor.y, target.x - anchor.x)
        var steps = [0, 45, -45, 90, -90, 135, -135, 180]
        for (var i = 0; i < steps.length; i++) {
            var a = base + steps[i] * Math.PI / 180
            var ux = Math.cos(a), uy = Math.sin(a)
            var d = gap + targetRadius * 0.5 + Math.abs(ux) * w / 2 + Math.abs(uy) * h / 2
            var x = target.x + ux * d - w / 2, y = target.y + uy * d - h / 2
            if (fits(x, y, w, h) && clearOfTarget(x, y, w, h)) { card.x = x; card.y = y; return }
        }
        // nothing fits cleanly (tiny screen, huge card): clamp the first choice into the screen
        var x0 = target.x + Math.cos(base) * (gap + w / 2) - w / 2, y0 = target.y + Math.sin(base) * (gap + h / 2) - h / 2
        card.x = Math.max(margin, Math.min(x0, parent.width - w - margin))
        card.y = Math.max(margin, Math.min(y0, parent.height - h - margin))
    }
    onTargetChanged: place()
    onBodyChanged: Qt.callLater(place)
    onTitleChanged: Qt.callLater(place)
    Component.onCompleted: place()
    Behavior on x { enabled: card.shown; NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
    Behavior on y { enabled: card.shown; NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }

    Rectangle {
        id: panel
        width: 360
        height: col.implicitHeight + 32
        radius: 18
        color: "#FFFBE6"
        border.color: "#FFD60A"; border.width: 3
        Rectangle {   // soft flat shadow
            z: -1; anchors.fill: parent; anchors.topMargin: 4; anchors.leftMargin: 2; anchors.rightMargin: -2; anchors.bottomMargin: -4
            radius: parent.radius; color: "#33000000"
        }
        Column {
            id: col
            x: 18; y: 16; width: parent.width - 36; spacing: 6
            Row {
                spacing: 7; visible: card.title !== ""
                Row { spacing: 3; anchors.verticalCenter: parent.verticalCenter
                    Repeater { model: 2; Rectangle { width: 6; height: 10; radius: 3; color: "white"; border.color: "#2b2400"; border.width: 1 } } }
                Text { text: card.title; color: "#2b2400"; font.pixelSize: 15; font.weight: Font.DemiBold; elide: Text.ElideRight; width: col.width - 30 }
            }
            Text { width: parent.width; text: card.body; color: "#2b2400"; font.pixelSize: 16; wrapMode: Text.Wrap; lineHeight: 1.15 }
        }
    }
}
