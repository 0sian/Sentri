package uk.osianj.companion

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.TextMeasurer
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sign
import kotlin.math.sin

// ---- customisation options (indexes are stored in prefs) --------------------
internal val BodyColors = listOf(
    Color(0xFFFFD60A), // bright yellow
    Color(0xFFFF6A00), // orange
    Color(0xFF00C875), // green
    Color(0xFF1A88FF), // blue
    Color(0xFFEE9A86), // coral
    Color(0xFFB9A3E8), // lilac
    Color(0xFFEDE6DA), // bone
)
internal val ShapeNames = listOf("Cloud", "Round", "Squircle", "Tall")
internal val EyeNames = listOf("Pill", "Oval", "Dot")

// Cloud body = overlapping ellipses: (x, y, radius) in units of the body's half-width/half-height.
private val CloudLobes = arrayOf(
    floatArrayOf(-0.50f, 0.10f, 0.50f),
    floatArrayOf(0.50f, 0.18f, 0.50f),
    floatArrayOf(0.00f, -0.45f, 0.55f),
    floatArrayOf(0.00f, 0.35f, 0.62f),
    floatArrayOf(0.52f, -0.25f, 0.38f),
    floatArrayOf(-0.55f, -0.35f, 0.36f),
)

// =============================================================================
private class Clock { var t = 0f }

