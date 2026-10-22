package uk.osianj.companion

import android.graphics.Color as AColor
import android.os.Bundle
import android.view.KeyEvent
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
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
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.isImeVisible
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
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
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.positionChange
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlin.math.hypot
import kotlin.math.max

// ---- palette: warm ink, amber accent ----------------------------------------
private val Ink = Color(0xFF121110)
private val Surface = Color(0xFF1B1917)
private val Pad = Color(0xFF1F1D1A)
private val Hairline = Color(0xFF2E2B27)
private val TextMain = Color(0xFFEDE6DA)
private val TextDim = Color(0xFF9A9189)
private val Accent = Color(0xFFE3B05B)
private val Good = Color(0xFF7CC38A)
private val Bad = Color(0xFFE0795F)
private val DotColor = Color(0x16EDE6DA)

class MainActivity : ComponentActivity() {
    private val vm: CompanionViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(AColor.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(AColor.TRANSPARENT),
        )
        setContent {
            MaterialTheme(
                colorScheme = darkColorScheme(
                    primary = Accent, onPrimary = Ink,
                    background = Ink, onBackground = TextMain,
                    surface = Surface, onSurface = TextMain,
                    surfaceVariant = Surface, onSurfaceVariant = TextDim,
                    outline = Color(0xFF5A534B), outlineVariant = Hairline,
                )
            ) { App(vm) }
        }
    }

    override fun onStart() {
        super.onStart()
        vm.onForeground()
    }

    override fun onStop() {
        super.onStop()
        vm.onBackground()
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        if (vm.handleHardwareKey(keyCode)) return true
        return super.onKeyDown(keyCode, event)
    }
}

@Composable
fun App(vm: CompanionViewModel) {
    var editing by remember { mutableStateOf(!vm.isPaired) }
    Box(
        Modifier
            .fillMaxSize()
            .background(Ink)
            .systemBarsPadding()
            .imePadding()
    ) {
        if (editing) SettingsScreen(vm) { editing = false }
        else ControlScreen(vm) { editing = true }
    }
}

// =============================================================================
// Settings / pairing
// =============================================================================
@Composable
fun SettingsScreen(vm: CompanionViewModel, onDone: () -> Unit) {
    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 22.dp, vertical = 18.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Text(
            if (vm.isPaired) "Settings" else "Pair with your PC",
            color = TextMain, fontSize = 28.sp, fontWeight = FontWeight.SemiBold,
        )
        if (!vm.isPaired) {
            Text(
                "Start the daemon on your PC. It prints its address and a pairing token - enter both here once.",
                color = TextDim, fontSize = 14.sp,
            )
        }

        OutlinedTextField(
            value = vm.host, onValueChange = { vm.host = it },
            label = { Text("PC address") }, placeholder = { Text("192.168.1.50") },
            singleLine = true, modifier = Modifier.fillMaxWidth(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
        )
        OutlinedTextField(
            value = vm.port, onValueChange = { vm.port = it.filter(Char::isDigit) },
            label = { Text("Port") }, singleLine = true, modifier = Modifier.fillMaxWidth(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
        )
        OutlinedTextField(
            value = vm.token, onValueChange = { vm.token = it },
            label = { Text("Pairing token") }, singleLine = true, modifier = Modifier.fillMaxWidth(),
            keyboardOptions = KeyboardOptions(autoCorrectEnabled = false),
        )

        Spacer(Modifier.height(6.dp))
        Text("Pointer speed  ·  ${"%.1f".format(vm.sensitivity)}x", color = TextMain, fontSize = 15.sp)
        Slider(
            value = vm.sensitivity, onValueChange = { vm.sensitivity = it },
            valueRange = 0.5f..3.5f, onValueChangeFinished = { vm.savePrefsOnly() },
        )
        SwitchRow("Natural scrolling", "Content follows your fingers", vm.naturalScroll) {
            vm.naturalScroll = it; vm.savePrefsOnly()
        }
        SwitchRow("Phone volume keys control PC", "Instead of the phone's own volume", vm.volumeKeys) {
            vm.volumeKeys = it; vm.savePrefsOnly()
        }

        Spacer(Modifier.height(6.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
            Button(
                onClick = { vm.saveAndConnect(); onDone() },
                enabled = vm.host.isNotBlank() && vm.token.isNotBlank(),
                colors = ButtonDefaults.buttonColors(containerColor = Accent, contentColor = Ink),
                shape = RoundedCornerShape(14.dp),
                modifier = Modifier.height(50.dp),
            ) { Text(if (vm.isPaired) "Save & reconnect" else "Connect", fontWeight = FontWeight.SemiBold) }
            if (vm.isPaired) TextButton(onClick = { vm.savePrefsOnly(); onDone() }) {
                Text("Back", color = TextDim)
            }
        }
    }
}

@Composable
private fun SwitchRow(title: String, sub: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(title, color = TextMain, fontSize = 15.sp)
            Text(sub, color = TextDim, fontSize = 12.sp)
        }
        Switch(checked = checked, onCheckedChange = onChange)
    }
}

