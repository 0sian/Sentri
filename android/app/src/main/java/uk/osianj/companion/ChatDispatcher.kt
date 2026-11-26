package uk.osianj.companion

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

/** What the dispatcher needs from the rest of the app. Tests supply a fake. */
interface ChatHost {
    var chat: ChatState
    /** The link is open and authenticated right now. */
    val connected: Boolean
    /** Try to put the message on the wire. False if the socket couldn't take it. */
    fun transmit(id: Int, text: String): Boolean
    /** Start connecting unless a connection attempt is already running. */
    fun ensureConnecting()
    /** Suspends until the link is open and authenticated. */
    suspend fun awaitConnected()
    /** Best-effort: tell the PC to stop this turn. */
    fun cancelOnPc(id: Int)
    /** Throw the current socket away and open a new one. */
    fun reconnect()
}

/**
 * Gets one chat message to the PC and makes sure the user finds out if it didn't work.
 *
 * - Never sends into a socket that isn't open: reconnects first, shows the message as pending meanwhile,
 *   and marks it failed (tap to resend) if the connection doesn't come back in [reconnectWaitMs].
 * - After sending, expects some sign of life within [answerWaitMs] (any event: text, tool, approval card).
 *   If there is none, the socket is probably dead without the phone knowing, so it says so and reconnects.
 *   A turn waiting on an approval card has already shown a sign of life, so it is never "silent".
 * - A drop after the first sign of life is handled by [ChatState.disconnected].
 */
class ChatDispatcher(
    private val scope: CoroutineScope,
    private val host: ChatHost,
    private val reconnectWaitMs: Long = 8_000,
    private val answerWaitMs: Long = 15_000,
    private val pollMs: Long = 250,
) {
    private var job: Job? = null

    fun send(id: Int, text: String) {
        job?.cancel()
        job = scope.launch { run(id, text) }
    }

    /** Stop watching (the transcript was cleared). Leaves the chat state alone. */
    fun cancel() {
        job?.cancel()
        job = null
    }

    /** The user pressed stop before the message left the phone. True if that was the case. */
    fun abortIfUndelivered(): Boolean {
        val c = host.chat
        val id = c.activeTurn ?: return false
        if (!c.awaitingDelivery) return false
        cancel()
        host.chat = c.undelivered(id, "Not sent")
        return true
    }

    private suspend fun run(id: Int, text: String) {
        if (!(host.connected && host.transmit(id, text))) {
            host.chat = host.chat.setPending(id, true)
            host.ensureConnecting()
            val up = withTimeoutOrNull(reconnectWaitMs) { host.awaitConnected(); true } == true
            if (!up || !host.transmit(id, text)) {
                host.chat = host.chat.undelivered(id, "Couldn't reach your PC")
                return
            }
            host.chat = host.chat.setPending(id, false)
        }
        var waited = 0L
        while (true) {
            val c = host.chat
            if (c.activeTurn != id || c.activity > 0) return // answered, finished, failed or replaced
            if (waited >= answerWaitMs) break
            delay(pollMs)
            waited += pollMs
        }
        host.cancelOnPc(id)
        host.chat = host.chat.noAnswer(id)
        host.reconnect()
    }
}
