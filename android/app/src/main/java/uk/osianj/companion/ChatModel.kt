package uk.osianj.companion

import org.json.JSONObject

// Pure state for the chat transcript. No Android/Compose types here so it is unit-testable on the JVM.

sealed interface ChatItem { val key: Long }

/**
 * [turn] is the chat turn this message started. [pending] is true while it hasn't left the phone yet
 * (waiting for the connection to come back).
 */
data class UserMsg(override val key: Long, val text: String, val turn: Int = 0, val pending: Boolean = false) : ChatItem
data class AiMsg(override val key: Long, val text: String) : ChatItem
data class ToolItem(
    override val key: Long,
    val call: String,
    val name: String,
    val summary: String,
    val state: String,   // running | ok | error
    val detail: String,
) : ChatItem

enum class Answer { Pending, Allowed, Denied, Expired }

data class ConfirmItem(
    override val key: Long,
    val call: String,
    val summary: String,
    val risk: String,    // low | high
    val timeout: Int,
    val answer: Answer,
) : ChatItem

/** A problem line. If [retry] is set, tapping it sends that text again. */
data class ErrorItem(override val key: Long, val text: String, val retry: String? = null) : ChatItem

data class ChatState(
    val items: List<ChatItem> = emptyList(),
    val activeTurn: Int? = null,
    val nextKey: Long = 1,
    val doneCount: Int = 0,      // bumps on every finished turn (drives the happy blip)
    val confirmCount: Int = 0,   // bumps on every approval request (drives the surprised blip)
    val errorCount: Int = 0,     // bumps whenever a turn fails (drives the confused blip)
    val mood: String? = null,    // the AI's chosen expression for the current/last turn (lowercase Expr name)
    val moodCount: Int = 0,      // bumps whenever a mood arrives
    val todayUsd: Double? = null,   // AI spend today, if the daemon reports it
    val budgetUsd: Double? = null,  // daily budget, if the daemon reports it
    val activity: Int = 0,       // events heard from the PC for the current turn (0 = nothing yet, not even a tool)
) {
    /** The AI is typing its answer right now (as opposed to waiting for the first words or a tool). */
    val streaming: Boolean get() = activeTurn != null && items.lastOrNull() is AiMsg

    /** An approval card is waiting for the user. */
    val pendingApproval: Boolean get() = items.any { it is ConfirmItem && it.answer == Answer.Pending }

    /** The AI hasn't produced anything yet and a message hasn't left the phone: still waiting for the connection. */
    val awaitingDelivery: Boolean
        get() = activeTurn != null && items.any { it is UserMsg && it.turn == activeTurn && it.pending }

    fun userSent(id: Int, text: String): ChatState =
        copy(
            items = items + UserMsg(nextKey, text, turn = id), activeTurn = id, nextKey = nextKey + 1,
            mood = null, activity = 0,
        )

    /** Mark a turn's message as waiting for the connection (true) or as on its way (false). */
    fun setPending(turn: Int, pending: Boolean): ChatState {
        if (items.none { it is UserMsg && it.turn == turn && it.pending != pending }) return this
        return copy(items = items.map { if (it is UserMsg && it.turn == turn) it.copy(pending = pending) else it })
    }

    /** The message never reached the PC (couldn't reconnect, or the user stopped it first). */
    fun undelivered(turn: Int, why: String): ChatState = failedWithRetry(turn, why)

    /** The message was sent but nothing came back. */
    fun noAnswer(turn: Int): ChatState = failedWithRetry(turn, "No answer from the PC")

    /**
     * The user tapped a "tap to resend" line. Returns the state without that line (and without the message
     * it belonged to, if nothing else happened in between, so it isn't shown twice) plus the text to send.
     */
    fun takeRetry(errorKey: Long): Pair<ChatState, String>? {
        val i = items.indexOfFirst { it is ErrorItem && it.key == errorKey && it.retry != null }
        if (i < 0 || activeTurn != null) return null
        val text = (items[i] as ErrorItem).retry!!
        val prev = items.getOrNull(i - 1)
        val drop = if (prev is UserMsg && prev.text == text) setOf(i - 1, i) else setOf(i)
        return copy(items = items.filterIndexed { idx, _ -> idx !in drop }) to text
    }

    /** Apply one daemon -> phone message. Events for a turn we aren't running (e.g. after Clear) are dropped. */
    fun onServer(m: JSONObject): ChatState {
        if (m.optInt("id", -1) != activeTurn) return this
        val s = copy(activity = activity + 1) // any event proves the PC got the message and is working on it
        return when (m.optString("t")) {
            "chat_delta" -> s.delta(m.optString("text"))
            "chat_mood" -> m.optString("mood").lowercase().takeIf { it.isNotEmpty() }
                ?.let { s.copy(mood = it, moodCount = moodCount + 1) } ?: s
            "tool" -> s.tool(m)
            "confirm_req" -> s.confirmReq(m)
            "chat_done" -> s.copy(
                items = expirePending(items), activeTurn = null, doneCount = doneCount + 1,
                todayUsd = m.optDouble("today_usd").takeIf { !it.isNaN() } ?: todayUsd,
                budgetUsd = m.optDouble("budget_usd").takeIf { !it.isNaN() } ?: budgetUsd,
            )
            "chat_error" -> s.failed(m.optString("msg").ifEmpty { "Something went wrong" })
            else -> this
        }
    }

    /** The user tapped Allow/Deny. Updates the card immediately; the daemon's tool event confirms it. */
    fun answered(call: String, allow: Boolean): ChatState = copy(
        items = items.map {
            if (it is ConfirmItem && it.call == call && it.answer == Answer.Pending)
                it.copy(answer = if (allow) Answer.Allowed else Answer.Denied) else it
        }
    )

    /** The socket dropped. A running turn can't continue; pending approvals are void. */
    fun disconnected(): ChatState {
        val turn = activeTurn
        val hasPending = items.any { it is ConfirmItem && it.answer == Answer.Pending }
        if (turn == null && !hasPending) return this
        if (turn == null) return copy(items = expirePending(items))
        if (awaitingDelivery) return this // it never left the phone, so the sender decides what happens to it
        return failedWithRetry(turn, "Connection lost")
    }

    private fun failedWithRetry(turn: Int, why: String): ChatState {
        if (activeTurn != turn) return this
        val text = items.lastOrNull { it is UserMsg && it.turn == turn }?.let { (it as UserMsg).text }
        val settled = items.map { if (it is UserMsg && it.turn == turn) it.copy(pending = false) else it }
        return copy(
            items = expirePending(settled) +
                ErrorItem(nextKey, if (text != null) "$why \u00B7 tap to resend" else why, retry = text),
            activeTurn = null,
            nextKey = nextKey + 1,
            errorCount = errorCount + 1,
        )
    }

    private fun delta(text: String): ChatState {
        if (text.isEmpty()) return this
        val last = items.lastOrNull()
        return if (last is AiMsg) copy(items = items.dropLast(1) + last.copy(text = last.text + text))
        else copy(items = items + AiMsg(nextKey, text), nextKey = nextKey + 1)
    }

    private fun tool(m: JSONObject): ChatState {
        val call = m.optString("call")
        val state = m.optString("state", "running")
        val detail = m.optString("detail")
        val summary = m.optString("summary")
        // any tool event for a call resolves its approval card
        val list = items.map {
            if (it is ConfirmItem && it.call == call && it.answer == Answer.Pending) {
                it.copy(
                    answer = when {
                        state != "denied" -> Answer.Allowed
                        detail == "timeout" -> Answer.Expired
                        else -> Answer.Denied
                    }
                )
            } else it
        }
        if (state == "denied") return copy(items = list) // the card already says so
        val i = list.indexOfFirst { it is ToolItem && it.call == call }
        if (i >= 0) {
            val old = list[i] as ToolItem
            val upd = old.copy(state = state, detail = detail, summary = summary.ifEmpty { old.summary })
            return copy(items = list.toMutableList().also { it[i] = upd })
        }
        return copy(
            items = list + ToolItem(nextKey, call, m.optString("name"), summary, state, detail),
            nextKey = nextKey + 1,
        )
    }

    private fun confirmReq(m: JSONObject): ChatState = copy(
        items = items + ConfirmItem(
            key = nextKey,
            call = m.optString("call"),
            summary = m.optString("summary"),
            risk = m.optString("risk", "low"),
            timeout = m.optInt("timeout", 60),
            answer = Answer.Pending,
        ),
        nextKey = nextKey + 1,
        confirmCount = confirmCount + 1,
    )

    private fun failed(msg: String): ChatState = copy(
        items = expirePending(items) + ErrorItem(nextKey, msg),
        activeTurn = null,
        nextKey = nextKey + 1,
        errorCount = errorCount + 1,
    )

    private fun expirePending(list: List<ChatItem>): List<ChatItem> = list.map {
        if (it is ConfirmItem && it.answer == Answer.Pending) it.copy(answer = Answer.Expired) else it
    }
}