@Composable
fun CompanionScreen(vm: CompanionViewModel) {
    val state by vm.link.state.collectAsStateWithLifecycle()
    val caps by vm.link.caps.collectAsStateWithLifecycle()
    val chat = vm.chat
    val face = remember { Face() }
    val clock = remember { Clock() }
    var tick by remember { mutableLongStateOf(0L) }
    val textMeasurer = rememberTextMeasurer()
    var previewName by remember { mutableStateOf<String?>(null) }
    var previewIdx by remember { mutableIntStateOf(-1) }

    // what the app state says the character should be doing
    val base = when {
        state is Link.State.Failed -> Expr.Sad
        state is Link.State.Idle -> Expr.Sleepy
        state is Link.State.Connecting -> Expr.Thinking
        chat.pendingApproval -> Expr.Alert
        vm.cu != null || vm.guide -> Expr.Attentive
        vm.listening -> Expr.Curious
        chat.activeTurn != null -> if (chat.streaming) Expr.Attentive else Expr.Thinking
        else -> Expr.Neutral
    }
    val baseNow by rememberUpdatedState(base)
    val connected by rememberUpdatedState(state is Link.State.Connected)

    // one-off reactions. Each fires only for a count the character hasn't seen yet (the "seen" values live in
    // the ViewModel), so coming back to this screen doesn't replay old ones. A count lower than the seen value
    // means the chat was cleared: just catch up.
    LaunchedEffect(chat.doneCount) {
        if (chat.doneCount != vm.seenDone) {
            val fresh = chat.doneCount > vm.seenDone
            vm.seenDone = chat.doneCount
            // if the AI picked its own mood for this reply, let that stand instead of the generic happy blip
            if (fresh && chat.mood == null) { face.react(clock.t, Expr.Happy, 1.6f); face.hop(clock.t, 1f) }
        }
    }
    LaunchedEffect(chat.moodCount) {
        if (chat.moodCount != vm.seenMood) {
            val fresh = chat.moodCount > vm.seenMood
            vm.seenMood = chat.moodCount
            val x = chat.mood?.let { m -> Expr.values().firstOrNull { it.name.equals(m, ignoreCase = true) } }
            if (fresh && x != null) { face.react(clock.t, x, 4f); face.hop(clock.t, 0.8f) }
        }
    }
    LaunchedEffect(chat.confirmCount) {
        if (chat.confirmCount != vm.seenConfirm) {
            val fresh = chat.confirmCount > vm.seenConfirm
            vm.seenConfirm = chat.confirmCount
            if (fresh) face.hop(clock.t, 1.2f)
        }
    }
    LaunchedEffect(chat.errorCount) {
        if (chat.errorCount != vm.seenError) {
            val fresh = chat.errorCount > vm.seenError
            vm.seenError = chat.errorCount
            if (fresh) face.react(clock.t, Expr.Confused, 2.4f)
        }
    }

    LaunchedEffect(Unit) {
        var last = 0L
        var wasConnected = connected
        while (true) {
            withFrameNanos { ns ->
                if (last != 0L) {
                    clock.t += ((ns - last) / 1_000_000_000f).coerceAtMost(0.05f)
                    if (connected && !wasConnected) { face.react(clock.t, Expr.Happy, 2.5f); face.hop(clock.t, 1f) }
                    wasConnected = connected
                    face.update(clock.t, baseNow)
                }
                last = ns
                tick++
            }
        }
    }
    LaunchedEffect(previewName) {
        if (previewName != null) { kotlinx.coroutines.delay(2500); previewName = null }
    }

    val caption = when (val st = state) {
        is Link.State.Connected -> "Connected · ${st.host}"
        is Link.State.Connecting -> "Looking for your PC…"
        is Link.State.Failed -> st.reason
        is Link.State.Idle -> "Not connected"
    }
    val chatReady = "chat" in caps

    Column(
        Modifier.fillMaxSize().padding(horizontal = 16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(
            Modifier
                .weight(1f)
                .heightIn(min = 96.dp)
                .fillMaxWidth()
                .pointerInput(Unit) {
                    detectTapGestures(
                        onTap = { face.poke(clock.t) },
                        // long-press steps through every expression, handy for seeing the whole set
                        onLongPress = {
                            previewIdx = (previewIdx + 1) % Expr.values().size
                            val x = Expr.values()[previewIdx]
                            face.react(clock.t, x, 2.5f)
                            previewName = x.name
                        },
                    )
                }
                .pointerInput(Unit) {
                    fun gaze(p: Offset) {
                        val hw = size.width / 2f
                        val hh = size.height / 2f
                        face.look(clock.t, ((p.x - hw) / hw).coerceIn(-1f, 1f), ((p.y - hh) / hh).coerceIn(-1f, 1f))
                    }
                    detectDragGestures(
                        onDragStart = { gaze(it) },
                        onDrag = { change, _ -> gaze(change.position) },
                        onDragEnd = { face.release(clock.t) },
                        onDragCancel = { face.release(clock.t) },
                    )
                },
        ) {
            Canvas(Modifier.fillMaxSize()) {
                val frame = tick // read so the canvas redraws every frame
                if (frame >= 0L) {
                    drawPet(
                        face, clock.t,
                        BodyColors[vm.charColor.coerceIn(0, BodyColors.lastIndex)],
                        vm.charShape, vm.charEyes, vm.charMouth, vm.charWhiteEyes, textMeasurer,
                    )
                }
            }
            previewName?.let {
                Text(
                    it, color = TextDim, fontSize = 12.sp,
                    modifier = Modifier.align(Alignment.BottomCenter),
                )
            }
        }
        if (chatReady) {
            // with messages on screen the transcript gets most of the height; the character keeps the rest
            // enabled whenever paired: sending while the link is down reconnects first (see ChatDispatcher)
            ChatPanel(vm, enabled = vm.isPaired, modifier = if (chat.items.isNotEmpty()) Modifier.weight(1.6f) else Modifier)
        } else {
            Text(caption, color = TextMain, fontSize = 15.sp)
            Spacer(Modifier.height(4.dp))
            Text("Tap me · drag to make me look · hold to cycle moods", color = TextDim, fontSize = 12.sp)
            Spacer(Modifier.height(2.dp))
            Text(
                "Chat appears once the AI layer is running on your PC.",
                color = TextDim.copy(alpha = 0.7f), fontSize = 12.sp,
            )
        }
        Spacer(Modifier.height(12.dp))
    }
}

// =============================================================================
private fun DrawScope.drawPet(
    face: Face,
    t: Float,
    body: Color,
    shape: Int,
    eyeStyle: Int,
    showMouth: Boolean,
    whiteEyes: Boolean,
    tm: TextMeasurer,
) {
    val pose = face.pose(t)
    val (gx, gy) = face.gaze(t)
    val b = face.bounce(t)
    val blink = face.blink(t)

    // white eyes unless the body is so light they'd vanish
    val lum = 0.299f * body.red + 0.587f * body.green + 0.114f * body.blue
    val ink = if (whiteEyes && lum < 0.85f) Color.White else Ink

    val s = min(size.width, size.height) * 0.62f
    // thin dark ring so white eyes stay readable on light bodies like yellow
    val outline = if (ink == Color.White) s * 0.011f else 0f
    val cx = size.width / 2f + face.shakeX(t) * s
    val baseY = size.height * 0.48f
    val breath = sin(t * if (pose.zzz > 0.5f) 1.1f else 1.7f)

    val (aF, bF, n) = when (shape) {
        0 -> Triple(0.52f, 0.43f, 0f)      // cloud (n unused)
        2 -> Triple(0.5f, 0.44f, 3.4f)     // squircle
        3 -> Triple(0.4f, 0.56f, 2.4f)     // tall
        else -> Triple(0.5f, 0.47f, 2.0f)  // round
    }
    val sx = pose.sx * (1f + 0.014f * breath - b * 0.25f)
    val sy = pose.sy * (1f - 0.014f * breath + b * 0.35f)
    val a = s * aF * sx
    val hb = s * bF * sy
    val groundY = baseY + s * bF
    val cy = groundY - hb - b * s * 0.5f

    // body: flat colour, no outline or shadow
    if (shape == 0) {
        // lobes drift slightly so the cloud feels alive
        for ((i, l) in CloudLobes.withIndex()) {
            val ox = l[0] + 0.03f * sin(t * 1.3f + i * 1.7f)
            val oy = l[1]
            val r = (l[2] + 0.02f * sin(t * 1.1f + i * 2.3f)) * pose.puff
            val x = cx + ox * a
            val y = cy + oy * hb
            drawOval(body, Offset(x - r * a, y - r * hb), Size(2f * r * a, 2f * r * hb))
        }
    } else {
        val path = Path()
        val steps = 96
        for (i in 0..steps) {
            val th = (i / steps.toFloat()) * 2f * PI.toFloat()
            val c = cos(th)
            val sn = sin(th)
            val x = cx + a * pose.puff * sign(c) * abs(c).pow(2f / n)
            val y = cy + hb * pose.puff * sign(sn) * abs(sn).pow(2f / n)
            if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
        }
        path.close()
        drawPath(path, body)
    }

    // face
    val fx = cx + gx * s * 0.05f
    val fy = cy - hb * 0.10f + gy * s * 0.035f
    val eyeDx = a * (if (shape == 0) 0.30f else 0.34f)
    val open = (1f - blink * 0.95f).coerceAtLeast(0.08f)

    for (side in intArrayOf(-1, 1)) {
        val eye = styledEye(if (side < 0) pose.l else pose.r, eyeStyle)
        val ex = fx + side * eyeDx * eye.x
        val ey = fy + eye.y * s
        val w = s * eye.w
        val h = s * eye.h * open
        val pillA = (1f - eye.arc).coerceIn(0f, 1f)
        val arcA = eye.arc.coerceIn(0f, 1f)
        val tilt = eye.tilt + gx * 6f
        rotate(tilt, Offset(ex, ey)) {
            if (pillA > 0.01f) {
                val r = min(w, h) / 2f
                if (outline > 0f) {
                    val ring = Ink.copy(alpha = pillA)
                    val tlo = Offset(ex - w / 2f - outline, ey - h / 2f - outline)
                    val so = Size(w + 2f * outline, h + 2f * outline)
                    if (eyeStyle == 1 || eyeStyle == 2) drawOval(ring, tlo, so)
                    else drawRoundRect(ring, tlo, so, CornerRadius(r + outline, r + outline))
                }
                val tl = Offset(ex - w / 2f, ey - h / 2f)
                val c = ink.copy(alpha = pillA)
                if (eyeStyle == 1 || eyeStyle == 2) drawOval(c, tl, Size(w, h))
                else drawRoundRect(c, tl, Size(w, h), CornerRadius(r, r))
            }
            if (arcA > 0.01f) {
                // happy eyes: ^ ^
                val hw = s * eye.w
                if (outline > 0f) {
                    drawArc(
                        Ink.copy(alpha = arcA), 200f, 140f, false,
                        Offset(ex - hw, ey - hw * 0.6f), Size(hw * 2f, hw * 1.4f),
                        style = Stroke(s * 0.04f + 2f * outline, cap = StrokeCap.Round),
                    )
                }
                drawArc(
                    ink.copy(alpha = arcA), 200f, 140f, false,
                    Offset(ex - hw, ey - hw * 0.6f), Size(hw * 2f, hw * 1.4f),
                    style = Stroke(s * 0.04f, cap = StrokeCap.Round),
                )
            }
        }
    }

    if (showMouth) {
        val my = fy + hb * 0.34f
        if (pose.mouthO > 0.02f) {
            val o = pose.mouthO.coerceIn(0f, 1f)
            drawOval(
                ink.copy(alpha = o),
                Offset(fx - s * 0.035f * o, my - s * 0.045f * o),
                Size(s * 0.07f * o, s * 0.095f * o),
            )
        }
        val curveA = (1f - pose.mouthO).coerceIn(0f, 1f)
        if (curveA > 0.02f) {
            val p = Path().apply {
                moveTo(fx - s * 0.07f, my)
                quadraticBezierTo(fx, my + pose.smile * s * 0.16f, fx + s * 0.07f, my)
            }
            drawPath(p, ink.copy(alpha = curveA), style = Stroke(s * 0.028f, cap = StrokeCap.Round))
        }
    }

    // thinking: three dots that pulse one after another, up beside the head
    if (pose.dots > 0.01f) {
        val ox = cx + a * 0.72f
        val oy = cy - hb * 0.95f - s * 0.02f
        for (i in 0..2) {
            val pulse = 0.6f + 0.4f * max(0f, sin(2f * PI.toFloat() * (t * 1.1f - i * 0.18f)))
            drawCircle(
                body.copy(alpha = pose.dots.coerceIn(0f, 1f)),
                radius = s * 0.026f * pulse,
                center = Offset(ox + i * s * 0.07f, oy - i * s * 0.035f),
            )
        }
    }

    // needs your attention: "!" above the head
    if (pose.bang > 0.01f) {
        val k = pose.bang.coerceIn(0f, 1f)
        val bw = s * 0.055f * k
        val bh = s * 0.15f * k
        val top = cy - hb - s * 0.02f - s * 0.20f * k
        val col = body.copy(alpha = k)
        drawRoundRect(col, Offset(cx - bw / 2f, top), Size(bw, bh), CornerRadius(bw / 2f, bw / 2f))
        drawCircle(col, radius = s * 0.032f * k, center = Offset(cx, top + bh + s * 0.055f * k))
    }

    // zzz while dozing
    if (pose.zzz > 0.4f) {
        for (i in 0..2) {
            val ph = (t * 0.45f + i / 3f) % 1f
            val alpha = (sin(PI.toFloat() * ph) * pose.zzz).coerceIn(0f, 1f)
            drawText(
                tm, "z",
                topLeft = Offset(cx + a * 0.75f + ph * s * 0.1f, cy - hb * 0.8f - ph * s * 0.3f),
                style = TextStyle(color = TextDim.copy(alpha = alpha), fontSize = (13f + ph * 12f).sp),
            )
        }
    }
}
