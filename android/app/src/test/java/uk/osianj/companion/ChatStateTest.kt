package uk.osianj.companion

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class ChatStateTest {
    private fun j(s: String) = JSONObject(s)
    private fun start(text: String = "hi") = ChatState().userSent(1, text)

    @Test fun userMessageStartsATurn() {
        val s = start("open firefox")
        assertEquals(1, s.activeTurn)
        assertEquals(UserMsg(1, "open firefox", turn = 1), s.items.single())
    }

    @Test fun deltasStreamIntoOneBubble() {
        var s = start()
        s = s.onServer(j("""{"t":"chat_delta","id":1,"text":"Hel"}"""))
        s = s.onServer(j("""{"t":"chat_delta","id":1,"text":"lo!"}"""))
        assertEquals(2, s.items.size)
        assertEquals("Hello!", (s.items[1] as AiMsg).text)
    }

    @Test fun textAfterAToolStartsANewBubble() {
        var s = start()
        s = s.onServer(j("""{"t":"chat_delta","id":1,"text":"Sure."}"""))
        s = s.onServer(j("""{"t":"tool","id":1,"call":"c1","name":"launch_app","summary":"Open Firefox","state":"running"}"""))
        s = s.onServer(j("""{"t":"chat_delta","id":1,"text":"Done."}"""))
        assertEquals(listOf("UserMsg", "AiMsg", "ToolItem", "AiMsg"), s.items.map { it::class.simpleName })
    }

    @Test fun toolLineUpdatesInPlace() {
        var s = start()
        s = s.onServer(j("""{"t":"tool","id":1,"call":"c1","name":"launch_app","summary":"Open Firefox","state":"running"}"""))
        s = s.onServer(j("""{"t":"tool","id":1,"call":"c1","name":"launch_app","summary":"Open Firefox","state":"ok"}"""))
        val tools = s.items.filterIsInstance<ToolItem>()
        assertEquals(1, tools.size)
        assertEquals("ok", tools[0].state)
        assertEquals("Open Firefox", tools[0].summary)
    }

    @Test fun doneEndsTheTurnAndBumpsCounter() {
        val s = start().onServer(j("""{"t":"chat_done","id":1}"""))
        assertNull(s.activeTurn)
        assertEquals(1, s.doneCount)
    }

    @Test fun confirmAllowedFlow() {
        var s = start()
        s = s.onServer(j("""{"t":"confirm_req","id":1,"call":"c2","name":"type_text","summary":"Type hi","risk":"low","timeout":60}"""))
        assertEquals(1, s.confirmCount)
        assertEquals(Answer.Pending, (s.items.last() as ConfirmItem).answer)
        s = s.answered("c2", true)
        assertEquals(Answer.Allowed, (s.items.last() as ConfirmItem).answer)
        s = s.onServer(j("""{"t":"tool","id":1,"call":"c2","name":"type_text","summary":"Type hi","state":"running"}"""))
        assertEquals(Answer.Allowed, s.items.filterIsInstance<ConfirmItem>().single().answer)
        assertEquals(1, s.items.filterIsInstance<ToolItem>().size)
    }

    @Test fun denyDoesNotAddAToolLine() {
        var s = start()
        s = s.onServer(j("""{"t":"confirm_req","id":1,"call":"c3","name":"close_window","summary":"Close","risk":"low","timeout":60}"""))
        s = s.answered("c3", false)
        s = s.onServer(j("""{"t":"tool","id":1,"call":"c3","name":"close_window","summary":"Close","state":"denied","detail":"user"}"""))
        assertEquals(Answer.Denied, s.items.filterIsInstance<ConfirmItem>().single().answer)
        assertTrue(s.items.none { it is ToolItem })
    }

    @Test fun timeoutExpiresThePendingCard() {
        var s = start()
        s = s.onServer(j("""{"t":"confirm_req","id":1,"call":"c4","name":"screenshot","summary":"Shot","risk":"high","timeout":60}"""))
        s = s.onServer(j("""{"t":"tool","id":1,"call":"c4","name":"screenshot","summary":"Shot","state":"denied","detail":"timeout"}"""))
        assertEquals(Answer.Expired, s.items.filterIsInstance<ConfirmItem>().single().answer)
    }

    @Test fun answeringTwiceKeepsTheFirstAnswer() {
        var s = start()
        s = s.onServer(j("""{"t":"confirm_req","id":1,"call":"c5","name":"x","summary":"X","risk":"low","timeout":60}"""))
        s = s.answered("c5", true).answered("c5", false)
        assertEquals(Answer.Allowed, s.items.filterIsInstance<ConfirmItem>().single().answer)
    }

    @Test fun errorEndsTurnShowsMessageAndExpiresCards() {
        var s = start()
        s = s.onServer(j("""{"t":"confirm_req","id":1,"call":"c6","name":"x","summary":"X","risk":"low","timeout":60}"""))
        s = s.onServer(j("""{"t":"chat_error","id":1,"msg":"Daily AI budget reached"}"""))
        assertNull(s.activeTurn)
        assertEquals("Daily AI budget reached", (s.items.last() as ErrorItem).text)
        assertEquals(Answer.Expired, s.items.filterIsInstance<ConfirmItem>().single().answer)
    }

    @Test fun staleOrForeignTurnEventsAreIgnored() {
        val s = start()
        assertSame(s, s.onServer(j("""{"t":"chat_delta","id":99,"text":"ghost"}""")))
        val cleared = ChatState()
        assertSame(cleared, cleared.onServer(j("""{"t":"chat_delta","id":1,"text":"late"}""")))
    }

    @Test fun disconnectMidTurnShowsConnectionLost() {
        var s = start()
        s = s.onServer(j("""{"t":"confirm_req","id":1,"call":"c7","name":"x","summary":"X","risk":"low","timeout":60}"""))
        s = s.disconnected()
        assertNull(s.activeTurn)
        assertEquals("Connection lost \u00B7 tap to resend", (s.items.last() as ErrorItem).text)
        assertEquals(Answer.Expired, s.items.filterIsInstance<ConfirmItem>().single().answer)
    }

    @Test fun disconnectWhenIdleChangesNothing() {
        val s = start().onServer(j("""{"t":"chat_done","id":1}"""))
        assertSame(s, s.disconnected())
    }

    @Test fun unknownMessageTypesAreIgnored() {
        val s = start()
        assertSame(s, s.onServer(j("""{"t":"mystery","id":1}""")))
    }

    @Test fun moodIsRecordedPerTurnAndIgnoredWhenUnknownTurn() {
        var st = ChatState().userSent(1, "hi")
        st = st.onServer(JSONObject("""{"t":"chat_mood","id":1,"mood":"Curious"}"""))
        assertEquals("curious", st.mood)
        assertEquals(1, st.moodCount)
        st = st.onServer(JSONObject("""{"t":"chat_mood","id":9,"mood":"angry"}"""))
        assertEquals("curious", st.mood) // other turn: dropped
        st = st.onServer(JSONObject("""{"t":"chat_mood","id":1,"mood":""}"""))
        assertEquals(1, st.moodCount)
        st = st.onServer(JSONObject("""{"t":"chat_done","id":1}""")).userSent(2, "again")
        assertEquals(null, st.mood) // new turn starts clean
    }

    @Test fun computerUseSessionLifecycle() {
        val now = 1_000_000L
        val a = cuFrom(JSONObject("""{"t":"cu_session","state":"active","secs_left":300,"goal":"find a video"}"""), now, null)
        assertEquals(now + 300_000L, a.session!!.endAtMs)
        assertEquals("find a video", a.session!!.goal)
        // a refresh without a goal keeps the old one and moves the end time
        val b = cuFrom(JSONObject("""{"t":"cu_session","state":"active","secs_left":120}"""), now + 1000, a.session)
        assertEquals("find a video", b.session!!.goal)
        assertEquals(now + 1000 + 120_000L, b.session!!.endAtMs)
        val e = cuFrom(JSONObject("""{"t":"cu_session","state":"ended","reason":"touched"}"""), now, b.session)
        assertNull(e.session)
        assertEquals("You took over", e.ended)
        assertEquals("Computer use finished", cuFrom(JSONObject("""{"state":"ended","reason":"done"}"""), now, b.session).ended)
        assertEquals("Computer use ended", cuFrom(JSONObject("""{"state":"ended","reason":"something-new"}"""), now, b.session).ended)
        // unknown state changes nothing; absurd durations are clamped
        assertEquals(b.session, cuFrom(JSONObject("""{"state":"weird"}"""), now, b.session).session)
        assertEquals(now + 3_600_000L, cuFrom(JSONObject("""{"state":"active","secs_left":99999}"""), now, null).session!!.endAtMs)
    }

    @Test fun spendIsTakenFromChatDoneWhenPresent() {
        var st = ChatState().userSent(1, "hi")
        st = st.onServer(JSONObject("""{"t":"chat_done","id":1,"today_usd":0.0123,"budget_usd":1.0}"""))
        assertEquals(0.0123, st.todayUsd!!, 1e-9)
        assertEquals(1.0, st.budgetUsd!!, 1e-9)
        // a later turn without the fields keeps the last known values
        st = st.userSent(2, "again").onServer(JSONObject("""{"t":"chat_done","id":2}"""))
        assertEquals(0.0123, st.todayUsd!!, 1e-9)
    }
}
