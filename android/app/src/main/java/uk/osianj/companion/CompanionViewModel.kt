package uk.osianj.companion

import android.app.Application
import android.content.Context
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class CompanionViewModel(app: Application) : AndroidViewModel(app) {

    private val prefs = app.getSharedPreferences("companion", Context.MODE_PRIVATE)

    val link = Link(viewModelScope)

    var host by mutableStateOf(prefs.getString("host", "") ?: "")
    var port by mutableStateOf(prefs.getString("port", "8765") ?: "8765")
    var token by mutableStateOf(prefs.getString("token", "") ?: "")
    var sensitivity by mutableFloatStateOf(prefs.getFloat("sens", 1.5f))
    var naturalScroll by mutableStateOf(prefs.getBoolean("natural", true))
    var volumeKeys by mutableStateOf(prefs.getBoolean("volkeys", false))

    // character customisation (indexes into the lists in CompanionScreen.kt)
    // "char2_" keys: the v0.2.1 restyle reordered the options, so old saved indexes don't apply
    var charColor by mutableIntStateOf(prefs.getInt("char2_color", 0))   // bright yellow
    var charShape by mutableIntStateOf(prefs.getInt("char2_shape", 0))   // cloud
    var charEyes by mutableIntStateOf(prefs.getInt("char2_eyes", 0))     // pill
    var charMouth by mutableStateOf(prefs.getBoolean("char2_mouth", false))
    var charWhiteEyes by mutableStateOf(prefs.getBoolean("char2_white", true))

    /** One-shot sticky modifiers (ctrl/alt/shift/super) applied to the next key or typed character. */
    val mods = mutableStateListOf<String>()

    /** True while the microphone is open (drives the character's listening face). */
    var listening by mutableStateOf(false)

    /** Set while the AI has an active computer-use session (it may look at the screen and click). */
    var cu by mutableStateOf<CuSession?>(null)
        private set
    /** One-line reason shown briefly after a session ends. */
    var cuNote by mutableStateOf<String?>(null)

    /** The PC's MAC address, learned from the daemon, for the Wake PC button. */
    var pcMac by mutableStateOf(prefs.getString("mac", null))
        private set
    /** Short status line after pressing Wake PC. */
    var wakeNote by mutableStateOf<String?>(null)

    /** The trackpad's how-to text is shown until the first touch, ever. */
    var padHintSeen by mutableStateOf(prefs.getBoolean("pad_hint_seen", false))
        private set

    fun markPadHintSeen() {
        if (!padHintSeen) { padHintSeen = true; prefs.edit().putBoolean("pad_hint_seen", true).apply() }
    }

    // Counters the character has already reacted to. They live here, not in the screen, so leaving and
    // re-entering the home screen doesn't replay old reactions.
    var seenDone = 0
    var seenConfirm = 0
    var seenError = 0
    var seenMood = 0

    // ---- AI chat --------------------------------------------------------
    /** When the saved spend figure was last reported (0 = none). Survives restarts for two days. */
    var spendAt by mutableLongStateOf(
        prefs.getLong("spend_at", 0L).takeIf { spendIsFresh(it, System.currentTimeMillis()) } ?: 0L
    )
        private set

    var chat by mutableStateOf(
        if (spendAt > 0) ChatState(
            todayUsd = prefs.getString("spend_usd", null)?.toDoubleOrNull(),
            budgetUsd = prefs.getString("spend_budget", null)?.toDoubleOrNull(),
        ) else ChatState()
    )
        private set
    private var turnId = 0

    /** True while the AI's "point at the screen" guide is up on the PC (it retracts by itself after ~10 s). */
    var guide by mutableStateOf(false)
        private set
    private var guideJob: Job? = null

    // Gets chat messages to the PC and reports it if they don't arrive (see ChatDispatcher).
    private val chatHost = object : ChatHost {
        override var chat: ChatState
            get() = this@CompanionViewModel.chat
            set(v) { this@CompanionViewModel.chat = v }
        override val connected: Boolean get() = link.isConnected
        override fun transmit(id: Int, text: String) = link.chat(id, text)
        override fun ensureConnecting() {
            val s = link.state.value
            if (s is Link.State.Idle || s is Link.State.Failed) connect()
        }
        override suspend fun awaitConnected() { link.state.first { it is Link.State.Connected } }
        override fun cancelOnPc(id: Int) = link.chatCancel(id)
        override fun reconnect() = link.reconnect()
    }
    private val dispatcher = ChatDispatcher(viewModelScope, chatHost)

    init {
        link.chatHandler = { m ->
            if (m.optString("t") == "cu_session") {
                val u = cuFrom(m, System.currentTimeMillis(), cu)
                cu = u.session
                if (u.ended != null) cuNote = u.ended
            } else {
                val live = m.optInt("id", -1) == chat.activeTurn
                val done = chat.doneCount
                chat = chat.onServer(m)
                if (chat.doneCount != done && chat.todayUsd != null) saveSpend()
                if (live && m.optString("t") == "tool" && m.optString("state") == "ok") {
                    when (m.optString("name")) {
                        "point_at_screen" -> showGuide()
                        "clear_guide" -> endGuide()
                    }
                }
            }
        }
        if (spendAt == 0L) prefs.edit().remove("spend_at").remove("spend_usd").remove("spend_budget").apply()
        link.macHandler = { mac ->
            if (mac != pcMac && Wol.parseMac(mac) != null) {
                pcMac = mac
                prefs.edit().putString("mac", mac).apply()
            }
        }
        // a dropped connection ends any running turn and voids pending approvals
        viewModelScope.launch {
            link.state.collect { st ->
                if (st !is Link.State.Connected) {
                    chat = chat.disconnected()
                    endGuide()
                    if (cu != null) { cu = null; cuNote = "Computer use ended: connection lost" }
                }
            }
        }
    }

    /**
     * Returns false only if it wasn't taken at all (not paired, or a reply is still running). If the link is
     * down, the message is kept as pending while the app reconnects, then sent; if that fails the transcript
     * says so, with tap-to-resend.
     */
    fun sendChat(text: String): Boolean {
        if (!isPaired || chat.activeTurn != null) return false
        val id = ++turnId
        chat = chat.userSent(id, text)
        dispatcher.send(id, text)
        return true
    }

    /** The user tapped a "tap to resend" line in the transcript. */
    fun retryChat(errorKey: Long) {
        val (s, text) = chat.takeRetry(errorKey) ?: return
        chat = s
        sendChat(text)
    }

    fun stopChat() {
        if (dispatcher.abortIfUndelivered()) return // never left the phone: nothing to cancel on the PC
        chat.activeTurn?.let { link.chatCancel(it) }
    }

    private fun saveSpend() {
        val usd = chat.todayUsd ?: return
        spendAt = System.currentTimeMillis()
        prefs.edit().putLong("spend_at", spendAt).putString("spend_usd", usd.toString()).apply {
            chat.budgetUsd?.let { putString("spend_budget", it.toString()) } ?: remove("spend_budget")
        }.apply()
    }

    private fun showGuide() {
        guideJob?.cancel()
        guide = true
        guideJob = viewModelScope.launch { delay(10_000); guide = false }
    }

    private fun endGuide() {
        guideJob?.cancel()
        guideJob = null
        guide = false
    }

    /** Dismiss the on-screen guide early. */
    fun clearGuide() {
        link.guideClear()
        endGuide()
    }

    fun stopCu() { if (cu != null) link.cuStop() }

    fun clearChat() {
        dispatcher.cancel() // a message still waiting for the connection must not be sent after Clear
        link.chatReset()
        chat = ChatState(todayUsd = chat.todayUsd, budgetUsd = chat.budgetUsd) // keep the spend line
    }

    fun answerConfirm(call: String, allow: Boolean) {
        chat = chat.answered(call, allow)
        link.confirm(call, allow)
    }

    val isPaired: Boolean get() = host.isNotBlank() && token.isNotBlank()

    /** Throw away unsaved edits to the connection fields. */
    fun revertConnection() {
        host = prefs.getString("host", "") ?: ""
        port = prefs.getString("port", "8765") ?: "8765"
        token = prefs.getString("token", "") ?: ""
    }

    /** Send a Wake-on-LAN packet, then try to connect once the PC has had time to boot. */
    fun wakePc() {
        val mac = pcMac ?: return
        viewModelScope.launch {
            val ok = withContext(Dispatchers.IO) { Wol.send(mac) }
            wakeNote = if (ok) "Wake signal sent · reconnecting soon" else "Couldn't send the wake signal"
            if (ok) {
                delay(20_000)
                if (link.state.value !is Link.State.Connected) connect()
            }
            delay(4_000)
            wakeNote = null
        }
    }

    fun saveAndConnect() {
        host = host.trim()
        port = port.trim()
        token = token.trim()
        prefs.edit()
            .putString("host", host).putString("port", port).putString("token", token)
            .putFloat("sens", sensitivity)
            .putBoolean("natural", naturalScroll).putBoolean("volkeys", volumeKeys)
            .putInt("char2_color", charColor).putInt("char2_shape", charShape)
            .putInt("char2_eyes", charEyes).putBoolean("char2_mouth", charMouth)
            .putBoolean("char2_white", charWhiteEyes)
            .apply()
        connect()
    }

    fun savePrefsOnly() {
        prefs.edit()
            .putFloat("sens", sensitivity)
            .putBoolean("natural", naturalScroll).putBoolean("volkeys", volumeKeys)
            .putInt("char2_color", charColor).putInt("char2_shape", charShape)
            .putInt("char2_eyes", charEyes).putBoolean("char2_mouth", charMouth)
            .putBoolean("char2_white", charWhiteEyes)
            .apply()
    }

    fun connect() {
        if (!isPaired) return
        link.connect(host, port.toIntOrNull() ?: 8765, token)
    }

    fun onForeground() {
        if (isPaired && link.state.value is Link.State.Idle) connect()
    }

    fun onBackground() {
        // Drop the socket when the app isn't visible: saves battery and never leaves a stale controller.
        link.disconnect()
    }

    fun handleHardwareKey(keyCode: Int): Boolean {
        if (!volumeKeys || !link.isConnected) return false
        return when (keyCode) {
            android.view.KeyEvent.KEYCODE_VOLUME_UP -> { link.key("volup"); true }
            android.view.KeyEvent.KEYCODE_VOLUME_DOWN -> { link.key("voldown"); true }
            else -> false
        }
    }

    // ---- key helpers that respect sticky modifiers ---------------------
    fun toggleMod(m: String) {
        if (mods.contains(m)) mods.remove(m) else mods.add(m)
    }

    fun pressKey(name: String) {
        link.key(name, mods.toList())
        mods.clear()
    }

    /** Bare tap of a modifier key on its own (e.g. Super to open a launcher). */
    fun tapModAlone(name: String) {
        link.key(name)
        mods.remove(name)
    }

    fun typeText(s: String) {
        if (mods.isNotEmpty() && s.length == 1) {
            link.key(s.lowercase(), mods.toList())
            mods.clear()
        } else {
            link.text(s)
        }
    }

    fun backspace() = link.key("backspace")

    override fun onCleared() {
        link.disconnect()
    }
}
