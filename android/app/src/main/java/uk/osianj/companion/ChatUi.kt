package uk.osianj.companion

import androidx.compose.foundation.background
import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.border
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import kotlinx.coroutines.delay
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Transcript + input, shown under the character once the daemon announces the "chat" capability. */
@Composable
fun ChatPanel(vm: CompanionViewModel, enabled: Boolean, modifier: Modifier = Modifier) {
    val chat = vm.chat
    val busy = chat.activeTurn != null

    Column(modifier.fillMaxWidth()) {
        if (chat.items.isNotEmpty()) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                TextButton(onClick = { vm.clearChat() }) {
                    Text("Clear", color = TextDim, fontSize = 12.sp)
                }
            }
            val listState = rememberLazyListState()
            val reversed = remember(chat.items) { chat.items.asReversed() }
            // newest at the bottom: the list is reversed, so index 0 is the bottom. Follow new messages,
            // but don't yank the view down if you've scrolled up to read something older.
            LaunchedEffect(chat.items) {
                if (listState.firstVisibleItemIndex <= 1 || chat.items.lastOrNull() is UserMsg) listState.scrollToItem(0)
            }
            val olderAbove by remember { derivedStateOf { listState.canScrollForward } }
            // the transcript takes whatever height the screen gives it, with a soft fade at the top edge
            Box(Modifier.weight(1f).fillMaxWidth()) {
                LazyColumn(
                    state = listState,
                    reverseLayout = true,
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                    modifier = Modifier.fillMaxSize(),
                ) {
                    items(reversed, key = { it.key }) { ChatRow(it, vm) }
                }
                if (olderAbove) Box(
                    Modifier
                        .align(Alignment.TopCenter)
                        .fillMaxWidth()
                        .height(28.dp)
                        .background(Brush.verticalGradient(listOf(Ink, Color.Transparent))),
                )
            }
        } else {
            Text(
                if (enabled) "Ask me to open something, change the volume, or just chat."
                else "Waiting for your PC…",
                color = TextDim, fontSize = 13.sp, textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth(),
            )
        }
        Spacer(Modifier.height(10.dp))
        ChatInput(vm, enabled, busy)
    }
}

@Composable
private fun ChatRow(item: ChatItem, vm: CompanionViewModel) {
    when (item) {
        is UserMsg -> Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.End) {
            Bubble(item.text, user = true)
            if (item.pending) Text(
                "Reconnecting\u2026", color = TextDim, fontSize = 11.sp,
                modifier = Modifier.padding(top = 3.dp, end = 6.dp),
            )
        }
        is AiMsg -> Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Start) {
            Bubble(item.text, user = false)
        }
        is ToolItem -> ToolLine(item)
        is ConfirmItem -> ConfirmCard(item, vm)
        is ErrorItem -> Text(
            item.text, color = Bad, fontSize = 13.sp,
            modifier = Modifier
                .fillMaxWidth()
                .then(if (item.retry != null) Modifier.clickable { vm.retryChat(item.key) } else Modifier)
                .padding(horizontal = 6.dp, vertical = if (item.retry != null) 8.dp else 0.dp),
        )
    }
}

@Composable
private fun Bubble(text: String, user: Boolean) {
    val shape = RoundedCornerShape(18.dp)
    Box(
        Modifier
            .widthIn(max = 300.dp)
            .clip(shape)
            .background(if (user) Accent.copy(alpha = 0.16f) else Panel)
            .border(1.dp, if (user) Accent.copy(alpha = 0.4f) else Hairline, shape)
            .padding(horizontal = 14.dp, vertical = 9.dp),
    ) {
        Text(text, color = TextMain, fontSize = 15.sp, lineHeight = 21.sp)
    }
}

@Composable
private fun ToolLine(t: ToolItem) {
    val color = when (t.state) {
        "ok" -> Good
        "error" -> Bad
        else -> Accent
    }
    Row(
        Modifier.fillMaxWidth().padding(start = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(7.dp).clip(CircleShape).background(color))
        Spacer(Modifier.width(8.dp))
        Text(
            toolLabel(t) + if (t.detail.isNotEmpty()) " · ${t.detail}" else "",
            color = TextDim, fontSize = 12.sp,
        )
    }
}

