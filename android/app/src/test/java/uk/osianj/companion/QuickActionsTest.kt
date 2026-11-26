package uk.osianj.companion

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class QuickActionsTest {
    private val list = JSONObject(
        """{"t":"actions","items":[
          {"id":"lock","label":"Lock","group":"Session"},
          {"id":"logout","label":"Log out","group":"Session","confirm":"Log out? Open apps will be closed.","danger":true},
          {"id":"restart","label":"Restart","group":"Power","confirm":"Restart?","danger":true},
          {"id":"routine:work","label":"Work","group":"Routines"}]}"""
    )

    private fun loaded() = ActionsState().onServer(list)

    @Test fun parsesListWithConfirmAndDanger() {
        val s = loaded()
        assertEquals(listOf("lock", "logout", "restart", "routine:work"), s.items.map { it.id })
        assertEquals("Log out? Open apps will be closed.", s.items[1].confirm)
        assertTrue(s.items[1].danger)
        assertNull(s.items[0].confirm)
        assertFalse(s.items[0].danger)
    }

    @Test fun groupsKeepThePcOrder() {
        assertEquals(listOf("Session", "Power", "Routines"), loaded().groups.map { it.first })
        assertEquals(listOf("lock", "logout"), loaded().groups[0].second.map { it.id })
    }

    @Test fun skipsMalformedItemsAndMissingFields() {
        val m = JSONObject("""{"t":"actions","items":[5,{"id":"","label":"x"},{"id":"a"},{"id":"ok","label":"Ok"},null]}""")
        val items = ActionsState().onServer(m).items
        assertEquals(listOf("ok"), items.map { it.id })
        assertEquals("Actions", items[0].group)   // default section
    }

    @Test fun missingOrWrongItemsGiveAnEmptyList() {
        assertTrue(ActionsState().onServer(JSONObject("""{"t":"actions"}""")).items.isEmpty())
        assertTrue(ActionsState().onServer(JSONObject("""{"t":"actions","items":"x"}""")).items.isEmpty())
    }

    @Test fun capsHugeLists() {
        val items = (1..100).joinToString(",") { """{"id":"a$it","label":"A$it"}""" }
        assertEquals(40, ActionsState().onServer(JSONObject("""{"t":"actions","items":[$items]}""")).items.size)
    }

    @Test fun startHandsOutIncreasingRequestIds() {
        val (s1, r1) = loaded().start(loaded().items[0])
        assertEquals(1, r1); assertEquals("lock", s1.running)
        val done = s1.onServer(JSONObject("""{"t":"action_result","rid":1,"id":"lock","ok":true,"msg":"Locked"}"""))
        val (_, r2) = done.start(done.items[0])
        assertEquals(2, r2)
    }

    @Test fun resultClearsRunningAndSetsNote() {
        val (s, rid) = loaded().start(loaded().items[0])
        val d = s.onServer(JSONObject("""{"t":"action_result","rid":$rid,"id":"lock","ok":true,"msg":"Locked"}"""))
        assertNull(d.running); assertEquals("Locked", d.note); assertTrue(d.noteOk); assertEquals(1, d.noteSeq)
    }

    @Test fun failureKeepsTheReasonAndMarksNotOk() {
        val (s, rid) = loaded().start(loaded().items[0])
        val d = s.onServer(JSONObject("""{"t":"action_result","rid":$rid,"id":"sleep","ok":false,"msg":"Can't sleep yet: media-idle-inhibit: Media is actively playing"}"""))
        assertFalse(d.noteOk); assertTrue(d.note!!.startsWith("Can't sleep yet"))
    }

    @Test fun staleOrUnsolicitedResultsAreIgnored() {
        val s = loaded()
        assertSame(s, s.onServer(JSONObject("""{"t":"action_result","rid":1,"id":"lock","ok":true,"msg":"Locked"}""")))
        val (run, _) = s.start(s.items[0])
        val wrongRid = run.onServer(JSONObject("""{"t":"action_result","rid":99,"id":"lock","ok":true,"msg":"x"}"""))
        assertEquals("lock", wrongRid.running)
    }

    @Test fun emptyMessageFallsBackToDoneOrFailed() {
        val (s, rid) = loaded().start(loaded().items[0])
        assertEquals("Done", s.onServer(JSONObject("""{"t":"action_result","rid":$rid,"ok":true}""")).note)
        assertEquals("Failed", s.onServer(JSONObject("""{"t":"action_result","rid":$rid,"ok":false}""")).note)
    }

    @Test fun timeoutOnlyAppliesToTheRequestStillWaiting() {
        val (s, rid) = loaded().start(loaded().items[0])
        val t = s.timedOut(rid)
        assertNull(t.running); assertFalse(t.noteOk); assertEquals("No answer from the PC", t.note)
        val done = s.onServer(JSONObject("""{"t":"action_result","rid":$rid,"ok":true,"msg":"Locked"}"""))
        assertSame(done, done.timedOut(rid))                 // already answered: a late timer changes nothing
        assertSame(s, s.timedOut(rid + 5))                   // a timer for an older request changes nothing
    }

    @Test fun disconnectClearsRunningButKeepsTheList() {
        val (s, _) = loaded().start(loaded().items[0])
        val d = s.disconnected()
        assertNull(d.running); assertEquals(4, d.items.size)
    }

    @Test fun controlCharactersAndLongMessagesAreCleaned() {
        val (s, rid) = loaded().start(loaded().items[0])
        val msg = "a\\u0007b" + "x".repeat(400)
        val d = s.onServer(JSONObject("""{"t":"action_result","rid":$rid,"ok":true,"msg":"$msg"}"""))
        assertTrue(d.note!!.length <= 160 && !d.note!!.contains('\u0007'))
    }
}
