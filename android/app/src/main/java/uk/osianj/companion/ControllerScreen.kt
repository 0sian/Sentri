package uk.osianj.companion

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.positionChange
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.OffsetMapping
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.text.input.TransformedText
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.math.hypot
import kotlin.math.max

// =============================================================================
// Controller: trackpad, typing bar, click buttons, key / shortcut / media strips
// =============================================================================
@Composable
fun ControlScreen(vm: CompanionViewModel) {
    val state by vm.link.state.collectAsStateWithLifecycle()
    val connected = state is Link.State.Connected
    val view = LocalView.current
    DisposableEffect(Unit) {
        view.keepScreenOn = true
        onDispose { view.keepScreenOn = false }
    }

    Column(
        Modifier
            .fillMaxSize()
            .padding(horizontal = 14.dp)
    ) {
        Trackpad(vm, connected, Modifier.weight(1f).fillMaxWidth())
        Spacer(Modifier.height(10.dp))

        TypeBar(vm)
        Spacer(Modifier.height(8.dp))

        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            HoldButton("Left click", "left", vm, Modifier.weight(1f))
            HoldButton("Right click", "right", vm, Modifier.weight(1f))
        }
        Spacer(Modifier.height(8.dp))
        KeyStrip(vm)
        Spacer(Modifier.height(8.dp))
        ShortcutStrip(vm)
        Spacer(Modifier.height(8.dp))
        MediaStrip(vm)
        Spacer(Modifier.height(10.dp))
    }
}

// -----------------------------------------------------------------------------
// Trackpad
// -----------------------------------------------------------------------------
@Composable
private fun Trackpad(vm: CompanionViewModel, connected: Boolean, modifier: Modifier) {
    val haptic = LocalHapticFeedback.current
    var touched by remember { mutableStateOf(false) }
    val shape = RoundedCornerShape(28.dp)

    Box(
        modifier
            .clip(shape)
            .background(Pad)
            .border(1.dp, if (touched) Accent.copy(alpha = 0.55f) else Hairline, shape)
            .drawBehind {
                val step = 30.dp.toPx()
                var y = step / 2
                while (y < size.height) {
                    var x = step / 2
                    while (x < size.width) {
                        drawCircle(DotColor, 1.4.dp.toPx(), Offset(x, y))
                        x += step
                    }
                    y += step
                }
            }
            .alpha(if (connected) 1f else 0.5f)
            .pointerInput(Unit) {
                var lastTapUp = 0L
                val slop = 4.dp.toPx()
                val tapSlop = 10.dp.toPx()
                val notchPx = 38.dp.toPx()

                awaitEachGesture {
                    val down = awaitFirstDown(requireUnconsumed = false)
                    down.consume()
                    touched = true
                    vm.markPadHintSeen()

                    val t0 = down.uptimeMillis
                    var lastT = t0
                    var maxFingers = 1
                    var travel = 0f
                    var moving = false
                    val dragging = t0 - lastTapUp < 280
                    if (dragging) {
                        vm.link.button("left", "down")
                        moving = true
                    }

                    do {
                        val event = awaitPointerEvent()
                        val pressed = event.changes.filter { it.pressed }
                        val now = event.changes[0].uptimeMillis
                        if (pressed.isNotEmpty()) {
                            maxFingers = max(maxFingers, pressed.size)
                            var sx = 0f
                            var sy = 0f
                            for (c in pressed) {
                                val d = c.positionChange()
                                sx += d.x; sy += d.y
                            }
                            val n = pressed.size
                            val ax = sx / n
                            val ay = sy / n
                            travel += hypot(ax, ay)
                            val dt = max(1L, now - lastT).toFloat()

                            if (n >= 2) {
                                if (travel > slop) {
                                    // kernel convention: wheel up / scroll right are positive.
                                    // natural = content follows fingers.
                                    val s = if (vm.naturalScroll) 1f else -1f
                                    vm.link.scroll(-s * ax / notchPx, s * ay / notchPx)
                                }
                            } else if (maxFingers < 2) {
                                if (!moving && travel > slop) moving = true
                                if (moving) {
                                    val speed = hypot(ax, ay) / dt // px per ms
                                    val gain = vm.sensitivity * (0.7f + 0.9f * speed).coerceIn(0.7f, 3.0f)
                                    vm.link.move(ax * gain, ay * gain)
                                }
                            }
                            event.changes.forEach { it.consume() }
                        }
                        lastT = now
                    } while (event.changes.any { it.pressed })

                    val duration = lastT - t0
                    if (dragging) {
                        vm.link.button("left", "up")
                        lastTapUp = 0L
                    } else if (duration < 260 && travel < tapSlop) {
                        when (maxFingers) {
                            1 -> { vm.link.button("left", "click"); lastTapUp = lastT }
                            2 -> vm.link.button("right", "click")
                            else -> vm.link.button("middle", "click")
                        }
                        haptic.performHapticFeedback(HapticFeedbackType.TextHandleMove)
                    }
                    touched = false
                }
            },
        contentAlignment = Alignment.Center,
    ) {
        if (!vm.padHintSeen) {
            Text(
                "Drag to move\nTap to click · two fingers to scroll\nTwo-finger tap for right click · tap, then hold to drag",
                color = TextDim, fontSize = 13.sp, lineHeight = 20.sp, textAlign = TextAlign.Center,
                modifier = Modifier.padding(32.dp),
            )
        }
    }
}

