package uk.osianj.companion

import org.json.JSONObject
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/** One line of the PC's audit log (what the AI or a phone button did). */
data class AuditEntry(
    val ts: String,
    val tool: String,
    val summary: String,
    val approval: String,
    val result: String,
    val detail: String? = null,
)

data class MemoryItem(val id: String, val text: String, val created: String)

data class RoutineInfo(val name: String, val description: String, val risk: String?, val steps: List<String>)

/**
 * Pure state behind the Activity screen: the audit log, the AI's memory and the routines, as the PC sent them
 * (PROTOCOL.md "Activity, memory and routines"). `null` means "not loaded yet". JVM-testable.
 */
data class LibraryState(
    /** Newest first. */
    val audit: List<AuditEntry>? = null,
    val memory: List<MemoryItem>? = null,
    val memoryMax: Int = 100,
    val memoryMaxText: Int = 200,
    /** The PC's memory file has a syntax error: every edit would be refused. */
    val memoryBroken: Boolean = false,
    val routines: List<RoutineInfo>? = null,
    val memRid: Int = 0,
    val memRunning: Boolean = false,
    val memNote: String? = null,
    val memNoteOk: Boolean = true,
    val memNoteSeq: Int = 0,
) {
    fun onServer(m: JSONObject): LibraryState = when (m.optString("t")) {
        "audit" -> copy(audit = parseAudit(m))
        "memory" -> copy(
            memory = parseMemory(m),
            memoryMax = m.optInt("max", 100).coerceIn(1, 1000),
            memoryMaxText = m.optInt("max_text", 200).coerceIn(1, 2000),
            memoryBroken = m.optBoolean("broken", false),
        )
        "routines" -> copy(routines = parseRoutines(m))
        "memory_result" ->
            if (memRunning && m.optInt("rid", -1) == memRid)
                copy(memRunning = false, memNote = clip(m.optString("msg")).ifEmpty { if (m.optBoolean("ok")) "Saved" else "Failed" },
                    memNoteOk = m.optBoolean("ok"), memNoteSeq = memNoteSeq + 1)
            else this
        else -> this
    }

    /** The state after sending a memory change, and the request id to send with it. */
    fun startMemory(): Pair<LibraryState, Int> = copy(memRunning = true, memRid = memRid + 1, memNote = null) to (memRid + 1)

    fun memoryTimedOut(forRid: Int): LibraryState =
        if (memRunning && forRid == memRid) copy(memRunning = false, memNote = "No answer from the PC", memNoteOk = false, memNoteSeq = memNoteSeq + 1)
        else this

    fun disconnected(): LibraryState = if (memRunning) copy(memRunning = false) else this

    companion object {
        private const val MAX_ROWS = 300
        private fun clip(s: String, n: Int = 160) = s.replace(Regex("[\\u0000-\\u001f]"), " ").take(n).trim()

        fun parseAudit(m: JSONObject): List<AuditEntry> {
            val arr = m.optJSONArray("items") ?: return emptyList()
            val out = ArrayList<AuditEntry>()
            for (i in 0 until minOf(arr.length(), MAX_ROWS)) {
                val o = arr.optJSONObject(i) ?: continue
                val summary = clip(o.optString("summary"), 200)
                if (summary.isEmpty()) continue
                out += AuditEntry(
                    ts = o.optString("ts"), tool = clip(o.optString("tool"), 40), summary = summary,
                    approval = clip(o.optString("approval"), 30), result = clip(o.optString("result"), 20),
                    detail = clip(o.optString("detail"), 120).takeIf { it.isNotEmpty() },
                )
            }
            return out.reversed()    // the PC sends oldest first
        }

        fun parseMemory(m: JSONObject): List<MemoryItem> {
            val arr = m.optJSONArray("items") ?: return emptyList()
            val out = ArrayList<MemoryItem>()
            for (i in 0 until minOf(arr.length(), MAX_ROWS)) {
                val o = arr.optJSONObject(i) ?: continue
                val id = o.optString("id").trim()
                val text = o.optString("text").trim()
                if (id.isEmpty() || text.isEmpty()) continue
                out += MemoryItem(id, text.take(400), o.optString("created").take(20))
            }
            return out
        }

        fun parseRoutines(m: JSONObject): List<RoutineInfo> {
            val arr = m.optJSONArray("items") ?: return emptyList()
            val out = ArrayList<RoutineInfo>()
            for (i in 0 until minOf(arr.length(), 50)) {
                val o = arr.optJSONObject(i) ?: continue
                val name = o.optString("name").trim()
                if (name.isEmpty()) continue
                val steps = o.optJSONArray("steps")?.let { a -> (0 until minOf(a.length(), 30)).map { clip(a.optString(it), 120) }.filter { it.isNotEmpty() } } ?: emptyList()
                out += RoutineInfo(name.take(40), clip(o.optString("description"), 200), o.optString("risk").takeIf { it.isNotEmpty() && it != "null" }, steps)
            }
            return out
        }
    }
}

/** How the log says who approved a call. */
fun approvalLabel(approval: String, detail: String?): String = when (approval) {
    "auto" -> "Automatic"
    "allowed" -> "You allowed it"
    "denied" -> if (detail == "timeout") "Timed out" else "You said no"
    "timeout" -> "Timed out"
    "phone button" -> "Your tap"
    "phone" -> "From the app"
    else -> approval.replaceFirstChar { it.uppercase() }
}

/** "14:54" for a log timestamp, in `zone` (null if it can't be read). */
fun timeLabel(ts: String, zone: ZoneId = ZoneId.systemDefault()): String? =
    try { OffsetDateTime.parse(ts).atZoneSameInstant(zone).format(DateTimeFormatter.ofPattern("HH:mm", Locale.UK)) }
    catch (e: Exception) { null }

/** "Today", "Yesterday" or "26 Nov" for a log timestamp, relative to `now`. */
fun dayLabel(ts: String, now: OffsetDateTime = OffsetDateTime.now(), zone: ZoneId = ZoneId.systemDefault()): String? =
    try {
        val d = OffsetDateTime.parse(ts).atZoneSameInstant(zone).toLocalDate()
        val today = now.atZoneSameInstant(zone).toLocalDate()
        when (d) {
            today -> "Today"
            today.minusDays(1) -> "Yesterday"
            else -> d.format(DateTimeFormatter.ofPattern("d MMM", Locale.UK))
        }
    } catch (e: Exception) { null }
