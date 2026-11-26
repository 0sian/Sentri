package uk.osianj.companion

import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress

/** Wake-on-LAN. The PC must have it enabled in its BIOS/UEFI and network driver. */
object Wol {
    /** "aa:bb:cc:dd:ee:ff" or "aa-bb-..." -> 6 bytes, or null if malformed. */
    fun parseMac(mac: String): ByteArray? {
        val parts = mac.trim().split(':', '-')
        if (parts.size != 6) return null
        return ByteArray(6) { i -> parts[i].toIntOrNull(16)?.takeIf { it in 0..255 }?.toByte() ?: return null }
    }

    /** 6 x 0xFF then the MAC repeated 16 times. */
    fun magicPacket(mac: ByteArray): ByteArray {
        require(mac.size == 6)
        val out = ByteArray(6 + 16 * 6) { 0xFF.toByte() }
        for (i in 0 until 16) System.arraycopy(mac, 0, out, 6 + i * 6, 6)
        return out
    }

    /** Blocking: call off the main thread. Sends to the LAN broadcast address on ports 9 and 7. */
    fun send(mac: String): Boolean {
        val bytes = parseMac(mac) ?: return false
        val packet = magicPacket(bytes)
        return try {
            DatagramSocket().use { s ->
                s.broadcast = true
                val addr = InetAddress.getByName("255.255.255.255")
                for (port in intArrayOf(9, 7)) s.send(DatagramPacket(packet, packet.size, addr, port))
            }
            true
        } catch (e: Exception) {
            false
        }
    }
}
