import QtQuick

// The notch's eyes. All behaviour lives in Main.qml (root); this just draws lid and gaze, so every
// per-screen notch shows the same thing.
Row {
    id: eyes
    property real lid: 1            // 1 open, ~0.06 shut; >1 wide
    property real gazeX: 0          // -1..1
    property real gazeY: 0
    property real tilt: 0           // degrees; sad/angry brows later
    spacing: 22
    Repeater {
        model: 2
        Rectangle {
            width: 12; height: 20; radius: 6; color: "white"
            border.color: "#2b2400"; border.width: 1.5
            transform: Scale { origin.x: 6; origin.y: 10; yScale: eyes.lid
                               Behavior on yScale { NumberAnimation { duration: 90; easing.type: Easing.OutQuad } } }
            clip: true
            Rectangle {   // pupil
                width: 7; height: 7; radius: 3.5; color: "#2b2400"
                x: 2.5 + eyes.gazeX * 2.2
                y: 6.5 + eyes.gazeY * 5.5
                Behavior on x { NumberAnimation { duration: 120; easing.type: Easing.OutQuad } }
                Behavior on y { NumberAnimation { duration: 120; easing.type: Easing.OutQuad } }
            }
        }
    }
}
