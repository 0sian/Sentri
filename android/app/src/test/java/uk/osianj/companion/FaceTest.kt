package uk.osianj.companion

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class FaceTest {

    @Test fun transitionNeverOvershootsAndLandsExactly() {
        val f = Face()
        f.update(1f, Expr.Happy)
        var prev = -1f
        var t = 1f
        while (t <= 1.6f) {
            val arc = f.pose(t).l.arc
            assertTrue("arc must not decrease", arc >= prev - 1e-6f)
            assertTrue("arc must not overshoot", arc <= 1f + 1e-6f)
            prev = arc
            t += 0.01f
        }
        assertEquals(poseOf(Expr.Happy), f.pose(1f + TRANSITION_SECS + 0.01f))
    }

    @Test fun retargetingMidTransitionIsContinuous() {
        val f = Face()
        f.update(1f, Expr.Happy)
        val before = f.pose(1.1f)
        f.update(1.1f, Expr.Sad)
        val after = f.pose(1.1f)
        assertEquals(before.l.arc, after.l.arc, 1e-5f)
        assertEquals(before.l.tilt, after.l.tilt, 1e-4f)
        assertEquals(before.sy, after.sy, 1e-5f)
    }

    @Test fun framesAreAPureFunctionOfTime() {
        val f = Face()
        f.update(2f, Expr.Thinking)
        for (t in listOf(2.1f, 3.3f, 17.9f, 42f)) {
            assertEquals(f.pose(t), f.pose(t))
            assertEquals(f.blink(t), f.blink(t), 0f)
            assertEquals(f.gaze(t), f.gaze(t))
            assertEquals(f.bounce(t), f.bounce(t), 0f)
        }
        // asking about a later time first must not change what an earlier time returns
        val early = f.blinkRaw(5f)
        f.blinkRaw(500f)
        assertEquals(early, f.blinkRaw(5f), 0f)
    }

    @Test fun blinksAreSpacedAndStayInRange() {
        val f = Face()
        var blinks = 0
        var wasShut = false
        var t = 0f
        while (t < 120f) {
            val b = f.blinkRaw(t)
            assertTrue(b in 0f..1f)
            val shut = b > 0.5f
            if (shut && !wasShut) blinks++
            wasShut = shut
            t += 0.02f
        }
        // 2-6 s between blinks, plus the odd double blink
        assertTrue("blinks in 2 minutes: $blinks", blinks in 18..90)
    }

    @Test fun expressionsWithBlinkGainZeroNeverCloseTheEyes() {
        val f = Face()
        f.update(0f, Expr.Proud)
        var sawRawBlink = false
        for (i in 0..600) {
            val t = 1f + i * 0.02f // after the transition has finished
            if (f.blinkRaw(t) > 0.1f) sawRawBlink = true
            assertEquals(0f, f.blink(t), 0f)
        }
        assertTrue("schedule should still be running underneath", sawRawBlink)
    }

    @Test fun everyExpressionIsSane() {
        for (x in Expr.values()) {
            val p = poseOf(x)
            for (eye in listOf(p.l, p.r)) {
                assertTrue("$x w", eye.w in 0.03f..0.14f)
                assertTrue("$x h", eye.h in 0.02f..0.30f)
                assertTrue("$x arc", eye.arc in 0f..1f)
                // a clearly tilted pill must not be near-circular, or the tilt can't be seen
                if (eye.arc < 0.5f && kotlin.math.abs(eye.tilt) >= 20f) {
                    val ratio = eye.w / eye.h
                    assertTrue("$x tilted eye looks round ($ratio)", ratio < 0.8f || ratio > 1.25f)
                }
            }
        }
        assertEquals(18, Expr.values().size)
    }

    @Test fun mirroredMoodsMirror() {
        val angry = poseOf(Expr.Angry)
        assertEquals(angry.l.tilt, -angry.r.tilt, 1e-6f)
        val sad = poseOf(Expr.Sad)
        assertEquals(sad.l.tilt, -sad.r.tilt, 1e-6f)
        // angry tops lean outward, sad tops lean inward
        assertTrue(angry.l.tilt < 0f && angry.r.tilt > 0f)
        assertTrue(sad.l.tilt > 0f && sad.r.tilt < 0f)
    }

    @Test fun reactionsExpireBackToBase() {
        val f = Face()
        f.poke(1f)
        f.update(1.1f, Expr.Neutral); assertEquals(Expr.Surprised, f.expr)
        f.update(1.8f, Expr.Neutral); assertEquals(Expr.Happy, f.expr)
        f.update(3.0f, Expr.Neutral); assertEquals(Expr.Neutral, f.expr)
    }

    @Test fun dozesOffWhenLeftAloneButNotWhenBusy() {
        val f = Face()
        f.update(10f, Expr.Neutral); assertEquals(Expr.Neutral, f.expr)
        f.update(50f, Expr.Neutral); assertEquals(Expr.Sleepy, f.expr)
        f.update(51f, Expr.Thinking); assertEquals(Expr.Thinking, f.expr)
        f.touch(60f)
        f.update(61f, Expr.Neutral); assertEquals(Expr.Neutral, f.expr)
    }

    @Test fun gazeFollowsPointerThenDriftsFree() {
        val f = Face()
        f.update(0f, Expr.Neutral)
        f.look(1f, 1f, -1f)
        val (x, y) = f.gaze(2f)
        assertEquals(1f, x, 0.02f)
        assertEquals(-1f, y, 0.02f)
        f.look(2f, 5f, 5f) // out-of-range input is clamped
        assertTrue(f.gaze(4f).first <= 1.0001f)
        f.release(4f)
        assertEquals(1f, f.gaze(5f).first, 0.02f) // holds the look for a moment
        val free = f.gaze(40f)
        assertTrue(kotlin.math.abs(free.first) <= 1f && kotlin.math.abs(free.second) <= 1f)
    }

    @Test fun hopsSettleToNothing() {
        val f = Face()
        f.hop(1f, 1.5f)
        var peak = 0f
        var t = 1f
        while (t < 1.8f) { peak = maxOf(peak, f.bounce(t)); t += 0.01f }
        assertTrue("peak $peak", peak in 0.02f..0.2f)
        assertEquals(0f, f.bounce(4.5f), 1e-4f)
    }

    @Test fun styleOnlyReshapesTallOpenEyes() {
        val happy = poseOf(Expr.Happy).l
        assertEquals(happy, styledEye(happy, 1))
        val dash = poseOf(Expr.Proud).l
        assertEquals(dash, styledEye(dash, 2))
        val tall = poseOf(Expr.Neutral).l
        assertTrue(styledEye(tall, 1).h < tall.h)
        assertEquals(tall, styledEye(tall, 0))
    }

    /** Writes every pose as JSON so the preview renderer draws exactly what the app would. */
    @Test fun dumpPosesForPreview() {
        val sb = StringBuilder("{")
        for ((i, x) in Expr.values().withIndex()) {
            val p = poseOf(x)
            fun eye(e: Eye) = "[${e.w},${e.h},${e.tilt},${e.arc},${e.x},${e.y}]"
            if (i > 0) sb.append(",")
            sb.append("\"${x.name}\":{\"l\":${eye(p.l)},\"r\":${eye(p.r)},\"sx\":${p.sx},\"sy\":${p.sy},")
            sb.append("\"puff\":${p.puff},\"gx\":${p.gx},\"gy\":${p.gy},\"smile\":${p.smile},\"o\":${p.mouthO},")
            sb.append("\"dots\":${p.dots},\"bang\":${p.bang},\"zzz\":${p.zzz}}")
        }
        sb.append("}")
        File("build/poses.json").apply { parentFile.mkdirs() }.writeText(sb.toString())
    }
}
