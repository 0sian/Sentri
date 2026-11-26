package uk.osianj.companion

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.concurrent.TimeUnit
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * WebSocket link to the PC daemon.
 *
 * Handshake: daemon sends {"t":"challenge","nonce":..}; we answer with
 * HMAC-SHA256(token, nonce) so the token itself never goes over the wire.
 */
class Link(private val scope: CoroutineScope) {

    sealed interface State {
        data object Idle : State
        data object Connecting : State
        data class Connected(val host: String) : State
        data class Failed(val reason: String, val retrying: Boolean) : State
    }

    private val _state = MutableStateFlow<State>(State.Idle)
    val state: StateFlow<State> = _state

    /** Last measured app-level round-trip in ms, or null if unknown / daemon doesn't answer pings. */
    private val _rtt = MutableStateFlow<Int?>(null)
    val rtt: StateFlow<Int?> = _rtt

    /** Capabilities the daemon announced in its last `ok` (e.g. "chat"). Kept across reconnects so the UI doesn't flicker. */
    private val _caps = MutableStateFlow<Set<String>>(emptySet())
    val caps: StateFlow<Set<String>> = _caps

    /** Called on the main thread, in order, for chat_* / tool / confirm_req / cu_session messages. */
    var chatHandler: ((JSONObject) -> Unit)? = null

    /** Called on the main thread, in order, for `actions` / `action_result` (Quick actions). */
    var actionsHandler: ((JSONObject) -> Unit)? = null

    /** Called on the main thread, in order, for `audit` / `memory` / `memory_result` / `routines` (Activity screen). */
    var libraryHandler: ((JSONObject) -> Unit)? = null

    /** Called on the main thread when the daemon's `ok` includes the PC's MAC address (for Wake-on-LAN). */
    var macHandler: ((String) -> Unit)? = null

    private var pingJob: Job? = null
    @Volatile private var pingId = 0
    @Volatile private var sentId = -1
    @Volatile private var sentAt = 0L

    private val client = OkHttpClient.Builder()
        .connectTimeout(4, TimeUnit.SECONDS)
        .pingInterval(15, TimeUnit.SECONDS)
        .build()

    @Volatile private var ws: WebSocket? = null
    private var wantConnected = false
    private var attempt = 0
    private var host = ""
    private var port = 8765
    private var token = ""

    private companion object {
        const val REPLACED = 4000
        const val POLICY = 1008
    }

    fun connect(host: String, port: Int, token: String) {
        this.host = host
        this.port = port
        this.token = token
        wantConnected = true
        attempt = 0
        open()
    }

    private fun startPing() {
        stopPing()
        pingJob = scope.launch {
            while (isActive) {
                val id = ++pingId
                sentId = id
                sentAt = System.nanoTime()
                send(JSONObject().put("t", "ping").put("id", id))
                delay(2000)
            }
        }
    }

    private fun stopPing() {
        pingJob?.cancel()
        pingJob = null
        sentId = -1
        _rtt.value = null
    }

    fun disconnect() {
        stopPing()
        wantConnected = false
        ws?.close(1000, "bye")
        ws = null
        _state.value = State.Idle
    }

    val isConnected: Boolean get() = _state.value is State.Connected

    /** Drop the current socket and open a fresh one. For when the link looks dead but hasn't said so. */
    fun reconnect() {
        if (!wantConnected) return
        attempt = 0
        open()
    }

