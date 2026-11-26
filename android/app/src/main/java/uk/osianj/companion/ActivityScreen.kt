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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.delay

private enum class Tab(val label: String, val cap: String) {
    Log("Log", "audit"), Memory("Memory", "memory"), Routines("Routines", "routines")
}

/** What Sentri did (audit log), what it remembers (editable) and the routines it can run. */
@Composable
fun ActivityScreen(vm: CompanionViewModel) {
    val state by vm.link.state.collectAsStateWithLifecycle()
    val caps by vm.link.caps.collectAsStateWithLifecycle()
    val connected = state is Link.State.Connected
    val tabs = Tab.entries.filter { it.cap in caps }
    var picked by remember { mutableStateOf(Tab.Log) }
    val current = picked.takeIf { it in tabs } ?: tabs.firstOrNull()

    // load (or reload) whatever tab is showing whenever we are connected
    LaunchedEffect(connected, current) {
        if (connected) when (current) {
            Tab.Log -> vm.refreshLog()
            Tab.Memory -> vm.refreshMemory()
            Tab.Routines -> vm.refreshRoutines()
            null -> {}
        }
    }

    Column(Modifier.fillMaxSize()) {
        if (current == null) {
            Text(
                if (connected) "This PC's daemon doesn't offer these yet. Update and restart it." else "Connect to your PC to see this.",
                color = TextDim, fontSize = 14.sp, modifier = Modifier.padding(22.dp),
            )
            return
        }
        Row(Modifier.padding(horizontal = 18.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            for (t in tabs) Chip(t.label, t == current) { picked = t }
        }
        if (!connected) Text("Not connected: showing what was loaded last.", color = TextDim, fontSize = 12.sp,
            modifier = Modifier.padding(horizontal = 22.dp, vertical = 2.dp))
        when (current) {
            Tab.Log -> LogTab(vm)
            Tab.Memory -> MemoryTab(vm, connected)
            Tab.Routines -> RoutinesTab(vm, connected)
        }
    }
}

@Composable
private fun Chip(label: String, selected: Boolean, onClick: () -> Unit) {
    Box(
        Modifier.clip(RoundedCornerShape(50)).background(if (selected) Accent else Panel)
            .border(BorderStroke(1.dp, if (selected) Accent else Hairline), RoundedCornerShape(50))
            .clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 8.dp),
    ) {
        Text(label, color = if (selected) Ink else TextDim, fontSize = 14.sp, fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal)
    }
}

/** A one-line outcome that fades after a few seconds; fixed height so nothing below it jumps. */
@Composable
private fun FadingNote(seq: Int, note: String?, ok: Boolean) {
    var shown by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(seq) {
        shown = note
        if (note != null) { delay(5000); shown = null }
    }
    Box(Modifier.fillMaxWidth().height(24.dp).padding(horizontal = 22.dp), contentAlignment = Alignment.CenterStart) {
        shown?.let { Text(it, color = if (ok) Good else Bad, fontSize = 14.sp, maxLines = 1) }
    }
}

// ---- Log ---------------------------------------------------------------

private sealed interface LogRow {
    data class Day(val label: String) : LogRow
    data class Entry(val e: AuditEntry) : LogRow
}

@Composable
private fun LogTab(vm: CompanionViewModel) {
    val audit = vm.library.audit
    Row(Modifier.fillMaxWidth().padding(horizontal = 22.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(
            when { audit == null -> "Loading…"; audit.isEmpty() -> "Nothing yet"; else -> "Last ${audit.size} actions" },
            color = TextDim, fontSize = 13.sp, modifier = Modifier.weight(1f),
        )
        TextButton(onClick = { vm.refreshLog() }) { Text("Refresh", color = Accent) }
    }
    if (audit == null || audit.isEmpty()) return
    val rows = remember(audit) {
        val out = ArrayList<LogRow>()
        var last: String? = null
        for (e in audit) {
            val day = dayLabel(e.ts)
            if (day != null && day != last) { out += LogRow.Day(day); last = day }
            out += LogRow.Entry(e)
        }
        out
    }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 18.dp, vertical = 4.dp)) {
        items(rows) { r ->
            when (r) {
                is LogRow.Day -> Text(r.label.uppercase(), color = TextDim, fontSize = 12.sp, letterSpacing = 1.2.sp,
                    modifier = Modifier.padding(start = 4.dp, top = 14.dp, bottom = 4.dp))
                is LogRow.Entry -> LogEntryRow(r.e)
            }
        }
    }
}

