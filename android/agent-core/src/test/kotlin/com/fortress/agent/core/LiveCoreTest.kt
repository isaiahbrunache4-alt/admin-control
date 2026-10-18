package com.fortress.agent.core

import org.junit.jupiter.api.Assumptions.assumeTrue
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * The real protocol against a real, running Fortress Core (Python). Skipped unless
 * FORTRESS_AGENT_URL, FORTRESS_DEVICE_ID and FORTRESS_ENROL_CODE are set; see
 * android/README.md for the script that sets them up.
 */
class LiveCoreTest {
    @Test
    fun enrolSyncAndFetch() {
        val url = System.getenv("FORTRESS_AGENT_URL")
        val device = System.getenv("FORTRESS_DEVICE_ID")
        val code = System.getenv("FORTRESS_ENROL_CODE")
        assumeTrue(url != null && device != null && code != null, "no live Core configured")

        val store = MemoryStateStore()
        val agent = Agent(store, SoftSigner(), "live-test")

        // A wrong code is refused by Core, and nothing is pinned.
        val wrong = assertFailsWith<CoreError> { agent.enrol(url!!, device!!, "AAAAA-AAAAA") }
        assertEquals("bad_proof", wrong.kind)
        assertTrue(!agent.state.enrolled)

        // The right one: Core's proof checks out, its key is pinned, its bundle verifies.
        val s = agent.enrol(url, device, code!!)
        assertTrue(s.enrolled)
        val held = s.highestVersion
        assertTrue(held >= 1)
        assertNotNull(agent.currentPayload())

        // A check-in uploads the events; nothing newer to fetch.
        agent.log("live_test", "hello from Kotlin")
        val r1 = agent.sync(enforcing = true)
        assertNull(r1.error)
        assertEquals(false, r1.rulesChanged)
        assertTrue(r1.state.events.isEmpty())

        // Pretend to hold an older version: the Agent fetches, verifies and keeps the bundle.
        store.state = store.state.copy(highestVersion = held - 1)
        val r2 = agent.sync(enforcing = true)
        assertNull(r2.error)
        assertEquals(true, r2.rulesChanged)
        assertEquals(held, r2.state.highestVersion)

        // The enrolment code was single-use.
        val again = assertFailsWith<CoreError> { Agent(MemoryStateStore(), SoftSigner(), "x").enrol(url, device, code) }
        assertEquals("no_enrolment", again.kind)
        println("LIVE OK: enrolled $device, rules version $held, rules ${agent.currentPayload()!!.rules.lists.keys}")
    }
}
