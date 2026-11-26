package uk.osianj.companion

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

/** State transitions for messages that can't be delivered, and for the screen-guide tool events. */
class ChatDeliveryTest {
    private fun j(s: String) = JSONObject(s)
    private fun start(text: String = "hi") = ChatState().userSent(1, text)

    @Test fun aPendingMessageSurvivesConnectionChanges() {
        val s = start().setPending(1, true)
        assertTrue(s.awaitingDelivery)
        assertSame(s, s.disconnected()) // never left the phone: the sender decides, not the link state
        assertEquals(1, s.activeTurn)
    }

    @Test fun onceSentAnUndeliveredDropFailsTheTurn() {
        val s = start().setPending(1, true).setPending(1, false)
        assertFalse(s.awaitingDelivery)
        val lost = s.disconnected()
        assertNull(lost.activeTurn)
        assertEquals("Connection lost · tap to resend", (lost.items.last() as ErrorItem).text)
        assertEquals("hi", (lost.items.last() as ErrorItem).retry)
    }

    @Test fun undeliveredKeepsTheMessageAndOffersResend() {
        val s = start("open steam").setPending(1, true).undelivered(1, "Couldn't reach your PC")
        assertNull(s.activeTurn)
        assertEquals(1, s.errorCount)
        val user = s.items.filterIsInstance<UserMsg>().single()
        assertFalse(user.pending)
        val err = s.items.last() as ErrorItem
        assertEquals("Couldn't reach your PC · tap to resend", err.text)
        assertEquals("open steam", err.retry)
    }

    @Test fun noAnswerSaysSo() {
        val s = start().noAnswer(1)
        assertNull(s.activeTurn)
        assertEquals("No answer from the PC · tap to resend", (s.items.last() as ErrorItem).text)
    }

    @Test fun aFailureForAnOldTurnChangesNothing() {
        val s = start()
        assertSame(s, s.undelivered(7, "late"))
        assertSame(s, s.noAnswer(7))
    }

    @Test fun anyEventCountsAsAnAnswer() {
        var s = start()
        assertEquals(0, s.activity)
        s = s.onServer(j("""{"t":"chat_mood","id":1,"mood":"curious"}"""))
        assertEquals(1, s.activity)
        s = s.onServer(j("""{"t":"confirm_req","id":1,"call":"c1","name":"x","summary":"X","risk":"low","timeout":60}"""))
        assertEquals(2, s.activity)
        // events for another turn don't count
        assertEquals(2, s.onServer(j("""{"t":"chat_delta","id":9,"text":"x"}""")).activity)
        // a new message starts the count again
        assertEquals(0, s.onServer(j("""{"t":"chat_done","id":1}""")).userSent(2, "again").activity)
    }

    @Test fun retryOfANeverSentMessageDoesNotShowItTwice() {
        val failed = start("open steam").undelivered(1, "Couldn't reach your PC")
        val errKey = failed.items.last().key
        val (s, text) = failed.takeRetry(errKey)!!
        assertEquals("open steam", text)
        assertTrue(s.items.isEmpty())
        val again = s.userSent(2, text)
        assertEquals(listOf("open steam"), again.items.filterIsInstance<UserMsg>().map { it.text })
    }

    @Test fun retryAfterPartialProgressKeepsTheHistory() {
        var s = start("open steam")
        s = s.onServer(j("""{"t":"chat_delta","id":1,"text":"Opening"}"""))
        s = s.disconnected()
        val errKey = s.items.last().key
        val (after, text) = s.takeRetry(errKey)!!
        assertEquals("open steam", text)
        assertEquals(listOf("UserMsg", "AiMsg"), after.items.map { it::class.simpleName })
    }

    @Test fun retryIsRefusedWhileATurnIsRunningOrForUnknownLines() {
        val failed = start().noAnswer(1)
        val key = failed.items.last().key
        assertNull(failed.takeRetry(key + 100))
        assertNull(failed.userSent(2, "next").takeRetry(key)) // a turn is already running
        val plain = start().onServer(j("""{"t":"chat_error","id":1,"msg":"Daily AI budget reached"}"""))
        assertNull(plain.takeRetry(plain.items.last().key)) // server errors have nothing to resend
    }

    @Test fun guideToolsNeedNoApprovalCard() {
        var s = start()
        s = s.onServer(j("""{"t":"tool","id":1,"call":"g1","name":"point_at_screen","summary":"Point out the save button","state":"running"}"""))
        assertEquals("Pointing it out…", toolLabel(s.items.last() as ToolItem))
        s = s.onServer(j("""{"t":"tool","id":1,"call":"g1","name":"point_at_screen","summary":"Point out the save button","state":"ok"}"""))
        assertEquals("Point out the save button", toolLabel(s.items.last() as ToolItem))
        assertEquals(0, s.confirmCount)
        assertTrue(s.items.none { it is ConfirmItem })
        assertEquals(1, s.items.filterIsInstance<ToolItem>().size)
    }

    @Test fun toolLabels() {
        fun t(name: String, state: String, summary: String = "S") = ToolItem(1, "c", name, summary, state, "")
        assertEquals("Clearing the guide…", toolLabel(t("clear_guide", "running")))
        assertEquals("Guide cleared", toolLabel(t("clear_guide", "ok")))
        assertEquals("S", toolLabel(t("clear_guide", "error"))) // don't claim success
        assertEquals("S", toolLabel(t("launch_app", "running")))
        assertEquals("S", toolLabel(t("point_at_screen", "error")))
    }
}