@Composable
private fun LogEntryRow(e: AuditEntry) {
    val failed = e.result == "error"
    val sub = buildString {
        append(e.tool.replace('_', ' '))
        append(" · "); append(approvalLabel(e.approval, e.detail))
        if (failed) append(" · failed" + (e.detail?.let { ": $it" } ?: ""))
        else if (e.result == "not run") append(" · not run")
    }
    Row(Modifier.fillMaxWidth().padding(vertical = 6.dp, horizontal = 4.dp)) {
        Text(timeLabel(e.ts) ?: "", color = TextDim, fontSize = 12.sp, modifier = Modifier.width(46.dp).padding(top = 2.dp))
        Column(Modifier.weight(1f)) {
            Text(e.summary, color = TextMain, fontSize = 14.sp, maxLines = 3)
            Text(sub, color = if (failed) Bad else TextDim, fontSize = 12.sp, maxLines = 2)
        }
    }
}

// ---- Memory ------------------------------------------------------------

private data class MemEdit(val id: String?, val text: String)

@Composable
private fun MemoryTab(vm: CompanionViewModel, connected: Boolean) {
    val lib = vm.library
    val items = lib.memory
    var editing by remember { mutableStateOf<MemEdit?>(null) }
    var closeOnOk by remember { mutableStateOf(false) }

    // a successful save closes the dialog; a refusal keeps it open with the reason
    LaunchedEffect(lib.memNoteSeq) {
        if (closeOnOk) { if (lib.memNoteOk) editing = null; closeOnOk = false }
    }

    Row(Modifier.fillMaxWidth().padding(horizontal = 22.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(
            if (items == null) "Loading…" else "${items.size} of ${lib.memoryMax}",
            color = TextDim, fontSize = 13.sp, modifier = Modifier.weight(1f),
        )
        TextButton(enabled = connected && items != null && !lib.memoryBroken, onClick = { editing = MemEdit(null, "") }) {
            Text("Add", color = Accent, fontWeight = FontWeight.SemiBold)
        }
    }
    Text("Changes apply from your next conversation with Sentri.", color = TextDim, fontSize = 12.sp,
        modifier = Modifier.padding(horizontal = 22.dp))
    if (lib.memoryBroken) {
        Text("The memory file on your PC has a syntax error, so edits are off. Fix it there.", color = Bad, fontSize = 13.sp,
            modifier = Modifier.padding(horizontal = 22.dp, vertical = 6.dp))
    }
    // a refusal is shown inside the open dialog instead; successes show here even as the dialog closes
    FadingNote(lib.memNoteSeq, lib.memNote.takeIf { lib.memNoteOk || editing == null }, lib.memNoteOk)

    if (items != null) {
        if (items.isEmpty()) Text("Nothing remembered yet. Ask Sentri to remember something, or add it here.", color = TextDim,
            fontSize = 14.sp, modifier = Modifier.padding(horizontal = 22.dp, vertical = 8.dp))
        LazyColumn(Modifier.fillMaxSize(), contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 18.dp, vertical = 4.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(items, key = { it.id }) { m ->
                Column(
                    Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(Panel)
                        .border(BorderStroke(1.dp, Hairline), RoundedCornerShape(14.dp))
                        .clickable(enabled = connected && !lib.memoryBroken) { editing = MemEdit(m.id, m.text) }
                        .padding(14.dp),
                ) {
                    Text(m.text, color = TextMain, fontSize = 15.sp)
                    if (m.created.isNotEmpty()) Text("Saved ${m.created}", color = TextDim, fontSize = 12.sp, modifier = Modifier.padding(top = 4.dp))
                }
            }
        }
    }

    editing?.let { ed ->
        MemoryDialog(
            ed, lib, onDismiss = { editing = null },
            onSave = { text -> closeOnOk = true; vm.changeMemory(ed.id, text) },
            onForget = { closeOnOk = true; vm.changeMemory(ed.id, null) },
        )
    }
}

@Composable
private fun MemoryDialog(ed: MemEdit, lib: LibraryState, onDismiss: () -> Unit, onSave: (String) -> Unit, onForget: () -> Unit) {
    var text by remember { mutableStateOf(ed.text) }
    var confirmForget by remember { mutableStateOf(false) }
    val clean = text.trim()
    val tooLong = clean.length > lib.memoryMaxText
    val canSave = clean.isNotEmpty() && !tooLong && clean != ed.text.trim() && !lib.memRunning
    AlertDialog(
        onDismissRequest = { if (!lib.memRunning) onDismiss() },
        containerColor = Panel,
        title = { Text(if (confirmForget) "Forget this?" else if (ed.id == null) "Remember something" else "Edit memory",
            color = TextMain, fontWeight = FontWeight.SemiBold) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (confirmForget) {
                    Text(ed.text, color = TextDim, fontSize = 15.sp)
                } else {
                    OutlinedTextField(
                        value = text, onValueChange = { text = it }, modifier = Modifier.fillMaxWidth(), minLines = 2, maxLines = 5,
                        isError = tooLong, placeholder = { Text("e.g. My main browser is Vivaldi") },
                        supportingText = { Text("${clean.length} / ${lib.memoryMaxText}") },
                    )
                    Text("No passwords, keys or other secrets: Sentri refuses to keep them.", color = TextDim, fontSize = 12.sp)
                    if (!lib.memNoteOk && lib.memNote != null && !lib.memRunning) Text(lib.memNote, color = Bad, fontSize = 13.sp)
                }
            }
        },
        confirmButton = {
            if (confirmForget) TextButton(enabled = !lib.memRunning, onClick = onForget) { Text("Forget", color = Bad, fontWeight = FontWeight.SemiBold) }
            else TextButton(enabled = canSave, onClick = { onSave(clean) }) {
                Text(if (lib.memRunning) "Saving…" else "Save", color = if (canSave) Accent else TextDim, fontWeight = FontWeight.SemiBold)
            }
        },
        dismissButton = {
            Row {
                if (!confirmForget && ed.id != null) TextButton(enabled = !lib.memRunning, onClick = { confirmForget = true }) { Text("Forget", color = Bad) }
                TextButton(enabled = !lib.memRunning, onClick = { if (confirmForget) confirmForget = false else onDismiss() }) {
                    Text(if (confirmForget) "Keep" else "Cancel", color = TextDim)
                }
            }
        },
    )
}

