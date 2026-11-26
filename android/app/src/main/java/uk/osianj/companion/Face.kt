package uk.osianj.companion

import kotlin.math.PI
import kotlin.math.exp
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.sin

// The character's face, as plain Kotlin (no Compose types) so it can be unit-tested on the JVM.
//
// Design (the idea, not the code, is borrowed from the open-source Bloub avatar engine):
//  * every expression is a fixed target Pose;
//  * switching expression blends from the pose *at that instant* to the new target with an
//    exponential ease-out, so it never overshoots and never jumps;
//  * everything else (blink, gaze drift, hops) is a function of time, so a frame depends only on
//    the clock and the events that happened, never on how many frames were drawn.

enum class Expr {
    Neutral, Attentive, Surprised, Excited,
    Happy, Laughing, Angry, Sad,
    Scared, Suspicious, Confused, Curious,
    Proud, Shy, Unimpressed, Sleepy,
    Thinking, Alert,
}

/**
 * One eye. Sizes are fractions of the body scale; [tilt] is degrees clockwise; [arc] morphs the eye from
 * a filled capsule (0) into a "^" arc (1); [x] scales the spacing from the face centre; [y] is a vertical
 * offset in body scale.
 */
data class Eye(val w: Float, val h: Float, val tilt: Float, val arc: Float, val x: Float, val y: Float) {
    fun lerp(o: Eye, k: Float) = Eye(
        w + (o.w - w) * k, h + (o.h - h) * k, tilt + (o.tilt - tilt) * k,
        arc + (o.arc - arc) * k, x + (o.x - x) * k, y + (o.y - y) * k,
    )
}

data class Pose(
    val l: Eye, val r: Eye,
    val sx: Float, val sy: Float,   // body squash/stretch
    val puff: Float,                // cloud lobe size multiplier
    val gx: Float, val gy: Float,   // where the eyes rest when nothing is being looked at
    val gain: Float,                // how much idle gaze wander applies (0 = fixed stare)
    val blink: Float,               // 1 = blinks normally, 0 = never (eyes already closed / fixed)
    val smile: Float, val mouthO: Float,
    val shake: Float,               // tremble amount
    val bob: Float,                 // continuous happy hopping amount
    val dots: Float, val bang: Float, val zzz: Float,   // thought dots, "!", sleeping z's
) {
    fun lerp(o: Pose, k: Float): Pose {
        fun f(a: Float, b: Float) = a + (b - a) * k
        return Pose(
            l.lerp(o.l, k), r.lerp(o.r, k),
            f(sx, o.sx), f(sy, o.sy), f(puff, o.puff), f(gx, o.gx), f(gy, o.gy), f(gain, o.gain),
            f(blink, o.blink), f(smile, o.smile), f(mouthO, o.mouthO), f(shake, o.shake), f(bob, o.bob),
            f(dots, o.dots), f(bang, o.bang), f(zzz, o.zzz),
        )
    }
}

private fun e(w: Float, h: Float, tilt: Float = 0f, arc: Float = 0f, x: Float = 1f, y: Float = 0f) =
    Eye(w, h, tilt, arc, x, y)

private fun p(
    l: Eye, r: Eye = l,
    sx: Float = 1f, sy: Float = 1f, puff: Float = 1f,
    gx: Float = 0f, gy: Float = 0f, gain: Float = 1f, blink: Float = 1f,
    smile: Float = 0.25f, o: Float = 0f, shake: Float = 0f, bob: Float = 0f,
    dots: Float = 0f, bang: Float = 0f, zzz: Float = 0f,
) = Pose(l, r, sx, sy, puff, gx, gy, gain, blink, smile, o, shake, bob, dots, bang, zzz)

