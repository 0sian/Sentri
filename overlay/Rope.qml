import QtQuick
import QtQuick.Shapes

// Verlet rope from `anchor` to `target`. The free end is a damped spring chasing the target, so it
// overshoots and wobbles on arrival; the body droops under gravity and sways a little.
Item {
    id: rope
    property point anchor: Qt.point(width / 2, 0)
    property point target: Qt.point(width / 2, height / 2)
    property bool active: false
    property color ropeColor: "#FFD60A"
    property color edgeColor: "#2b2400"
    readonly property int n: 36
    property real slack: 1.10       // rest length vs straight distance: how much it droops
    property real gravity: 2400     // px/s^2
    property real sway: 260         // px/s^2 of sideways wind
    property real damping: 0.992    // per step
    property real springK: 110
    property real springC: 15       // zeta ~0.7: ~5% overshoot, rope body supplies the wobble
    property bool settled: false
    property int frames: 0

    property var px: []; property var py: []; property var ox: []; property var oy: []
    property real ex: 0; property real ey: 0; property real evx: 0; property real evy: 0
    property real t: 0
    property real acc: 0
    property real restLen: 1
    property real retract: 1       // 0..1, how far the rope has paid out
    property var pts: []

    function reset() {
        px = []; py = []; ox = []; oy = []
        for (var i = 0; i < n; i++) { px.push(anchor.x); py.push(anchor.y); ox.push(anchor.x); oy.push(anchor.y) }
        ex = anchor.x; ey = anchor.y; evx = 0; evy = 0; restLen = 1; retract = 0; settled = false
    }
    function show(x, y) { target = Qt.point(x, y); if (!active) { reset(); active = true } settled = false }
    function hide() { active = false }
    Component.onCompleted: reset()

    function step(dt) {
        t += dt
        // free end: damped spring toward target
        evx += ((target.x - ex) * springK - evx * springC) * dt
        evy += ((target.y - ey) * springK - evy * springC) * dt
        ex += evx * dt; ey += evy * dt
        var d = Math.hypot(ex - anchor.x, ey - anchor.y)
        var want = Math.max(d * slack + 30, 60) / (n - 1)
        restLen = want > restLen ? want : restLen + (want - restLen) * Math.min(1, dt * 8)  // pay out instantly, reel in smoothly
        px[0] = anchor.x; py[0] = anchor.y
        px[n - 1] = ex; py[n - 1] = ey
        for (var i = 1; i < n - 1; i++) {
            var vx = (px[i] - ox[i]) * damping, vy = (py[i] - oy[i]) * damping
            ox[i] = px[i]; oy[i] = py[i]
            var w = Math.sin(t * 1.7 + i * 0.35) * sway * (0.4 + 0.6 * i / n)
            px[i] += vx + w * dt * dt
            py[i] += vy + gravity * dt * dt
        }
        for (var it = 0; it < 14; it++) {
            for (var j = 0; j < n - 1; j++) {
                var dx = px[j + 1] - px[j], dy = py[j + 1] - py[j]
                var dd = Math.hypot(dx, dy) || 0.0001
                var diff = (dd - restLen) / dd * 0.5
                var fa = j === 0 ? 0 : 1, fb = j + 1 === n - 1 ? 0 : 1
                var tot = fa + fb
                if (tot === 0) continue
                var k = (dd - restLen) / dd
                px[j] += dx * k * fa / tot; py[j] += dy * k * fa / tot
                px[j + 1] -= dx * k * fb / tot; py[j + 1] -= dy * k * fb / tot
            }
        }
        var sp = Math.hypot(evx, evy)
        settled = sp < 1.5 && Math.hypot(target.x - ex, target.y - ey) < 1
    }

    function build() {   // Catmull-Rom subdivision so the polyline reads as a smooth curve
        var out = [], sub = 4
        for (var i = 0; i < n - 1; i++) {
            var i0 = Math.max(i - 1, 0), i3 = Math.min(i + 2, n - 1)
            for (var s = 0; s < sub; s++) {
                var u = s / sub, u2 = u * u, u3 = u2 * u
                var x = 0.5 * ((2 * px[i]) + (-px[i0] + px[i + 1]) * u + (2 * px[i0] - 5 * px[i] + 4 * px[i + 1] - px[i3]) * u2 + (-px[i0] + 3 * px[i] - 3 * px[i + 1] + px[i3]) * u3)
                var y = 0.5 * ((2 * py[i]) + (-py[i0] + py[i + 1]) * u + (2 * py[i0] - 5 * py[i] + 4 * py[i + 1] - py[i3]) * u2 + (-py[i0] + 3 * py[i] - 3 * py[i + 1] + py[i3]) * u3)
                out.push(Qt.point(x, y))
            }
        }
        out.push(Qt.point(px[n - 1], py[n - 1]))
        return out
    }

    Timer { interval: 2000; running: rope.active; repeat: true
            onTriggered: { console.log("rope fps", rope.frames / 2); rope.frames = 0 } }
    FrameAnimation {
        running: rope.active
        onTriggered: {
            rope.acc += Math.min(frameTime, 0.05)
            while (rope.acc >= 1 / 120) { rope.step(1 / 120); rope.acc -= 1 / 120 }
            rope.pts = rope.build(); rope.frames++
        }
    }

    Shape {
        anchors.fill: parent
        visible: rope.active
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: rope.edgeColor; strokeWidth: 7; fillColor: "transparent"
            capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
            PathPolyline { path: rope.pts }
        }
        ShapePath {
            strokeColor: rope.ropeColor; strokeWidth: 4; fillColor: "transparent"
            capStyle: ShapePath.RoundCap; joinStyle: ShapePath.RoundJoin
            PathPolyline { path: rope.pts }
        }
    }
    Rectangle {   // marker ring at the free end
        visible: rope.active
        x: rope.ex - 11; y: rope.ey - 11; width: 22; height: 22; radius: 11
        color: "transparent"; border.color: rope.ropeColor; border.width: 3
        Rectangle { anchors.fill: parent; anchors.margins: -2; radius: width / 2; color: "transparent"; border.color: rope.edgeColor; border.width: 1.5; z: -1 }
        Rectangle { anchors.centerIn: parent; width: 6; height: 6; radius: 3; color: rope.ropeColor }
    }
}