// -----------------------------------------------------------------------------
// Typing bar: a visible field. Whatever you type is sent to the PC live.
// The field keeps an invisible 8-space buffer in front so Backspace always has
// something to delete (soft keyboards don't report Backspace on an empty field).
// -----------------------------------------------------------------------------
private const val SENTINEL = "        "

private val HideSentinel = VisualTransformation { text ->
    val n = minOf(SENTINEL.length, text.length)
    TransformedText(
        AnnotatedString(text.text.drop(n)),
        object : OffsetMapping {
            override fun originalToTransformed(offset: Int) = (offset - n).coerceAtLeast(0)
            override fun transformedToOriginal(offset: Int) = offset + n
        },
    )
}

@Composable
private fun TypeBar(vm: CompanionViewModel) {
    var value by remember { mutableStateOf(TextFieldValue(SENTINEL, TextRange(SENTINEL.length))) }
    var focused by remember { mutableStateOf(false) }
    val shape = RoundedCornerShape(16.dp)
    fun reset() { value = TextFieldValue(SENTINEL, TextRange(SENTINEL.length)) }

    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        BasicTextField(
            value = value,
            onValueChange = { nv ->
                val old = value.text
                val new = nv.text
                var p = 0
                val m = minOf(old.length, new.length)
                while (p < m && old[p] == new[p]) p++
                repeat(old.length - p) { vm.backspace() }
                val added = new.substring(p)
                if (added.isNotEmpty()) vm.typeText(added)
                // keep the cursor at the end so edits always map onto "append / backspace"
                value = if (new.length < SENTINEL.length || new.length > 160)
                    TextFieldValue(SENTINEL, TextRange(SENTINEL.length))
                else nv.copy(selection = TextRange(new.length))
            },
            singleLine = true,
            textStyle = TextStyle(color = TextMain, fontSize = 16.sp),
            cursorBrush = SolidColor(Accent),
            visualTransformation = HideSentinel,
            keyboardOptions = KeyboardOptions(
                autoCorrectEnabled = false,
                keyboardType = KeyboardType.Text,
                imeAction = ImeAction.Send,
            ),
            keyboardActions = KeyboardActions(onSend = { vm.pressKey("enter"); reset() }),
            modifier = Modifier
                .weight(1f)
                .height(52.dp)
                .clip(shape)
                .background(Panel)
                .border(1.dp, if (focused) Accent else Hairline, shape)
                .padding(horizontal = 16.dp)
                .onFocusChanged { focused = it.isFocused },
            decorationBox = { inner ->
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.CenterStart) {
                    if (value.text.length <= SENTINEL.length) {
                        Text("Tap here to type on the PC", color = TextDim, fontSize = 15.sp)
                    }
                    inner()
                }
            },
        )
        KeyChip("Enter", Modifier.height(52.dp)) { vm.pressKey("enter"); reset() }
    }
}