/** Eye rule: a clearly tilted eye must not be near-circular or the tilt is invisible (checked in tests). */
fun poseOf(x: Expr): Pose = when (x) {
    Expr.Neutral -> p(e(.085f, .20f, 10f))
    Expr.Attentive -> p(e(.075f, .235f), sy = 1.02f, gain = .5f)
    Expr.Surprised -> p(e(.11f, .15f), sx = 1.08f, sy = 1.08f, smile = 0f, o = 1f, gain = .3f, blink = .3f)
    Expr.Excited -> p(e(.105f, .235f, 12f, y = -.01f), sx = 1.04f, sy = 1.04f, puff = 1.06f, smile = .8f, bob = 1f)
    Expr.Happy -> p(e(.075f, .06f, arc = 1f, y = .005f), puff = 1.04f, smile = .75f, blink = 0f)
    Expr.Laughing -> p(
        e(.095f, .06f, -20f, 1f, y = .015f), e(.095f, .06f, 20f, 1f, y = .015f),
        puff = 1.07f, smile = .9f, shake = .6f, bob = 1f, blink = 0f,
    )
    Expr.Angry -> p(
        e(.09f, .14f, -26f, y = .012f), e(.09f, .14f, 26f, y = .012f),
        sx = 1.02f, sy = .96f, smile = -.4f, gain = .4f, blink = .5f,
    )
    Expr.Sad -> p(
        e(.085f, .18f, 24f, x = .95f, y = .028f), e(.085f, .18f, -24f, x = .95f, y = .028f),
        sx = .98f, sy = .93f, gy = .3f, gain = .5f, smile = -.5f,
    )
    Expr.Scared -> p(e(.10f, .235f, x = 1.12f, y = -.005f), sx = .94f, sy = .95f, smile = -.2f, o = .5f, shake = 1f, gain = .6f, blink = .4f)
    Expr.Suspicious -> p(e(.10f, .05f, -4f, y = .01f), e(.075f, .075f), gx = .5f, gain = .3f, smile = 0f)
    Expr.Confused -> p(e(.07f, .17f, -16f), e(.085f, .12f, 22f, y = -.01f), smile = -.1f)
    Expr.Curious -> p(e(.07f, .19f, 4f), e(.095f, .25f, 12f, y = -.02f), sy = 1.02f, gx = .35f, gy = -.2f, gain = .4f)
    Expr.Proud -> p(e(.095f, .035f, y = -.03f), sy = 1.06f, gy = -.35f, gain = .2f, blink = 0f, smile = .5f)
    Expr.Shy -> p(e(.055f, .075f, 10f, x = .85f, y = .035f), sx = .93f, sy = .93f, gx = -.5f, gy = .55f, gain = .2f, smile = .2f)
    Expr.Unimpressed -> p(e(.115f, .045f, y = .028f), sx = 1.03f, sy = .93f, gain = .2f, blink = 0f, smile = 0f)
    Expr.Sleepy -> p(e(.05f, .05f, y = .03f), sx = 1.04f, sy = .92f, gy = .5f, gain = 0f, blink = 0f, smile = 0f, zzz = 1f)
    Expr.Thinking -> p(e(.075f, .22f), gx = .65f, gy = -.65f, gain = .25f, smile = 0f, dots = 1f)
    Expr.Alert -> p(e(.11f, .15f), sx = 1.06f, sy = 1.08f, smile = 0f, o = 1f, gain = 0f, blink = 0f, bang = 1f)
}

/** The user's eye-style setting (0 pill, 1 oval, 2 dot) only reshapes tall, open eyes. */
fun styledEye(eye: Eye, style: Int): Eye {
    if (eye.arc > 0.001f || eye.h < 0.12f) return eye
    return when (style) {
        1 -> eye.copy(w = eye.w * 1.29f, h = eye.h * 0.75f)
        2 -> eye.copy(w = eye.w * 1.06f, h = eye.h * 0.45f)
        else -> eye
    }
}

const val TRANSITION_SECS = 0.45f

/** Exponential ease-out: fast start, soft landing, never overshoots. 0..1 -> 0..1. */
fun easeOut(x: Float): Float {
    if (x <= 0f) return 0f
    if (x >= 1f) return 1f
    return ((1f - exp(-5f * x)) / (1f - exp(-5f)))
}

private fun smooth(x: Float): Float {
    val c = x.coerceIn(0f, 1f)
    return c * c * (3f - 2f * c)
}

private fun hash(k: Int): Float {
    val v = sin(k * 12.9898 + 78.233) * 43758.5453
    return (v - floor(v)).toFloat()
}

class Face {
    var expr = Expr.Neutral
        private set

    private var from = poseOf(Expr.Neutral)
    private var to = from
    private var t0 = -10f

    // ---- expression selection -------------------------------------------------
    private var r1 = Expr.Neutral
    private var r1Until = -1f
    private var r2 = Expr.Neutral
    private var r2Until = -1f
    private var lastTouch = 0f

    /** Show [x] for [secs], then [then] for [thenSecs], then fall back to the base expression. */
    fun react(t: Float, x: Expr, secs: Float, then: Expr? = null, thenSecs: Float = 0f) {
        r1 = x; r1Until = t + secs
        if (then != null) { r2 = then; r2Until = t + secs + thenSecs } else r2Until = -1f
        lastTouch = t
    }

    fun touch(t: Float) { lastTouch = t }

