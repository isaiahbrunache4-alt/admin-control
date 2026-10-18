package com.fortress.agent.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import java.io.File
import java.security.KeyPairGenerator
import java.security.Signature
import java.security.interfaces.ECPrivateKey
import java.security.spec.ECGenParameterSpec
import java.time.Instant
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** A device key in memory, for tests. On Android the key is in the Keystore. */
class SoftSigner : DeviceSigner {
    private val pair = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()
    override val publicKey: ByteArray = pair.public.encoded
    override fun sign(data: ByteArray): ByteArray =
        Signature.getInstance("SHA256withECDSA").apply { initSign(pair.private as ECPrivateKey); update(data) }.sign()
}

class AgentTest {
    private fun rules() = Rules.parse(
        Json.parseToJsonElement(File(System.getProperty("fortress.vectors")).readText()).jsonObject["rules"]!!.jsonObject,
    )

    @Test
    fun nextChangeFindsTheNextBoundary() {
        val r = rules()
        // Mon 2026-10-19 13:00 UTC = 09:00 New York, inside s1 (08:00–15:00, tablet).
        assertEquals(Instant.parse("2026-10-19T19:00:00Z"), Evaluator.nextChange(r, "tablet", Instant.parse("2026-10-19T13:00:00Z")))
        // Monday 15:00 New York, on the pixel: next is 'games' at 22:00 New York (02:00 UTC),
        // before local midnight (04:00 UTC).
        assertEquals(Instant.parse("2026-10-20T02:00:00Z"), Evaluator.nextChange(r, "pixel", Instant.parse("2026-10-19T19:00:00Z")))
        // The one-off block on the pixel ends at 16:00 UTC on the 24th.
        assertEquals(Instant.parse("2026-10-24T16:00:00Z"), Evaluator.nextChange(r, "pixel", Instant.parse("2026-10-24T15:00:00Z")))
        // A device no schedule names, with no 'all' schedule… there is one ('games'), so not null.
        assertTrue(Evaluator.nextChange(r, "nobody", Instant.parse("2026-10-19T13:00:00Z")) != null)
        assertNull(Evaluator.nextChange(Rules(emptyMap(), emptyList(), Items()), "x", Instant.EPOCH))
    }

    @Test
    fun nextChangeIsNeverLateForAnyCase() {
        // Walking forward boundary by boundary must never step over a change in the answer.
        val r = rules()
        for (device in listOf("tablet", "pixel", "pc")) {
            var t = Instant.parse("2026-10-18T00:00:00Z")
            val end = Instant.parse("2026-11-05T00:00:00Z")
            while (t.isBefore(end)) {
                val next = Evaluator.nextChange(r, device, t) ?: break
                val before = Evaluator.activeBlocks(r, device, t).scheduleIds
                var probe = t.plusSeconds(60)
                while (probe.isBefore(next)) {
                    assertEquals(before, Evaluator.activeBlocks(r, device, probe).scheduleIds, "$device changed at $probe before $next")
                    probe = probe.plusSeconds(15 * 60)
                }
                t = next
            }
        }
    }

    @Test
    fun packagesToBlockLeavesAllowedAndProtectedAlone() {
        val r = rules()
        val now = Instant.parse("2026-10-19T13:00:00Z")
        assertEquals(setOf("com.zhiliaoapp.musically"), Evaluator.packagesToBlock(r, "tablet", now))
        assertEquals(emptySet(), Evaluator.packagesToBlock(r, "tablet", now, never = setOf("com.zhiliaoapp.musically")))
    }

    @Test
    fun stateRoundTrips() {
        val s = AgentState("tablet", "http://192.168.1.20:47801", "a2V5", "{}", 7, false, lastSync = "2026-10-19T12:00:00Z")
            .withEvent("bundle_accepted", "version 7", Instant.parse("2026-10-19T12:00:00.123Z"))
        val back = AgentState.fromJson(s.toJson())
        assertEquals(s, back)
        assertEquals("2026-10-19T12:00:00Z", back.events.single().at)
    }

    @Test
    fun eventsAreCapped() {
        var s = AgentState()
        repeat(MAX_EVENTS + 5) { s = s.withEvent("e", "$it", Instant.EPOCH) }
        assertEquals(MAX_EVENTS, s.events.size)
        assertEquals("5", s.events.first().detail)
    }

    @Test
    fun addresses() {
        assertEquals("http://192.168.1.20:47801", CoreClient.normalizeBaseUrl("192.168.1.20"))
        assertEquals("http://192.168.1.20:47801", CoreClient.normalizeBaseUrl(" http://192.168.1.20/ "))
        assertEquals("http://fortress-pc.local:9000", CoreClient.normalizeBaseUrl("fortress-pc.local:9000"))
        assertFailsWith<IllegalArgumentException> { CoreClient.normalizeBaseUrl("http://") }
    }

    @Test
    fun aFakeCoreIsRefused() {
        // Answers with a well-formed enrolment but cannot know the code.
        val fake = Transport { _, _, _, _ ->
            HttpResponse(200, """{"core_public_key":"${b64e(ByteArray(32))}","key_id":"x","proof":"${b64e(ByteArray(32))}","bundle":{}}""".toByteArray())
        }
        val agent = Agent(MemoryStateStore(), SoftSigner(), "test", fake)
        val e = assertFailsWith<CoreError> { agent.enrol("192.168.1.20", "tablet", "MFA4D-52ANU") }
        assertEquals("bad_core_proof", e.kind)
        assertTrue(!agent.state.enrolled)
    }

    @Test
    fun unreachableCoreIsReportedNotThrown() {
        val store = MemoryStateStore(AgentState("tablet", "http://192.168.1.20:47801", b64e(ByteArray(32)), highestVersion = 3))
        val down = Transport { _, _, _, _ -> throw java.net.ConnectException("refused") }
        val r = Agent(store, SoftSigner(), "test", down).sync(enforcing = true)
        assertTrue(r.error!!.contains("cannot reach"))
        assertEquals(3, store.state.highestVersion)
    }
}