    private fun open() {
        // detach first so callbacks from the socket we're cancelling are ignored
        stopPing()
        val old = ws
        ws = null
        old?.cancel()
        _state.value = State.Connecting
        val request = try {
            Request.Builder().url("http://$host:$port").build() // OkHttp upgrades via newWebSocket
        } catch (e: IllegalArgumentException) {
            wantConnected = false
            _state.value = State.Failed("Bad address", false)
            return
        }
        lateinit var socket: WebSocket
        socket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onMessage(webSocket: WebSocket, text: String) {
                if (webSocket !== ws) return
                val m = try { JSONObject(text) } catch (e: Exception) { return }
                when (m.optString("t")) {
                    "challenge" -> webSocket.send(
                        JSONObject().put("t", "auth")
                            .put("hmac", hmacHex(token, m.getString("nonce"))).toString()
                    )
                    "ok" -> {
                        attempt = 0
                        val arr = m.optJSONArray("caps")
                        _caps.value = if (arr == null) emptySet()
                        else (0 until arr.length()).map { arr.optString(it) }.toSet()
                        _state.value = State.Connected(m.optString("host", host))
                        startPing()
                        if ("actions" in _caps.value) send(JSONObject().put("t", "actions_get"))   // fresh list per connection
                        val mac = m.optString("mac")
                        val mh = macHandler
                        if (mac.isNotEmpty() && mh != null) scope.launch { mh(mac) }
                    }
                    "pong" -> if (m.optInt("id", -1) == sentId) {
                        _rtt.value = ((System.nanoTime() - sentAt) / 1_000_000L).toInt()
                    }
                    "chat_delta", "chat_done", "chat_error", "chat_mood", "tool", "confirm_req", "cu_session" -> {
                        val h = chatHandler
                        if (h != null) scope.launch { h(m) } // hop to main; launches stay in order
                    }
                    "actions", "action_result" -> {
                        val h = actionsHandler
                        if (h != null) scope.launch { h(m) }
                    }
                    "audit", "memory", "memory_result", "routines" -> {
                        val h = libraryHandler
                        if (h != null) scope.launch { h(m) }
                    }
                    "denied" -> {
                        wantConnected = false
                        _state.value = State.Failed("Wrong token", false)
                        webSocket.close(1000, null)
                    }
                }
            }

            // answer the server's close frame straight away, so onClosed fires now instead of after a timeout
            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(code, null)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                if (webSocket !== ws) return
                if (code == REPLACED) {
                    stopPing()
                    wantConnected = false
                    _state.value = State.Failed("Another device took over", false)
                } else if (code == POLICY) {
                    // the daemon is rate-limiting failed logins; retrying would only extend the lockout
                    stopPing()
                    wantConnected = false
                    _state.value = State.Failed("PC refused: too many failed logins, try later", false)
                } else {
                    scheduleRetry("Connection closed")
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                if (webSocket !== ws) return
                scheduleRetry("Can't reach PC")
            }
        })
        ws = socket
    }

    private fun scheduleRetry(reason: String) {
        stopPing()
        if (!wantConnected) return
        val failed = ws
        _state.value = State.Failed(reason, true)
        attempt++
        val wait = minOf(5000L, 700L * attempt)
        scope.launch {
            delay(wait)
            if (wantConnected && ws === failed) open()
        }
    }

    // ---- messages -------------------------------------------------------
    private fun send(o: JSONObject) { trySend(o) }

    /** True only if the socket is open and accepted the message. (It can still be lost if the socket is dead.) */
    private fun trySend(o: JSONObject): Boolean =
        _state.value is State.Connected && ws?.send(o.toString()) == true

    fun move(dx: Float, dy: Float) =
        send(JSONObject().put("t", "mv").put("dx", dx.toDouble()).put("dy", dy.toDouble()))

    fun scroll(dx: Float, dy: Float) =
        send(JSONObject().put("t", "sc").put("dx", dx.toDouble()).put("dy", dy.toDouble()))

    /** button: left|right|middle, state: down|up|click */
    fun button(button: String, state: String) =
        send(JSONObject().put("t", "btn").put("b", button).put("s", state))

    fun text(s: String) = send(JSONObject().put("t", "text").put("s", s))

    fun key(name: String, mods: List<String> = emptyList()) =
        send(JSONObject().put("t", "key").put("k", name).put("mods", org.json.JSONArray(mods)))

    // ---- AI chat (PROTOCOL-AI.md) ------------------------------------------
    fun chat(id: Int, text: String): Boolean =
        trySend(JSONObject().put("t", "chat").put("id", id).put("text", text))
    fun chatCancel(id: Int) = send(JSONObject().put("t", "chat_cancel").put("id", id))
    fun chatReset() = send(JSONObject().put("t", "chat_reset"))
    fun cuStop() = send(JSONObject().put("t", "cu_stop"))
    // ---- Quick actions (PROTOCOL.md) ---------------------------------------
    fun actionsGet() = send(JSONObject().put("t", "actions_get"))
    /** True only if the socket accepted it. `confirmed` is required exactly when the item had a confirm text. */
    fun action(id: String, rid: Int, confirmed: Boolean): Boolean =
        trySend(JSONObject().put("t", "action").put("id", id).put("rid", rid).apply { if (confirmed) put("confirmed", true) })
    // ---- Activity, memory, routines (PROTOCOL.md) ----------------------------
    fun auditGet(n: Int = 100) = send(JSONObject().put("t", "audit_get").put("n", n))
    fun memoryGet() = send(JSONObject().put("t", "memory_get"))
    fun routinesGet() = send(JSONObject().put("t", "routines_get"))
    /** True only if the socket accepted it. */
    fun memoryAdd(text: String, rid: Int) = trySend(JSONObject().put("t", "memory_add").put("text", text).put("rid", rid))
    fun memoryEdit(id: String, text: String, rid: Int) =
        trySend(JSONObject().put("t", "memory_edit").put("id", id).put("text", text).put("rid", rid))
    fun memoryForget(id: String, rid: Int) = trySend(JSONObject().put("t", "memory_forget").put("id", id).put("rid", rid))
    fun guideClear() = send(JSONObject().put("t", "guide_clear"))
    fun confirm(call: String, allow: Boolean) =
        send(JSONObject().put("t", "confirm").put("call", call).put("allow", allow))

    private fun hmacHex(token: String, nonce: String): String {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(token.toByteArray(), "HmacSHA256"))
        return mac.doFinal(nonce.toByteArray()).joinToString("") { "%02x".format(it) }
    }
}