// =============================================================================
// Control surface
// =============================================================================
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ControlScreen(vm: CompanionViewModel, onSettings: () -> Unit) {
    val state by vm.link.state.collectAsStateWithLifecycle()
    val view = LocalView.current
    DisposableEffect(Unit) {
        view.keepScreenOn = true
        onDispose { view.keepScreenOn = false }
    }
    val focus = remember { FocusRequester() }
    val kb = LocalSoftwareKeyboardController.current
    val imeVisible = WindowInsets.isImeVisible
    val connected = state is Link.State.Connected

    Column(
        Modifier
            .fillMaxSize()
            .padding(horizontal = 14.dp)
    ) {
        StatusRow(state, vm, onSettings)

        Trackpad(vm, connected, Modifier.weight(1f).fillMaxWidth())
        Spacer(Modifier.height(10.dp))

        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            HoldButton("Left click", "left", vm, Modifier.weight(1f))
            HoldButton("Right click", "right", vm, Modifier.weight(1f))
            KeyChip(
                if (imeVisible) "Hide keys" else "Keyboard",
                Modifier.weight(1f).height(56.dp),
                active = imeVisible,
            ) {
                if (imeVisible) kb?.hide() else { focus.requestFocus(); kb?.show() }
            }
        }
        Spacer(Modifier.height(8.dp))
        KeyStrip(vm)
        Spacer(Modifier.height(8.dp))
        MediaStrip(vm)
        Spacer(Modifier.height(10.dp))

        KeyboardCapture(vm, focus)
    }
}

@Composable
private fun StatusRow(state: Link.State, vm: CompanionViewModel, onSettings: () -> Unit) {
    val (label, color) = when (state) {
        is Link.State.Idle -> "Not connected" to TextDim
        is Link.State.Connecting -> "Connecting…" to Accent
        is Link.State.Connected -> "Connected · ${state.host}" to Good
        is Link.State.Failed -> (state.reason + if (state.retrying) " · retrying" else "") to Bad
    }
    Row(
        Modifier.fillMaxWidth().padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(9.dp).clip(CircleShape).background(color))
        Spacer(Modifier.width(10.dp))
        Text(label, color = TextMain, fontSize = 14.sp, modifier = Modifier.weight(1f), maxLines = 1)
        val canRetry = state is Link.State.Idle || (state is Link.State.Failed && !state.retrying)
        if (canRetry) TextButton(onClick = { vm.connect() }) { Text("Retry", color = Accent) }
        TextButton(onClick = onSettings) { Text("Settings", color = TextDim) }
    }
}

