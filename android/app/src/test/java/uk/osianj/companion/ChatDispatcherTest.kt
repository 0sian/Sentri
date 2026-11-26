package uk.osianj.companion

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CopyOnWriteArrayList

class ChatDispatcherTest {

    private class FakeHost : ChatHost {
        @Volatile override var chat: ChatState = ChatState()
        @Volatile override var connected = true
        /** What transmit() answers, in order; true once the list is used up. */
        val transmitResults = CopyOnWriteArrayList<Boolean>()
        val transmitted = CopyOnWriteArrayList<String>()
        val cancelled = CopyOnWriteArrayList<Int>()
        @Volatile var connectRequests = 0
        @Volatile var reconnects = 0
        val up = CompletableDeferred<Unit>()

        override fun transmit(id: Int, text: String): Boolean {
            val ok = if (transmitResults.isEmpty()) true else transmitResults.removeAt(0)
            if (ok) transmitted += text
            return ok
        }
        override fun ensureConnecting() { connectRequests++ }
        override suspend fun awaitConnected() { up.await() }
        override fun cancelOnPc(id: Int) { cancelled += id }
        override fun reconnect() { reconnects++ }
    }

    private val job = Job()
    private val scope = CoroutineScope(Dispatchers.Default + job)
    @After fun stop() { job.cancel() }

    private val host = FakeHost()
    private fun dispatcher(reconnectWait: Long = 150, answerWait: Long = 300) =
        ChatDispatcher(scope, host, reconnectWaitMs = reconnectWait, answerWaitMs = answerWait, pollMs = 10)

    private fun begin(d: ChatDispatcher, text: String = "hi") {
        host.chat = ChatState().userSent(1, text)
        d.send(1, text)
    }

    private suspend fun until(ms: Long = 2000, cond: () -> Boolean) {
        var t = 0L
        while (!cond() && t < ms) { delay(10); t += 10 }
        assertTrue("condition not reached in ${ms}ms", cond())
    }

    private fun lastError() = host.chat.items.last() as ErrorItem
    private fun event(s: String) { host.chat = host.chat.onServer(JSONObject(s)) }

    @Test fun connectedMessageIsSentOnceAndNotFlagged() = runBlocking {
        begin(dispatcher())
        until { host.transmitted.size == 1 }
        assertFalse(host.chat.awaitingDelivery)
        event("""{"t":"chat_delta","id":1,"text":"Hi"}""")
        delay(500)
        assertEquals(listOf("hi"), host.transmitted.toList())
        assertEquals(1, host.chat.activeTurn)
        assertTrue(host.chat.items.none { it is ErrorItem })
        assertEquals(0, host.reconnects)
        assertEquals(0, host.connectRequests)
    }

    @Test fun messageWaitsForTheConnectionThenGoesOut() = runBlocking {
        host.connected = false
        begin(dispatcher(reconnectWait = 1000))
        until { host.chat.awaitingDelivery }
        assertEquals(1, host.connectRequests)
        assertTrue(host.transmitted.isEmpty()) // nothing is sent into a dead socket
        host.connected = true
        host.up.complete(Unit)
        until { host.transmitted.size == 1 }
        until { !host.chat.awaitingDelivery }
        assertEquals(listOf("hi"), host.transmitted.toList())
    }

    @Test fun aSocketThatRefusesTheMessageIsTreatedAsDown() = runBlocking {
        host.transmitResults += false // looks connected, but the socket is closing
        begin(dispatcher(reconnectWait = 1000))
        until { host.chat.awaitingDelivery }
        host.up.complete(Unit)
        until { host.transmitted.size == 1 }
        assertEquals(1, host.connectRequests)
    }

    @Test fun failsWithResendIfTheConnectionNeverComesBack() = runBlocking {
        host.connected = false
        begin(dispatcher(reconnectWait = 100))
        until { host.chat.activeTurn == null }
        assertTrue(host.transmitted.isEmpty())
        assertEquals("Couldn't reach your PC · tap to resend", lastError().text)
        assertEquals("hi", lastError().retry)
        assertTrue(host.chat.items.filterIsInstance<UserMsg>().none { it.pending })
    }

    @Test fun silenceAfterSendingIsReportedAndTheLinkRestarted() = runBlocking {
        begin(dispatcher(answerWait = 200))
        until { host.chat.activeTurn == null }
        assertEquals("No answer from the PC · tap to resend", lastError().text)
        assertEquals(listOf(1), host.cancelled.toList())
        assertEquals(1, host.reconnects)
    }

    @Test fun waitingOnAnApprovalCardIsNotSilence() = runBlocking {
        begin(dispatcher(answerWait = 200))
        until { host.transmitted.size == 1 }
        event("""{"t":"confirm_req","id":1,"call":"c1","name":"x","summary":"X","risk":"low","timeout":60}""")
        delay(600) // well past the answer timeout, with the card still unanswered
        assertEquals(1, host.chat.activeTurn)
        assertTrue(host.chat.items.none { it is ErrorItem })
        assertEquals(0, host.reconnects)
    }

    @Test fun stopBeforeSendingAbortsWithoutContactingThePc() = runBlocking {
        host.connected = false
        val d = dispatcher(reconnectWait = 1000)
        begin(d)
        until { host.chat.awaitingDelivery }
        assertTrue(d.abortIfUndelivered())
        assertNull(host.chat.activeTurn)
        assertEquals("Not sent · tap to resend", lastError().text)
        host.up.complete(Unit) // the connection coming back later must not send it
        delay(100)
        assertTrue(host.transmitted.isEmpty())
    }

    @Test fun stopAfterSendingIsNotHandledHere() = runBlocking {
        val d = dispatcher()
        begin(d)
        until { host.transmitted.size == 1 }
        assertFalse(d.abortIfUndelivered())
    }

    @Test fun clearingWhileWaitingMeansItIsNeverSent() = runBlocking {
        host.connected = false
        val d = dispatcher(reconnectWait = 1000)
        begin(d)
        until { host.chat.awaitingDelivery }
        d.cancel()
        host.chat = ChatState()
        host.up.complete(Unit)
        delay(100)
        assertTrue(host.transmitted.isEmpty())
        assertTrue(host.chat.items.isEmpty())
    }
}