// ---- Routines ----------------------------------------------------------

@Composable
private fun RoutinesTab(vm: CompanionViewModel, connected: Boolean) {
    val routines = vm.library.routines
    var asking by remember { mutableStateOf<QuickAction?>(null) }
    FadingNote(vm.actions.noteSeq, vm.actions.note, vm.actions.noteOk)
    if (routines == null) { Text("Loading…", color = TextDim, fontSize = 13.sp, modifier = Modifier.padding(horizontal = 22.dp)); return }
    if (routines.isEmpty()) {
        Text("No routines set up. They are defined in your PC's ai.toml.", color = TextDim, fontSize = 14.sp, modifier = Modifier.padding(horizontal = 22.dp))
        return
    }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 18.dp, vertical = 4.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        items(routines, key = { it.name }) { r ->
            val action = vm.actions.items.firstOrNull { it.id == "routine:${r.name}" }
            Column(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(Panel)
                    .border(BorderStroke(1.dp, Hairline), RoundedCornerShape(14.dp)).padding(14.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(r.name.replace('_', ' ').replaceFirstChar { it.uppercase() }, color = TextMain, fontSize = 16.sp,
                        fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                    if (r.risk != null) Text("asks first", color = if (r.risk == "high") Bad else Accent, fontSize = 12.sp, modifier = Modifier.padding(end = 8.dp))
                    TextButton(
                        enabled = connected && action != null && vm.actions.running == null,
                        onClick = { if (action?.confirm != null) asking = action else if (action != null) vm.runAction(action) },
                    ) { Text(if (vm.actions.running == action?.id && action != null) "Running…" else "Run", color = Accent, fontWeight = FontWeight.SemiBold) }
                }
                if (r.description.isNotEmpty()) Text(r.description, color = TextDim, fontSize = 13.sp, modifier = Modifier.padding(top = 2.dp))
                Spacer(Modifier.height(6.dp))
                for (s in r.steps) Text("•  $s", color = TextMain, fontSize = 14.sp, modifier = Modifier.padding(vertical = 1.dp))
            }
        }
    }
    asking?.let { ask ->
        AlertDialog(
            onDismissRequest = { asking = null }, containerColor = Panel,
            title = { Text(ask.label, color = TextMain, fontWeight = FontWeight.SemiBold) },
            text = { Text(ask.confirm ?: "", color = TextDim, fontSize = 15.sp) },
            confirmButton = { TextButton(onClick = { asking = null; vm.runAction(ask) }) { Text("Run", color = Accent, fontWeight = FontWeight.SemiBold) } },
            dismissButton = { TextButton(onClick = { asking = null }) { Text("Cancel", color = TextDim) } },
        )
    }
}
