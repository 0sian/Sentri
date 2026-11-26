package uk.osianj.companion

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class WolTest {
    @Test fun parsesBothSeparatorsAndRejectsJunk() {
        val want = byteArrayOf(0xAA.toByte(), 0xBB.toByte(), 0x0C, 0x0D, 0xEE.toByte(), 0x01)
        assertArrayEquals(want, Wol.parseMac("aa:bb:0c:0d:ee:01"))
        assertArrayEquals(want, Wol.parseMac("AA-BB-0C-0D-EE-01"))
        assertNull(Wol.parseMac("aa:bb:cc:dd:ee"))
        assertNull(Wol.parseMac("aa:bb:cc:dd:ee:zz"))
        assertNull(Wol.parseMac("aa:bb:cc:dd:ee:100"))
    }

    @Test fun magicPacketLayout() {
        val mac = Wol.parseMac("01:02:03:04:05:06")!!
        val p = Wol.magicPacket(mac)
        assertEquals(102, p.size)
        for (i in 0 until 6) assertEquals(0xFF.toByte(), p[i])
        for (r in 0 until 16) for (i in 0 until 6) assertEquals(mac[i], p[6 + r * 6 + i])
    }
}
