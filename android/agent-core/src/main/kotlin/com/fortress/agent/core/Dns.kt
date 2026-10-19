package com.fortress.agent.core

/**
 * DNS over the website filter's virtual interface (Spec 01 §8.1). The filter routes only
 * its own DNS server address through the interface, so every packet it reads is a DNS
 * lookup: IPv4 or IPv6, UDP, port 53. It answers blocked names itself with "no such
 * domain" and passes every other answer back unchanged.
 *
 * Plain byte work, no Android, so it is tested on the JVM.
 */
class DnsQuery(
    val ipVersion: Int,
    val source: ByteArray,
    val destination: ByteArray,
    val sourcePort: Int,
    val destinationPort: Int,
    /** The DNS message itself, without IP and UDP headers. */
    val message: ByteArray,
    /** The first question's name, lower case, without a trailing dot. */
    val name: String,
)

object DnsPackets {
    private const val UDP = 17
    private const val DNS_PORT = 53
    private const val MAX_NAME = 253

    /** A DNS query in [packet], or null for anything else (which the filter drops). */
    fun parse(packet: ByteArray, length: Int = packet.size): DnsQuery? {
        if (length < 1) return null
        return when (u8(packet, 0) shr 4) {
            4 -> parseV4(packet, length)
            6 -> parseV6(packet, length)
            else -> null
        }
    }

    private fun parseV4(p: ByteArray, length: Int): DnsQuery? {
        if (length < 20) return null
        val ihl = (u8(p, 0) and 0x0F) * 4
        val total = u16(p, 2)
        if (ihl < 20 || total > length || total < ihl + 8) return null
        if (u8(p, 9) != UDP) return null
        // Fragments: DNS queries never need them; ignore rather than reassemble.
        if ((u16(p, 6) and 0x3FFF) != 0) return null
        return udp(4, p, p.copyOfRange(12, 16), p.copyOfRange(16, 20), ihl, total)
    }

    private fun parseV6(p: ByteArray, length: Int): DnsQuery? {
        if (length < 40) return null
        if (u8(p, 6) != UDP) return null // extension headers are not used for DNS queries
        val total = 40 + u16(p, 4)
        if (total > length || total < 48) return null
        return udp(6, p, p.copyOfRange(8, 24), p.copyOfRange(24, 40), 40, total)
    }

    private fun udp(version: Int, p: ByteArray, src: ByteArray, dst: ByteArray, at: Int, end: Int): DnsQuery? {
        val srcPort = u16(p, at)
        val dstPort = u16(p, at + 2)
        val udpLen = u16(p, at + 4)
        if (dstPort != DNS_PORT || udpLen < 8 || at + udpLen > end) return null
        val message = p.copyOfRange(at + 8, at + udpLen)
        val name = questionName(message) ?: return null
        return DnsQuery(version, src, dst, srcPort, dstPort, message, name)
    }

    /** The first question's name, if [message] is a well-formed standard query. */
    fun questionName(message: ByteArray): String? {
        if (message.size < 12) return null
        val flags = u16(message, 2)
        if (flags and 0x8000 != 0) return null // a response, not a query
        if ((flags shr 11) and 0xF != 0) return null // only standard queries
        if (u16(message, 4) < 1) return null
        val labels = mutableListOf<String>()
        var i = 12
        var total = 0
        while (true) {
            if (i >= message.size) return null
            val len = u8(message, i)
            if (len == 0) break
            if (len and 0xC0 != 0) return null // compression in a question: not from a real client
            if (i + 1 + len > message.size) return null
            total += len + 1
            if (total > MAX_NAME + 1) return null
            labels += String(message, i + 1, len, Charsets.ISO_8859_1)
            i += 1 + len
        }
        if (i + 5 > message.size) return null // QTYPE and QCLASS must follow
        return labels.joinToString(".").lowercase()
    }

