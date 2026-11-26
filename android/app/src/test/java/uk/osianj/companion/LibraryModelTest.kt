package uk.osianj.companion

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.OffsetDateTime
import java.time.ZoneOffset

class LibraryModelTest {
    private val utc = ZoneOffset.UTC

    @Test fun auditComesNewestFirstWithFields() {
        val s = LibraryState().onServer(JSONObject("""{"t":"audit","items":[
            {"ts":"2026-11-26T14:00:00+00:00","tool":"launch_app","summary":"Open Steam","approval":"auto","result":"ok"},
            {"ts":"2026-11-26T14:05:00+00:00","tool":"close_window","summary":"Close Steam","approval":"denied","result":"not run","detail":"user"}]}"""))
        assertEquals(listOf("Close Steam", "Open Steam"), s.audit!!.map { it.summary })
        assertEquals("user", s.audit!![0].detail)
        assertNull(s.audit!![1].detail)
    }

    @Test fun auditSkipsJunkRows() {
        val s = LibraryState().onServer(JSONObject("""{"t":"audit","items":[1,null,{"summary":""},{"summary":"ok one","tool":"x"}]}"""))
        assertEquals(1, s.audit!!.size)
    }

    @Test fun notLoadedIsNullNotEmpty() {
        val s = LibraryState()
        assertNull(s.audit); assertNull(s.memory); assertNull(s.routines)
        assertTrue(s.onServer(JSONObject("""{"t":"audit"}""")).audit!!.isEmpty())
    }

    @Test fun memoryListAndLimits() {
        val s = LibraryState().onServer(JSONObject("""{"t":"memory","items":[{"id":"m1","text":"Main browser is Vivaldi","created":"2026-10-22"},{"id":"","text":"x"},{"id":"m2","text":" "}],"max":100,"max_text":200,"broken":false}"""))
        assertEquals(listOf("m1"), s.memory!!.map { it.id })
        assertEquals(200, s.memoryMaxText); assertFalse(s.memoryBroken)
        assertTrue(LibraryState().onServer(JSONObject("""{"t":"memory","items":[],"broken":true}""")).memoryBroken)
    }

    @Test fun routinesParse() {
        val s = LibraryState().onServer(JSONObject("""{"t":"routines","items":[
            {"name":"work","description":"Work setup","steps":["Open Firefox","Set volume"],"risk":null},
            {"name":"wipe","description":"","risk":"high","steps":["Close windows"]},{"description":"nameless"}]}"""))
        assertEquals(listOf("work", "wipe"), s.routines!!.map { it.name })
        assertNull(s.routines!![0].risk); assertEquals("high", s.routines!![1].risk)
        assertEquals(listOf("Open Firefox", "Set volume"), s.routines!![0].steps)
    }

    @Test fun memoryResultMatchesTheRequest() {
        val (s, rid) = LibraryState().startMemory()
        assertTrue(s.memRunning); assertEquals(1, rid)
        val d = s.onServer(JSONObject("""{"t":"memory_result","rid":1,"ok":true,"msg":"Saved"}"""))
        assertFalse(d.memRunning); assertEquals("Saved", d.memNote); assertTrue(d.memNoteOk); assertEquals(1, d.memNoteSeq)
    }

    @Test fun refusedMemoryShowsTheReason() {
        val (s, rid) = LibraryState().startMemory()
        val d = s.onServer(JSONObject("""{"t":"memory_result","rid":$rid,"ok":false,"msg":"that looks like a password, key or other secret, so it wasn't saved"}"""))
        assertFalse(d.memNoteOk); assertTrue(d.memNote!!.contains("password"))
    }

    @Test fun staleMemoryResultsAreIgnored() {
        val idle = LibraryState()
        assertSame(idle, idle.onServer(JSONObject("""{"t":"memory_result","rid":1,"ok":true,"msg":"Saved"}""")))
        val (s, _) = idle.startMemory()
        assertTrue(s.onServer(JSONObject("""{"t":"memory_result","rid":9,"ok":true,"msg":"x"}""")).memRunning)
    }

    @Test fun timeoutOnlyHitsTheRequestStillWaiting() {
        val (s, rid) = LibraryState().startMemory()
        val t = s.memoryTimedOut(rid)
        assertFalse(t.memRunning); assertFalse(t.memNoteOk); assertEquals("No answer from the PC", t.memNote)
        val answered = s.onServer(JSONObject("""{"t":"memory_result","rid":$rid,"ok":true,"msg":"Saved"}"""))
        assertSame(answered, answered.memoryTimedOut(rid))
        assertSame(s, s.memoryTimedOut(rid + 3))
    }

    @Test fun disconnectStopsWaitingButKeepsData() {
        val s = LibraryState().onServer(JSONObject("""{"t":"memory","items":[{"id":"m1","text":"a b"}]}""")).startMemory().first
        val d = s.disconnected()
        assertFalse(d.memRunning); assertEquals(1, d.memory!!.size)
    }

    @Test fun approvalLabels() {
        assertEquals("Automatic", approvalLabel("auto", null))
        assertEquals("You allowed it", approvalLabel("allowed", null))
        assertEquals("You said no", approvalLabel("denied", "user"))
        assertEquals("Timed out", approvalLabel("denied", "timeout"))
        assertEquals("Timed out", approvalLabel("timeout", null))
        assertEquals("Your tap", approvalLabel("phone button", null))
        assertEquals("Something", approvalLabel("something", null))
    }

    @Test fun timeAndDayLabels() {
        assertEquals("14:54", timeLabel("2026-11-26T14:54:57+00:00", utc))
        assertEquals("15:54", timeLabel("2026-11-26T14:54:57+00:00", ZoneOffset.ofHours(1)))
        assertNull(timeLabel("garbage", utc))
        val now = OffsetDateTime.parse("2026-11-26T20:00:00+00:00")
        assertEquals("Today", dayLabel("2026-11-26T01:00:00+00:00", now, utc))
        assertEquals("Yesterday", dayLabel("2026-11-25T23:59:00+00:00", now, utc))
        assertEquals("20 Nov", dayLabel("2026-11-20T10:00:00+00:00", now, utc))
        assertNull(dayLabel("", now, utc))
    }
}
