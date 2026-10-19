package com.fortress.agent.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.time.Instant
import kotlin.random.Random
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull

class DnsTest {
    // ---- independent builders and checks (not using DnsPackets) ----

    private fun dnsQuery(name: String, id: Int = 0x1234, flags: Int = 0x0100, qtype: Int = 1): ByteArray {
        val o = ByteArrayOutputStream()
        fun w16(v: Int) { o.write(v shr 8); o.write(v and 0xFF) }
        w16(id); w16(flags); w16(1); w16(0); w16(0); w16(1)
        for (label in name.split('.')) { o.write(label.length); o.write(label.toByteArray()) }
        o.write(0)
        w16(qtype); w16(1)
        // An EDNS OPT record, as Android's resolver sends.
        o.write(0); w16(41); w16(1232); w16(0); w16(0); w16(0)
        return o.toByteArray()
    }

    private val client4 = byteArrayOf(10, 111, 222.toByte(), 1)
    private val dns4 = byteArrayOf(10, 111, 222.toByte(), 2)
    private val client6 = ByteArray(16).also { it[0] = 0xfd.toByte(); it[15] = 1.toByte() }
    private val dns6 = ByteArray(16).also { it[0] = 0xfd.toByte(); it[15] = 2.toByte() }

    private fun udpV4(msg: ByteArray, dstPort: Int = 53, proto: Int = 17): ByteArray {
        val total = 28 + msg.size
        val p = ByteArray(total)
        p[0] = 0x45; p[2] = (total shr 8).toByte(); p[3] = total.toByte(); p[8] = 64; p[9] = proto.toByte()
        client4.copyInto(p, 12); dns4.copyInto(p, 16)
        p[20] = 0xC3.toByte(); p[21] = 0x50 // source port 50000
        p[22] = (dstPort shr 8).toByte(); p[23] = dstPort.toByte()
        p[24] = ((8 + msg.size) shr 8).toByte(); p[25] = (8 + msg.size).toByte()
        msg.copyInto(p, 28)
        return p
    }

    private fun udpV6(msg: ByteArray): ByteArray {
        val p = ByteArray(48 + msg.size)
        p[0] = 0x60; p[4] = ((8 + msg.size) shr 8).toByte(); p[5] = (8 + msg.size).toByte(); p[6] = 17; p[7] = 64
        client6.copyInto(p, 8); dns6.copyInto(p, 24)
        p[40] = 0xC3.toByte(); p[41] = 0x51; p[43] = 53
        p[44] = ((8 + msg.size) shr 8).toByte(); p[45] = (8 + msg.size).toByte()
        msg.copyInto(p, 48)
        return p
    }

    /** True when the 16-bit ones' complement sum of the words is 0xFFFF (a valid checksum). */
    private fun sumsToAllOnes(vararg chunks: ByteArray): Boolean {
        var s = 0L
        for (c in chunks) {
            val b = if (c.size % 2 == 0) c else c + 0
            for (i in b.indices step 2) s += ((b[i].toInt() and 0xFF) shl 8) or (b[i + 1].toInt() and 0xFF)
        }
        while (s > 0xFFFF) s = (s and 0xFFFF) + (s shr 16)
        return s == 0xFFFFL
    }

    private fun be16(v: Int) = byteArrayOf((v shr 8).toByte(), v.toByte())
    private fun be32(v: Int) = byteArrayOf(0, 0, (v shr 8).toByte(), v.toByte())

    // ---- tests ----

    @Test
    fun parsesAnIpv4Query() {
        val q = assertNotNull(DnsPackets.parse(udpV4(dnsQuery("WWW.YouTube.com"))))
        assertEquals(4, q.ipVersion)
        assertEquals("www.youtube.com", q.name)
        assertEquals(50000, q.sourcePort)
        assertContentEquals(dns4, q.destination)
    }

    @Test
    fun parsesAnIpv6Query() {
        val q = assertNotNull(DnsPackets.parse(udpV6(dnsQuery("tiktok.com", qtype = 28))))
        assertEquals(6, q.ipVersion)
        assertEquals("tiktok.com", q.name)
    }

    @Test
    fun nxdomainAnswersTheSameQuestion() {
        val query = dnsQuery("tiktok.com", id = 0xBEEF)
        val r = DnsPackets.nxdomain(query)
        assertEquals(0xBE, r[0].toInt() and 0xFF); assertEquals(0xEF, r[1].toInt() and 0xFF)
        val flags = ((r[2].toInt() and 0xFF) shl 8) or (r[3].toInt() and 0xFF)
        assertEquals(0x8000, flags and 0x8000, "QR")
        assertEquals(0x0100, flags and 0x0100, "RD copied")
        assertEquals(0x0080, flags and 0x0080, "RA")
        assertEquals(3, flags and 0xF, "NXDOMAIN")
        assertContentEquals(byteArrayOf(0, 1, 0, 0, 0, 0, 0, 0), r.copyOfRange(4, 12))
        assertEquals("tiktok.com", run {
            // The question is unchanged: re-read it as a query.
            val back = r.copyOf().also { it[2] = 1; it[3] = 0 }
            DnsPackets.questionName(back)
        })
        assertEquals(12 + 12 + 4, r.size) // header + "\x06tiktok\x03com\x00" + type/class
    }

