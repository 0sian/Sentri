import QtQuick

// The notch's eyes. All behaviour lives in Main.qml (root); this just draws them, so every
// per-screen notch shows the same thing. Brows/cheeks are notch-yellow covers over a white eye, so
// they read as the eye being cut off.
Row {
    id: eyes
    property real lid: 1            // 1 open, ~0.06 shut; >1 wide
    property real gazeX: 0          // -1..1
    property real gazeY: 0
    property real pupil: 1          // pupil scale
    property real topL: 0           // brow cover, fraction of eye height, per eye
    property real topR: 0
    property real angL: 0           // brow angle in degrees (clockwise +)
    property real angR: 0
    property real bot: 0            // cheek cover (happy squint)
    property bool shake: false      // scared / laughing tremble
    spacing: 22

    property real jx: 0
    SequentialAnimation on jx {
        running: eyes.shake; loops: Animation.Infinite
        NumberAnimation { to: 1.2; duration: 45 }
        NumberAnimation { to: -1.2; duration: 45 }
        onRunningChanged: if (!running) eyes.jx = 0
    }
    transform: Translate { x: eyes.jx }

    Repeater {
        model: 2
        Rectangle {
            id: eye
            property int idx: index
            width: 12; height: 20; radius: 6; color: "white"
            border.color: "#2b2400"; border.width: 1.5
            transform: Scale { origin.x: 6; origin.y: 10; yScale: eyes.lid
                               Behavior on yScale { NumberAnimation { duration: 90; easing.type: Easing.OutQuad } } }
            clip: true
            Rectangle {   // pupil
                width: 7 * eyes.pupil; height: width; radius: width / 2; color: "#2b2400"
                x: 6 - width / 2 + eyes.gazeX * 2.2
                y: 10 - height / 2 + eyes.gazeY * 5.5
                Behavior on x { NumberAnimation { duration: 120; easing.type: Easing.OutQuad } }
                Behavior on y { NumberAnimation { duration: 120; easing.type: Easing.OutQuad } }
                Behavior on width { NumberAnimation { duration: 120 } }
            }
            Rectangle {   // brow cover
                property real amt: eye.idx === 0 ? eyes.topL : eyes.topR
                width: 30; height: 16; x: -9
                y: -16 + amt * 20
                color: "#FFD60A"
                rotation: eye.idx === 0 ? eyes.angL : eyes.angR
                visible: amt > 0.01
                Behavior on y { NumberAnimation { duration: 140; easing.type: Easing.OutQuad } }
                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1.6; color: "#2b2400" }
            }
            Rectangle {   // cheek cover: a rounded bump from below makes a happy ^ eye
                width: 22; height: 18; radius: 9; x: -5
                y: 20 - eyes.bot * 20
                color: "#FFD60A"
                visible: eyes.bot > 0.01
                Behavior on y { NumberAnimation { duration: 140; easing.type: Easing.OutQuad } }
            }
        }
    }
}