// ---- computer-use session (the AI is allowed to look and click for a short, time-boxed while) ----

/** An active session. [endAtMs] is wall-clock time on this phone, worked out when the message arrived. */
data class CuSession(val endAtMs: Long, val goal: String)

/** Result of applying one `cu_session` message. [ended] is a human sentence when the session just finished. */
data class CuUpdate(val session: CuSession?, val ended: String?)

fun cuFrom(m: JSONObject, nowMs: Long, old: CuSession?): CuUpdate = when (m.optString("state")) {
    "active" -> {
        val secs = m.optInt("secs_left", 0).coerceIn(0, 3600)
        CuUpdate(CuSession(nowMs + secs * 1000L, m.optString("goal").ifEmpty { old?.goal ?: "" }.take(160)), null)
    }
    "ended" -> CuUpdate(
        null,
        when (m.optString("reason")) {
            "done" -> "Computer use finished"
            "timeout" -> "Computer use timed out"
            "user" -> "Stopped"
            "touched" -> "You took over"
            "limit" -> "Computer use hit its action limit"
            "error" -> "Computer use stopped after an error"
            "disconnected" -> "Computer use ended: connection lost"
            else -> "Computer use ended"
        },
    )
    else -> CuUpdate(old, null)
}

/** What a tool line says. The screen-guide tools get friendlier text; everything else uses the PC's own summary. */
fun toolLabel(t: ToolItem): String = when {
    t.name == "point_at_screen" && t.state == "running" -> "Pointing it out\u2026"
    t.name == "clear_guide" && t.state == "running" -> "Clearing the guide\u2026"
    t.name == "clear_guide" && t.state == "ok" -> "Guide cleared"
    else -> t.summary
}

// ---- saved spend figure (survives app restarts; dropped after two days) ----

const val SPEND_KEEP_MS = 2L * 24 * 3600 * 1000

/** Is a saved spend figure still worth showing? Tolerates a little clock skew into the future. */
fun spendIsFresh(atMs: Long, nowMs: Long): Boolean =
    atMs > 0 && (nowMs - atMs) in -3_600_000L..SPEND_KEEP_MS

/** null if the figure was reported today (local time), otherwise a short phrase like "yesterday". */
fun spendAgeLabel(atMs: Long, nowMs: Long, zone: java.time.ZoneId): String? {
    val then = java.time.Instant.ofEpochMilli(atMs).atZone(zone).toLocalDate()
    val now = java.time.Instant.ofEpochMilli(nowMs).atZone(zone).toLocalDate()
    val days = java.time.temporal.ChronoUnit.DAYS.between(then, now)
    return when {
        days <= 0 -> null
        days == 1L -> "yesterday"
        else -> "$days days ago"
    }
}