    @Test
    fun ipv4ReplyIsWellFormed() {
        val q = DnsPackets.parse(udpV4(dnsQuery("example.org")))!!
        val answer = DnsPackets.nxdomain(q.message)
        val p = DnsPackets.reply(q, answer)
        assertEquals(28 + answer.size, p.size)
        assertContentEquals(dns4, p.copyOfRange(12, 16), "from the filter's DNS address")
        assertContentEquals(client4, p.copyOfRange(16, 20), "to the asker")
        assertEquals(53, ((p[20].toInt() and 0xFF) shl 8) or (p[21].toInt() and 0xFF))
        assertEquals(50000, ((p[22].toInt() and 0xFF) shl 8) or (p[23].toInt() and 0xFF))
        assert(sumsToAllOnes(p.copyOfRange(0, 20))) { "IPv4 header checksum" }
        val udp = p.copyOfRange(20, p.size)
        assert(sumsToAllOnes(dns4, client4, be16(17), be16(udp.size), udp)) { "UDP checksum" }
        assertContentEquals(answer, p.copyOfRange(28, p.size))
    }

    @Test
    fun ipv6ReplyIsWellFormed() {
        val q = DnsPackets.parse(udpV6(dnsQuery("example.org", qtype = 28)))!!
        val upstream = DnsPackets.nxdomain(q.message) + byteArrayOf(1, 2, 3) // odd length on purpose
        val p = DnsPackets.reply(q, upstream)
        assertContentEquals(dns6, p.copyOfRange(8, 24))
        assertContentEquals(client6, p.copyOfRange(24, 40))
        val udp = p.copyOfRange(40, p.size)
        assert(sumsToAllOnes(dns6, client6, be32(udp.size), be32(17), udp)) { "UDP checksum over the IPv6 pseudo-header" }
    }

    @Test
    fun ignoresWhatIsNotADnsQuery() {
        assertNull(DnsPackets.parse(udpV4(dnsQuery("a.com"), proto = 6)), "TCP")
        assertNull(DnsPackets.parse(udpV4(dnsQuery("a.com"), dstPort = 443)), "not port 53")
        assertNull(DnsPackets.parse(udpV4(dnsQuery("a.com", flags = 0x8180))), "a response")
        assertNull(DnsPackets.parse(udpV4(dnsQuery("a.com", flags = 0x2900))), "an UPDATE, not a query")
        val full = udpV4(dnsQuery("a.com"))
        assertNull(DnsPackets.parse(full, full.size - 30), "cut short")
        val compressed = dnsQuery("a.com").also { it[12] = 0xC0.toByte() }
        assertNull(DnsPackets.parse(udpV4(compressed)), "compression pointer in a question")
        assertNull(DnsPackets.parse(ByteArray(0)))
    }

    @Test
    fun junkNeverThrows() {
        val rnd = Random(42)
        repeat(20_000) {
            val p = ByteArray(rnd.nextInt(0, 120)).also(rnd::nextBytes)
            if (p.isNotEmpty() && rnd.nextBoolean()) p[0] = if (rnd.nextBoolean()) 0x45 else 0x60
            DnsPackets.parse(p)
        }
        // Mutations of a real query: every byte flipped in turn.
        val good = udpV4(dnsQuery("www.youtube.com"))
        for (i in good.indices) for (v in listOf(0, 0xFF, 0x3F, 0xC0)) {
            DnsPackets.parse(good.copyOf().also { it[i] = v.toByte() })?.let { DnsPackets.nxdomain(it.message) }
        }
    }

    @Test
    fun siteFilterFollowsTheScheduleAndCountsPerEntry() {
        val rules = Rules.parse(
            Json.parseToJsonElement(File(System.getProperty("fortress.vectors")).readText()).jsonObject["rules"]!!.jsonObject,
        )
        var now = Instant.parse("2026-10-19T13:00:00Z") // Monday 09:00 New York: 'social' on the tablet
        val f = SiteFilter { now }
        assertNull(f.check("tiktok.com"), "no rules yet: nothing blocked")
        f.update(rules, "tablet")
        assertEquals("tiktok.com", f.check("www.tiktok.com"))
        assertEquals("tiktok.com", f.check("m.tiktok.com"))
        assertEquals("*.reddit.com", f.check("old.reddit.com"))
        assertNull(f.check("github.com"), "always allowed")
        assertNull(f.check("example.org"))
        assertEquals("tiktok.com 2, *.reddit.com 1", f.takeSummary())
        assertNull(f.takeSummary(), "counts are taken once")

        now = Instant.parse("2026-10-19T19:00:00Z") // 15:00: the window has ended
        assertNull(f.check("tiktok.com"))
        f.update(null, null)
        now = Instant.parse("2026-10-19T13:00:00Z")
        assertNull(f.check("tiktok.com"), "rules cleared")
    }
}
