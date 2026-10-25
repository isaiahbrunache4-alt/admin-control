package com.fortress.agent.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.time.Instant
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull

class ReportTest {
    private val enrolled = AgentState(
        deviceId = "pixel", coreUrl = "http://127.0.0.1:47801", corePublicKey = "AAAA", highestVersion = 5,
    )
    private val t = Instant.parse("2026-10-25T18:00:00Z")

    @Test
    fun reportsSurviveTheStateFile() {
        val s = enrolled.withReport("block_trainer", """{"v":1,"days_per_week":4}""", t)
        assertEquals(s.reports, AgentState.fromJson(s.toJson()).reports)
        assertEquals("2026-10-25T18:00:00Z", s.reports["block_trainer"]!!.at)
    }

    @Test
    fun oldStateFilesHaveNoReports() {
        val old = """{"device_id":"pixel","highest_version":3,"released":false,"events":[]}"""
        assertEquals(emptyMap(), AgentState.fromJson(old).reports)
    }

    @Test
    fun badReportsAreRefused() {
        assertFailsWith<IllegalArgumentException> { enrolled.withReport("Bad Name", "{}", t) }
        assertFailsWith<IllegalArgumentException> { enrolled.withReport("block_trainer", "[1,2]", t) }
        assertFailsWith<IllegalArgumentException> { enrolled.withReport("block_trainer", "not json", t) }
        assertFailsWith<IllegalArgumentException> {
            enrolled.withReport("block_trainer", """{"x":"${"y".repeat(MAX_REPORT_BYTES)}"}""", t)
        }
        var full = enrolled
        for (i in 0 until MAX_REPORTS) full = full.withReport("s$i", "{}", t)
        assertFailsWith<IllegalArgumentException> { full.withReport("one_more", "{}", t) }
        full.withReport("s0", """{"replaced":true}""", t)   // an existing source can always update
    }

    @Test
    fun checkInCarriesTheLatestReports() {
        var sent: String? = null
        val transport = Transport { _, _, _, body ->
            sent = body?.toString(Charsets.UTF_8)
            HttpResponse(200, """{"latest_version":5,"released":false}""".toByteArray())
        }
        val store = MemoryStateStore(enrolled.withReport("block_trainer", """{"v":1}""", t))
        val result = Agent(store, SoftSigner(), "0.4.0", transport) { Instant.parse("2026-10-25T18:05:00Z") }
            .sync(enforcing = true)
        assertNull(result.error)
        val r = Json.parseToJsonElement(sent!!).jsonObject["reports"]!!.jsonObject["block_trainer"]!!.jsonObject
        assertEquals("2026-10-25T18:00:00Z", r["at"]!!.jsonPrimitive.content)
        assertEquals(1, r["data"]!!.jsonObject["v"]!!.jsonPrimitive.int)
        assertEquals(1, store.state.reports.size)   // kept: it's the latest state, not an event
    }
}