    /** Call every frame with the expression the app state asks for. */
    fun update(t: Float, base: Expr) {
        var x = when {
            t < r1Until -> r1
            t < r2Until -> r2
            else -> base
        }
        if (x == Expr.Neutral && t - lastTouch > IDLE_SLEEP_SECS) x = Expr.Sleepy
        if (x != expr) {
            from = pose(t)
            to = poseOf(x)
            t0 = t
            expr = x
        }
    }

    /** The blended pose at time [t]. Pure for any t at or after the last expression change. */
    fun pose(t: Float): Pose {
        val k = easeOut((t - t0) / TRANSITION_SECS)
        return if (k >= 1f) to else from.lerp(to, k) // land exactly, no float drift
    }

    // ---- hops -----------------------------------------------------------------
    private val hops = ArrayList<FloatArray>() // (time, amplitude)

    fun hop(t: Float, amp: Float = 1f) {
        hops.removeAll { t - it[0] > 3f }
        hops.add(floatArrayOf(t, amp))
    }

    /** A tap: bounce, startled for a moment, then pleased. */
    fun poke(t: Float) {
        hop(t, 1.5f)
        react(t, Expr.Surprised, 0.55f, Expr.Happy, 1.15f)
    }

    /** Body lift/stretch from hops and from happy bobbing, roughly 0..0.12. */
    fun bounce(t: Float): Float {
        var b = 0f
        for (h in hops) {
            val dt = t - h[0]
            if (dt in 0f..3f) b += h[1] * 0.105f * exp(-4f * dt) * sin(9.5f * dt)
        }
        val bob = pose(t).bob
        if (bob > 0.01f) b += bob * 0.06f * max(0f, sin((2.0 * PI * 2.4 * t).toFloat()))
        return b
    }

    /** Sideways tremble in body-scale units. */
    fun shakeX(t: Float): Float = pose(t).shake * 0.006f * sin((2.0 * PI * 14.0 * t).toFloat())

    // ---- blink: a fixed pseudo-random schedule, so it is a pure function of time ----
    private val blinks = arrayListOf(2.5f)
    private var blinkK = 0

    private fun extendBlinks(t: Float) {
        while (blinks.last() < t + 10f) {
            val k = blinkK++
            val next = blinks.last() + 2f + 4f * hash(k)
            blinks.add(next)
            if (hash(k + 1000) < 0.2f) blinks.add(next + 0.28f) // now and then, a double blink
        }
    }

    /** 0 = open .. 1 = closed, before the pose's own blink gain is applied. */
    fun blinkRaw(t: Float): Float {
        extendBlinks(t)
        var i = blinks.binarySearch(t)
        if (i < 0) i = -i - 2
        if (i < 0) return 0f
        val ph = (t - blinks[i]) / BLINK_SECS
        return if (ph in 0f..1f) sin(PI.toFloat() * ph) else 0f
    }

    fun blink(t: Float): Float = blinkRaw(t) * pose(t).blink

    // ---- gaze -----------------------------------------------------------------
    private var gfx = 0f
    private var gfy = 0f
    private var gtx = 0f
    private var gty = 0f
    private var gt0 = -10f
    private var pointer = false
    private var released = -10f

    private fun pointerGaze(t: Float): Pair<Float, Float> {
        val k = easeOut((t - gt0) / 0.35f)
        return Pair(gfx + (gtx - gfx) * k, gfy + (gty - gfy) * k)
    }

    /** The user is dragging: look at (x, y), each in -1..1. */
    fun look(t: Float, x: Float, y: Float) {
        val (cx, cy) = pointerGaze(t)
        gfx = cx; gfy = cy
        gtx = x.coerceIn(-1f, 1f); gty = y.coerceIn(-1f, 1f)
        gt0 = t
        pointer = true
        lastTouch = t
    }

    fun release(t: Float) {
        pointer = false
        released = t
    }

    /** Eye direction, each -1..1: pointer target while touched, then drifting on its own. */
    fun gaze(t: Float): Pair<Float, Float> {
        val po = pose(t)
        val wx = 0.8f * (0.55f * sin(0.9f * t + 0.3f) + 0.45f * sin(1.7f * t + 2.1f))
        val wy = 0.45f * (0.6f * sin(0.6f * t + 1.2f) + 0.4f * sin(1.3f * t + 0.5f))
        val ax = po.gx + wx * po.gain
        val ay = po.gy + wy * po.gain
        val (px, py) = pointerGaze(t)
        val pw = if (pointer) 1f else 1f - smooth((t - released - 1.5f) / 1f)
        return Pair(px * pw + ax * (1f - pw), py * pw + ay * (1f - pw))
    }

    companion object {
        const val IDLE_SLEEP_SECS = 45f
        const val BLINK_SECS = 0.18f
    }
}