// -----------------------------------------------------------------------------
// Buttons and strips
// -----------------------------------------------------------------------------
@Composable
private fun HoldButton(label: String, button: String, vm: CompanionViewModel, modifier: Modifier) {
    var pressed by remember { mutableStateOf(false) }
    val haptic = LocalHapticFeedback.current
    val shape = RoundedCornerShape(16.dp)
    Box(
        modifier
            .height(56.dp)
            .clip(shape)
            .background(if (pressed) Hairline else Panel)
            .border(1.dp, Hairline, shape)
            .pointerInput(Unit) {
                detectTapGestures(onPress = {
                    pressed = true
                    vm.link.button(button, "down")
                    haptic.performHapticFeedback(HapticFeedbackType.TextHandleMove)
                    tryAwaitRelease()
                    vm.link.button(button, "up")
                    pressed = false
                })
            },
        contentAlignment = Alignment.Center,
    ) { Text(label, color = TextMain, fontSize = 15.sp, fontWeight = FontWeight.Medium) }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun KeyChip(
    label: String,
    modifier: Modifier = Modifier.height(44.dp),
    active: Boolean = false,
    hPad: Int = 14,
    danger: Boolean = false,
    onLongClick: (() -> Unit)? = null,
    onClick: () -> Unit,
) {
    val shape = RoundedCornerShape(14.dp)
    Box(
        modifier
            .clip(shape)
            .background(if (active) Accent else Panel)
            .border(1.dp, if (active) Accent else if (danger) Bad.copy(alpha = 0.6f) else Hairline, shape)
            .combinedClickable(onClick = onClick, onLongClick = onLongClick)
            .padding(horizontal = hPad.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            label, color = if (active) Ink else if (danger) Bad else TextMain,
            fontSize = 14.sp, fontWeight = FontWeight.Medium, maxLines = 1,
        )
    }
}

@Composable
private fun KeyStrip(vm: CompanionViewModel) {
    val h = Modifier.height(44.dp)
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        // scrollable keys, with a fade on whichever edge has more to scroll to
        val scroll = rememberScrollState()
        Box(Modifier.weight(1f)) {
            Row(
                Modifier.fillMaxWidth().horizontalScroll(scroll),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                // modifiers are one-shot: tap to arm, then press the next key. Long-press taps the key alone.
                KeyChip("Ctrl", h, active = "ctrl" in vm.mods, onLongClick = { vm.tapModAlone("ctrl") }) { vm.toggleMod("ctrl") }
                KeyChip("Shift", h, active = "shift" in vm.mods, onLongClick = { vm.tapModAlone("shift") }) { vm.toggleMod("shift") }
                KeyChip("Alt", h, active = "alt" in vm.mods, onLongClick = { vm.tapModAlone("alt") }) { vm.toggleMod("alt") }
                KeyChip("Super", h, active = "super" in vm.mods, onLongClick = { vm.tapModAlone("super") }) { vm.toggleMod("super") }
                KeyChip("Esc", h) { vm.pressKey("esc") }
                KeyChip("Tab", h) { vm.pressKey("tab") }
                RepeatChip("Bksp", "backspace", vm, h)
                RepeatChip("Del", "delete", vm, h)
                KeyChip("Home", h) { vm.pressKey("home") }
                KeyChip("End", h) { vm.pressKey("end") }
                KeyChip("PgUp", h) { vm.pressKey("pageup") }
                KeyChip("PgDn", h) { vm.pressKey("pagedown") }
            }
            if (scroll.canScrollForward) EdgeFade(Modifier.align(Alignment.CenterEnd), toRight = true)
            if (scroll.canScrollBackward) EdgeFade(Modifier.align(Alignment.CenterStart), toRight = false)
        }
        // arrows stay on screen; hold to repeat
        val a = Modifier.height(44.dp).width(40.dp)
        RepeatChip("\u2190", "left", vm, a, hPad = 0)
        RepeatChip("\u2193", "down", vm, a, hPad = 0)
        RepeatChip("\u2191", "up", vm, a, hPad = 0)
        RepeatChip("\u2192", "right", vm, a, hPad = 0)
    }
}

