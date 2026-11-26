package uk.osianj.companion

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.delay

/** One-tap PC actions (lock, sleep, log out, ...). The list comes from the PC, so it only shows what it can do. */
@Composable
fun ActionsScreen(vm: CompanionViewModel) {
    val state by vm.link.state.collectAsStateWithLifecycle()
    val caps by vm.link.caps.collectAsStateWithLifecycle()
    val connected = state is Link.State.Connected
    val a = vm.actions
    var asking by remember { mutableStateOf<QuickAction?>(null) }
    var shownNote by remember { mutableStateOf<String?>(null) }

    // the outcome line fades after a few seconds
    LaunchedEffect(a.noteSeq) {
        shownNote = a.note
        if (a.note != null) { delay(5000); shownNote = null }
    }

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 18.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        val note = shownNote
        // a fixed-height line, so the tiles don't jump when a note appears or fades
        Box(Modifier.fillMaxWidth().height(24.dp).padding(horizontal = 4.dp), contentAlignment = Alignment.CenterStart) {
            if (note != null) {
                Text(note, color = if (a.noteOk) Good else Bad, fontSize = 14.sp, maxLines = 1)
            } else if (!connected) {
                Text("Connect to your PC to use these.", color = TextDim, fontSize = 14.sp, maxLines = 1)
            } else if (a.items.isEmpty()) {
                Text(
                    if ("actions" in caps) "Loading…" else "This PC's daemon doesn't offer quick actions yet.",
                    color = TextDim, fontSize = 14.sp, maxLines = 1,
                )
            }
        }

        for ((group, items) in a.groups) {
            Text(
                group.uppercase(), color = TextDim, fontSize = 12.sp, letterSpacing = 1.2.sp,
                modifier = Modifier.padding(start = 4.dp, top = 8.dp),
            )
            for (row in items.chunked(2)) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    for (item in row) {
                        Tile(
                            item, enabled = connected && a.running == null, busy = a.running == item.id,
                            modifier = Modifier.weight(1f),
                        ) { if (item.confirm != null) asking = item else vm.runAction(item) }
                    }
                    if (row.size == 1) Spacer(Modifier.weight(1f))
                }
            }
        }
        Spacer(Modifier.height(24.dp))
    }

    val ask = asking
    if (ask != null) {
        AlertDialog(
            onDismissRequest = { asking = null },
            containerColor = Panel,
            title = { Text(ask.label, color = TextMain, fontWeight = FontWeight.SemiBold) },
            text = { Text(ask.confirm ?: "", color = TextDim, fontSize = 15.sp) },
            confirmButton = {
                TextButton(onClick = { asking = null; vm.runAction(ask) }) {
                    Text(ask.label, color = if (ask.danger) Bad else Accent, fontWeight = FontWeight.SemiBold)
                }
            },
            dismissButton = { TextButton(onClick = { asking = null }) { Text("Cancel", color = TextDim) } },
        )
    }
}

@Composable
private fun Tile(item: QuickAction, enabled: Boolean, busy: Boolean, modifier: Modifier, onClick: () -> Unit) {
    val tint = if (item.danger) Bad else TextMain
    Box(
        modifier
            .height(72.dp)
            .alpha(if (enabled || busy) 1f else 0.45f)
            .clip(RoundedCornerShape(16.dp))
            .background(Panel)
            .border(BorderStroke(1.dp, if (busy) Accent else Hairline), RoundedCornerShape(16.dp))
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 14.dp),
        contentAlignment = Alignment.CenterStart,
    ) {
        Text(
            if (busy) item.label + "…" else item.label, color = tint, fontSize = 16.sp,
            fontWeight = FontWeight.Medium, maxLines = 2,
        )
    }
}
