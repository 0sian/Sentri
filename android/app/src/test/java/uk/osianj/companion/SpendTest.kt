package uk.osianj.companion

import java.time.ZoneId
import java.time.ZonedDateTime
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SpendTest {
    private val z = ZoneId.of("Europe/London")
    private fun ms(y: Int, mo: Int, d: Int, h: Int) = ZonedDateTime.of(y, mo, d, h, 0, 0, 0, z).toInstant().toEpochMilli()

    @Test fun freshWithinTwoDays() {
        val at = ms(2026, 10, 21, 12)
        assertTrue(spendIsFresh(at, at))
        assertTrue(spendIsFresh(at, at + SPEND_KEEP_MS))
        assertFalse(spendIsFresh(at, at + SPEND_KEEP_MS + 1))
    }

    @Test fun neverSavedIsNotFresh() { assertFalse(spendIsFresh(0, 1_000)) }

    @Test fun smallClockSkewIsTolerated() {
        val at = 10_000_000L
        assertTrue(spendIsFresh(at, at - 60_000))
        assertFalse(spendIsFresh(at, at - 2 * 3_600_000L))
    }

    @Test fun ageLabel() {
        val now = ms(2026, 10, 23, 9)
        assertNull(spendAgeLabel(ms(2026, 10, 23, 0), now, z))
        assertEquals("yesterday", spendAgeLabel(ms(2026, 10, 22, 23), now, z))
        assertEquals("2 days ago", spendAgeLabel(ms(2026, 10, 21, 12), now, z))
    }
}