@Composable
private fun EdgeFade(modifier: Modifier, toRight: Boolean) {
    val colors = if (toRight) listOf(Color.Transparent, Ink) else listOf(Ink, Color.Transparent)
    Box(modifier.width(28.dp).height(44.dp).background(Brush.horizontalGradient(colors)))
}

/**
 * A key that fires on press and keeps repeating while held (after a short pause), like a real keyboard.
 * Armed modifiers apply to every repeat, so Shift + held arrow keeps selecting.
 */
@Composable
private fun RepeatChip(label: String, key: String, vm: CompanionViewModel, modifier: Modifier, hPad: Int = 14) {
    var pressed by remember { mutableStateOf(false) }
    val haptic = LocalHapticFeedback.current
    val shape = RoundedCornerShape(14.dp)
    Box(
        modifier
            .clip(shape)
            .background(if (pressed) Hairline else Panel)
            .border(1.dp, Hairline, shape)
            .pointerInput(key) {
                detectTapGestures(onPress = {
                    pressed = true
                    val mods = vm.mods.toList()
                    vm.mods.clear()
                    vm.link.key(key, mods)
                    haptic.performHapticFeedback(HapticFeedbackType.TextHandleMove)
                    coroutineScope {
                        val repeat = launch {
                            delay(420)
                            while (true) { vm.link.key(key, mods); delay(55) }
                        }
                        tryAwaitRelease()
                        repeat.cancel()
                    }
                    pressed = false
                })
            }
            .padding(horizontal = hPad.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(label, color = TextMain, fontSize = 14.sp, fontWeight = FontWeight.Medium, maxLines = 1)
    }
}

private data class Shortcut(
    val label: String,
    val key: String,
    val mods: List<String>,
    val danger: Boolean = false,
)

// Edit this list to add or change shortcuts. Keys use the daemon's key names (see PROTOCOL.md).
private val Shortcuts = listOf(
    Shortcut("Super+Q", "q", listOf("super"), danger = true), // close window on Hyprland
    Shortcut("Alt+Tab", "tab", listOf("alt")),
    Shortcut("Ctrl+C", "c", listOf("ctrl")),
    Shortcut("Ctrl+V", "v", listOf("ctrl")),
    Shortcut("Ctrl+Z", "z", listOf("ctrl")),
    Shortcut("Ctrl+A", "a", listOf("ctrl")),
    Shortcut("Ctrl+W", "w", listOf("ctrl")),
    Shortcut("Ctrl+T", "t", listOf("ctrl")),
)

@Composable
private fun ShortcutStrip(vm: CompanionViewModel) {
    val haptic = LocalHapticFeedback.current
    Row(
        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        for (s in Shortcuts) {
            KeyChip(s.label, Modifier.height(44.dp), danger = s.danger) {
                haptic.performHapticFeedback(HapticFeedbackType.TextHandleMove)
                vm.link.key(s.key, s.mods)
                vm.mods.clear() // don't leave an armed modifier lingering
            }
        }
    }
}

@Composable
private fun MediaStrip(vm: CompanionViewModel) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        val m = Modifier.weight(1f).height(44.dp)
        KeyChip("Prev", m, hPad = 2) { vm.link.key("prev") }
        KeyChip("Play", m, hPad = 2) { vm.link.key("playpause") }
        KeyChip("Next", m, hPad = 2) { vm.link.key("next") }
        KeyChip("Vol −", m, hPad = 2) { vm.link.key("voldown") }
        KeyChip("Vol +", m, hPad = 2) { vm.link.key("volup") }
        KeyChip("Mute", m, hPad = 2) { vm.link.key("mute") }
    }
}