@Composable
private fun ConfirmCard(c: ConfirmItem, vm: CompanionViewModel) {
    val high = c.risk == "high"
    if (c.answer != Answer.Pending) {
        // answered: shrink to one quiet line. For Allowed the tool line that follows already names the action.
        val (mark, label, color) = when (c.answer) {
            Answer.Allowed -> Triple("\u2713", "Allowed", Good)
            Answer.Denied -> Triple("\u2715", "Denied", TextDim)
            else -> Triple("\u2013", "Expired, nothing was done", TextDim)
        }
        Row(
            Modifier.fillMaxWidth().padding(start = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(mark, color = color, fontSize = 13.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.width(8.dp))
            Text(
                if (c.answer == Answer.Allowed) label else "$label \u00B7 ${c.summary}",
                color = color, fontSize = 12.sp, maxLines = 2,
            )
        }
        return
    }
    val edge = if (high) Bad else Accent
    val shape = RoundedCornerShape(16.dp)
    Column(
        Modifier
            .fillMaxWidth()
            .clip(shape)
            .background(Panel)
            .border(1.dp, edge.copy(alpha = 0.7f), shape)
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(
            if (high) "NEEDS APPROVAL \u00B7 SENSITIVE" else "NEEDS APPROVAL",
            color = edge, fontSize = 11.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.sp,
        )
        Text(c.summary, color = TextMain, fontSize = 15.sp, lineHeight = 21.sp)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ActionButton("Deny", filled = false, Modifier.weight(1f)) { vm.answerConfirm(c.call, false) }
            ActionButton("Allow", filled = true, Modifier.weight(1f)) { vm.answerConfirm(c.call, true) }
        }
        Text("Denied automatically after ${c.timeout} s", color = TextDim, fontSize = 11.sp)
    }
}

@Composable
private fun ActionButton(label: String, filled: Boolean, modifier: Modifier, onClick: () -> Unit) {
    val shape = RoundedCornerShape(12.dp)
    Box(
        modifier
            .height(44.dp)
            .clip(shape)
            .background(if (filled) Accent else Panel)
            .border(1.dp, if (filled) Accent else Hairline, shape)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(label, color = if (filled) Ink else TextMain, fontSize = 15.sp, fontWeight = FontWeight.SemiBold)
    }
}

