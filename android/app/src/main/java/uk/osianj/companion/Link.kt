package uk.osianj.companion

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.delay
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

    private val client = OkHttpClient.Builder()
        .connectTimeout(4, TimeUnit.SECONDS)
        .pingInterval(15, TimeUnit.SECONDS)
        .build()

    private var ws: WebSocket? = null
    private var wantConnected = false
    private var attempt = 0
    private var host = ""
    private var port = 8765
    private var token = ""

    private companion object {
        const val REPLACED = 4000
    }

    fun connect(host: String, port: Int, token: String) {
        this.host = host
        this.port = port
        this.token = token
        wantConnected = true
        attempt = 0
        open()
    }

    fun disconnect() {
        wantConnected = false
        ws?.close(1000, "bye")
        ws = null
        _state.value = State.Idle
    }

    val isConnected: Boolean get() = _state.value is State.Connected

    private fun open() {
        // detach first so callbacks from the socket we're cancelling are ignored
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
                        _state.value = State.Connected(m.optString("host", host))
                    }
                    "denied" -> {
                        wantConnected = false
                        _state.value = State.Failed("Wrong token", false)
                        webSocket.close(1000, null)
                    }
                }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                if (webSocket !== ws) return
                if (code == REPLACED) {
                    wantConnected = false
                    _state.value = State.Failed("Another device took over", false)
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
    private fun send(o: JSONObject) {
        if (_state.value is State.Connected) ws?.send(o.toString())
    }

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

    private fun hmacHex(token: String, nonce: String): String {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(token.toByteArray(), "HmacSHA256"))
        return mac.doFinal(nonce.toByteArray()).joinToString("") { "%02x".format(it) }
    }
}
