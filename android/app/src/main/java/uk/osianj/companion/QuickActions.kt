package uk.osianj.companion

import org.json.JSONObject

/** One tile on the Quick actions screen, as the PC described it (PROTOCOL.md, "Quick actions"). */
data class QuickAction(
    val id: String,
    val label: String,
    val group: String,
    /** Text of the dialog the phone must show first; the PC refuses the action unless it is sent `confirmed`. */
    val confirm: String? = null,
    val danger: Boolean = false,
)

/**
 * Pure state for the Quick actions screen: the list the PC offered, which action is waiting for its
 * result, and the one-line outcome. JVM-testable; the ViewModel owns the timers and the socket.
 */
data class ActionsState(
    val items: List<QuickAction> = emptyList(),
    /** Id of the action that was sent and has no result yet. */
    val running: String? = null,
    /** Last request id handed out (echoed by the PC in `action_result`). */
    val rid: Int = 0,
    val note: String? = null,
    val noteOk: Boolean = true,
    /** Bumped for every new note, so the UI can fade it out per note. */
    val noteSeq: Int = 0,
) {
    /** Sections in the order the PC listed them. */
    val groups: List<Pair<String, List<QuickAction>>> get() = items.groupBy { it.group }.toList()

    /** The state after sending `item`, and the request id to send with it. */
    fun start(item: QuickAction): Pair<ActionsState, Int> =
        copy(running = item.id, rid = rid + 1, note = null) to (rid + 1)

    fun onServer(m: JSONObject): ActionsState = when (m.optString("t")) {
        "actions" -> copy(items = parseActions(m))
        "action_result" ->
            if (running != null && m.optInt("rid", -1) == rid)
                copy(running = null, note = clip(m.optString("msg")).ifEmpty { if (m.optBoolean("ok")) "Done" else "Failed" },
                    noteOk = m.optBoolean("ok"), noteSeq = noteSeq + 1)
            else this     // a late or unrelated result: ignore
        else -> this
    }

    /** No answer arrived for request `forRid` in time. */
    fun timedOut(forRid: Int): ActionsState =
        if (running != null && forRid == rid) copy(running = null, note = "No answer from the PC", noteOk = false, noteSeq = noteSeq + 1)
        else this

    /** The link dropped: nothing is waiting any more (the PC may still have acted). */
    fun disconnected(): ActionsState = if (running != null) copy(running = null) else this

    companion object {
        private const val MAX_ITEMS = 40
        private fun clip(s: String) = s.replace(Regex("[\\u0000-\\u001f]"), " ").take(160).trim()

        fun parseActions(m: JSONObject): List<QuickAction> {
            val arr = m.optJSONArray("items") ?: return emptyList()
            val out = ArrayList<QuickAction>()
            for (i in 0 until minOf(arr.length(), MAX_ITEMS)) {
                val o = arr.optJSONObject(i) ?: continue
                val id = o.optString("id").trim()
                val label = o.optString("label").trim()
                if (id.isEmpty() || label.isEmpty() || id.length > 60) continue
                out += QuickAction(
                    id = id, label = label.take(40),
                    group = o.optString("group").trim().ifEmpty { "Actions" }.take(30),
                    confirm = o.optString("confirm").trim().takeIf { it.isNotEmpty() }?.take(300),
                    danger = o.optBoolean("danger", false),
                )
            }
            return out
        }
    }
}