@Composable
private fun ChatInput(vm: CompanionViewModel, enabled: Boolean, busy: Boolean) {
    var text by remember { mutableStateOf("") }
    var partial by remember { mutableStateOf("") }
    var hint by remember { mutableStateOf<String?>(null) }
    val shape = RoundedCornerShape(24.dp)
    val ctx = LocalContext.current
    val canSend by rememberUpdatedState(enabled)

    val voice = remember {
        VoiceController(
            ctx,
            onPartial = { partial = it },
            onFinal = { heard ->
                partial = ""
                // spoken text is sent straight away; approval cards still guard anything risky
                if (!(canSend && vm.sendChat(heard))) text = heard // couldn't send now: leave it in the box
            },
            onError = { partial = ""; hint = it },
            onListening = { vm.listening = it; if (!it) partial = "" },
        )
    }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    DisposableEffect(lifecycle) {
        val obs = LifecycleEventObserver { _, ev -> if (ev == Lifecycle.Event.ON_STOP) voice.cancel() }
        lifecycle.addObserver(obs)
        onDispose { lifecycle.removeObserver(obs); voice.destroy() }
    }
    LaunchedEffect(hint) { if (hint != null) { delay(3500); hint = null } }
    val askMic = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        if (ok) voice.start() else hint = "Microphone permission is off"
    }
    fun startVoice() {
        val granted = ContextCompat.checkSelfPermission(ctx, Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED
        if (granted) voice.start() else askMic.launch(Manifest.permission.RECORD_AUDIO)
    }

    fun send() {
        val t = text.trim()
        if (t.isNotEmpty() && enabled && !busy) {
            vm.sendChat(t)
            text = ""
        }
    }
    val listening = voice.listening
    val micAvailable = remember { voice.available } // a system query: ask once, not on every keystroke
    val micMode = text.isBlank() && !busy && micAvailable
    Row(
        Modifier.fillMaxWidth().alpha(if (enabled) 1f else 0.5f),
        verticalAlignment = Alignment.Bottom,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        BasicTextField(
            value = if (listening) partial else text,
            onValueChange = { if (!listening) text = it },
            enabled = enabled && !listening,
            maxLines = 4,
            textStyle = TextStyle(color = TextMain, fontSize = 16.sp),
            cursorBrush = SolidColor(Accent),
            keyboardOptions = KeyboardOptions(
                capitalization = KeyboardCapitalization.Sentences,
                imeAction = ImeAction.Send,
            ),
            keyboardActions = KeyboardActions(onSend = { send() }),
            modifier = Modifier
                .weight(1f)
                .heightIn(min = 48.dp)
                .clip(shape)
                .background(Panel)
                .border(1.dp, if (listening) Accent else Hairline, shape)
                .padding(horizontal = 18.dp, vertical = 13.dp),
            decorationBox = { inner ->
                Box {
                    val empty = if (listening) partial.isEmpty() else text.isEmpty()
                    if (empty) {
                        Text(
                            when {
                                listening -> "Listening…"
                                hint != null -> hint!!
                                else -> "Ask me anything…"
                            },
                            color = if (hint != null && !listening) Bad else TextDim, fontSize = 16.sp,
                        )
                    }
                    inner()
                }
            },
        )
        val ring = if (listening) voice.level else 0f
        Box(
            Modifier
                .size(48.dp)
                .drawBehind {
                    if (listening) {
                        drawCircle(Accent.copy(alpha = 0.25f), radius = size.minDimension / 2f + 10.dp.toPx() * ring)
                    }
                }
                .clip(CircleShape)
                .background(if (busy) Panel else Accent)
                .border(1.dp, if (busy) Hairline else Accent, CircleShape)
                .clickable(enabled = enabled) {
                    when {
                        busy -> vm.stopChat()
                        listening -> voice.stop()
                        micMode -> startVoice()
                        else -> send()
                    }
                },
            contentAlignment = Alignment.Center,
        ) {
            when {
                busy -> Text("\u25A0", color = TextMain, fontSize = 20.sp, fontWeight = FontWeight.Bold)
                listening -> Text("\u25A0", color = Ink, fontSize = 20.sp, fontWeight = FontWeight.Bold)
                micMode -> MicIcon(Ink)
                else -> Text("\u2191", color = Ink, fontSize = 20.sp, fontWeight = FontWeight.Bold)
            }
        }
    }
}

/** A small microphone drawn with paths, so it doesn't depend on an icon pack or font. */
@Composable
private fun MicIcon(color: Color) {
    Canvas(Modifier.size(22.dp)) {
        val w = size.width
        val h = size.height
        val capW = w * 0.34f
        val capH = h * 0.52f
        drawRoundRect(
            color, Offset((w - capW) / 2f, h * 0.06f), Size(capW, capH),
            CornerRadius(capW / 2f, capW / 2f),
        )
        val stroke = Stroke(width = w * 0.09f, cap = StrokeCap.Round)
        drawArc(
            color, 0f, 180f, false,
            Offset(w * 0.22f, h * 0.22f), Size(w * 0.56f, h * 0.48f), style = stroke,
        )
        drawLine(color, Offset(w / 2f, h * 0.70f), Offset(w / 2f, h * 0.90f), strokeWidth = w * 0.09f, cap = StrokeCap.Round)
        drawLine(color, Offset(w * 0.36f, h * 0.92f), Offset(w * 0.64f, h * 0.92f), strokeWidth = w * 0.09f, cap = StrokeCap.Round)
    }
}