@Composable
private fun Trackpad(vm: CompanionViewModel, connected: Boolean, modifier: Modifier) {
    val haptic = LocalHapticFeedback.current
    var touched by remember { mutableStateOf(false) }
    var everTouched by remember { mutableStateOf(false) }
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
                    everTouched = true

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
        if (!everTouched) {
            Text(
                "Drag to move\nTap to click · two fingers to scroll\nTwo-finger tap for right click · tap, then hold to drag",
                color = TextDim, fontSize = 13.sp, lineHeight = 20.sp,
                modifier = Modifier.padding(32.dp),
            )
        }
    }
}

@Composable
private fun HoldButton(label: String, button: String, vm: CompanionViewModel, modifier: Modifier) {
    var pressed by remember { mutableStateOf(false) }
    val haptic = LocalHapticFeedback.current
    val shape = RoundedCornerShape(16.dp)
    Box(
        modifier
            .height(56.dp)
            .clip(shape)
            .background(if (pressed) Hairline else Surface)
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
    onLongClick: (() -> Unit)? = null,
    onClick: () -> Unit,
) {
    val shape = RoundedCornerShape(14.dp)
    Box(
        modifier
            .clip(shape)
            .background(if (active) Accent else Surface)
            .border(1.dp, if (active) Accent else Hairline, shape)
            .combinedClickable(onClick = onClick, onLongClick = onLongClick)
            .padding(horizontal = hPad.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            label, color = if (active) Ink else TextMain,
            fontSize = 14.sp, fontWeight = FontWeight.Medium, maxLines = 1,
        )
    }
}

@Composable
private fun KeyStrip(vm: CompanionViewModel) {
    Row(
        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        val h = Modifier.height(44.dp)
        KeyChip("Esc", h) { vm.pressKey("esc") }
        KeyChip("Tab", h) { vm.pressKey("tab") }
        // modifiers are one-shot: tap to arm, then press the next key. Long-press taps the key alone.
        KeyChip("Ctrl", h, active = "ctrl" in vm.mods, onLongClick = { vm.tapModAlone("ctrl") }) { vm.toggleMod("ctrl") }
        KeyChip("Alt", h, active = "alt" in vm.mods, onLongClick = { vm.tapModAlone("alt") }) { vm.toggleMod("alt") }
        KeyChip("Shift", h, active = "shift" in vm.mods, onLongClick = { vm.tapModAlone("shift") }) { vm.toggleMod("shift") }
        KeyChip("Super", h, active = "super" in vm.mods, onLongClick = { vm.tapModAlone("super") }) { vm.toggleMod("super") }
        KeyChip("←", h) { vm.pressKey("left") }
        KeyChip("↓", h) { vm.pressKey("down") }
        KeyChip("↑", h) { vm.pressKey("up") }
        KeyChip("→", h) { vm.pressKey("right") }
        KeyChip("Del", h) { vm.pressKey("delete") }
        KeyChip("Home", h) { vm.pressKey("home") }
        KeyChip("End", h) { vm.pressKey("end") }
        KeyChip("PgUp", h) { vm.pressKey("pageup") }
        KeyChip("PgDn", h) { vm.pressKey("pagedown") }
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

// =============================================================================
// Hidden text field that turns the phone's soft keyboard into PC keystrokes.
// =============================================================================
private const val SENTINEL = "        " // 8 spaces so backspace always has something to delete

@Composable
private fun KeyboardCapture(vm: CompanionViewModel, focus: FocusRequester) {
    var value by remember { mutableStateOf(TextFieldValue(SENTINEL, TextRange(SENTINEL.length))) }
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
            // reset on word boundaries / when the buffer drifts so it never runs out of backspace room
            value = if (new.length < SENTINEL.length || new.length > 120 ||
                added.contains(' ') || added.contains('\n')
            ) TextFieldValue(SENTINEL, TextRange(SENTINEL.length)) else nv
        },
        modifier = Modifier.size(1.dp).alpha(0f).focusRequester(focus),
        keyboardOptions = KeyboardOptions(
            autoCorrectEnabled = false,
            keyboardType = KeyboardType.Text,
            imeAction = ImeAction.Default,
        ),
    )
}