    /** "No such domain" for the query's first question. */
    fun nxdomain(query: ByteArray): ByteArray {
        var i = 12
        while (u8(query, i) != 0) i += 1 + u8(query, i)
        val questionEnd = i + 1 + 4
        val out = query.copyOfRange(0, questionEnd)
        val flags = u16(query, 2)
        // QR=1, same opcode and RD, RA=1, RCODE=3 (NXDOMAIN).
        val answer = 0x8000 or (flags and 0x7900) or 0x0080 or 3
        put16(out, 2, answer)
        put16(out, 4, 1) // one question
        put16(out, 6, 0)
        put16(out, 8, 0)
        put16(out, 10, 0)
        return out
    }

    /** An IP packet carrying [dnsReply] back to whoever sent [query]. */
    fun reply(query: DnsQuery, dnsReply: ByteArray): ByteArray =
        if (query.ipVersion == 4) replyV4(query, dnsReply) else replyV6(query, dnsReply)

    private fun replyV4(q: DnsQuery, msg: ByteArray): ByteArray {
        val total = 20 + 8 + msg.size
        val p = ByteArray(total)
        p[0] = 0x45
        put16(p, 2, total)
        put16(p, 6, 0x4000) // don't fragment
        p[8] = 64 // TTL
        p[9] = UDP.toByte()
        q.destination.copyInto(p, 12) // from the filter's DNS address…
        q.source.copyInto(p, 16) // …back to the asker
        put16(p, 10, checksum(p, 0, 20, 0))
        writeUdp(p, 20, q, msg)
        put16(p, 26, udpChecksum(p, 20, msg.size + 8, pseudoV4(q, msg.size + 8)))
        return p
    }

    private fun replyV6(q: DnsQuery, msg: ByteArray): ByteArray {
        val udpLen = 8 + msg.size
        val p = ByteArray(40 + udpLen)
        p[0] = 0x60
        put16(p, 4, udpLen)
        p[6] = UDP.toByte()
        p[7] = 64 // hop limit
        q.destination.copyInto(p, 8)
        q.source.copyInto(p, 24)
        writeUdp(p, 40, q, msg)
        put16(p, 46, udpChecksum(p, 40, udpLen, pseudoV6(q, udpLen)))
        return p
    }

    private fun writeUdp(p: ByteArray, at: Int, q: DnsQuery, msg: ByteArray) {
        put16(p, at, q.destinationPort)
        put16(p, at + 2, q.sourcePort)
        put16(p, at + 4, 8 + msg.size)
        msg.copyInto(p, at + 8)
    }

    private fun pseudoV4(q: DnsQuery, udpLen: Int): Long =
        sum(q.destination) + sum(q.source) + UDP + udpLen

    private fun pseudoV6(q: DnsQuery, udpLen: Int): Long =
        sum(q.destination) + sum(q.source) + udpLen + UDP

    private fun udpChecksum(p: ByteArray, at: Int, len: Int, pseudo: Long): Int {
        val c = checksum(p, at, len, pseudo)
        return if (c == 0) 0xFFFF else c // 0 means "no checksum" in UDP
    }

    /** The Internet checksum (RFC 1071) over [len] bytes from [at], plus [start]. */
    fun checksum(p: ByteArray, at: Int, len: Int, start: Long = 0): Int {
        var s = start
        var i = at
        while (i + 1 < at + len) {
            s += u16(p, i)
            i += 2
        }
        if (i < at + len) s += u8(p, i) shl 8
        while (s shr 16 != 0L) s = (s and 0xFFFF) + (s shr 16)
        return (s.inv() and 0xFFFF).toInt()
    }

    private fun sum(b: ByteArray): Long {
        var s = 0L
        var i = 0
        while (i + 1 < b.size) {
            s += u16(b, i)
            i += 2
        }
        return s
    }

    private fun u8(b: ByteArray, i: Int) = b[i].toInt() and 0xFF
    private fun u16(b: ByteArray, i: Int) = (u8(b, i) shl 8) or u8(b, i + 1)
    private fun put16(b: ByteArray, i: Int, v: Int) {
        b[i] = (v shr 8).toByte()
        b[i + 1] = v.toByte()
    }
}
