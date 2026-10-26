package com.fortress.agent.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.time.Instant
import java.time.LocalDate
import kotlin.test.Test
import kotlin.test.assertEquals

class StepsTest {
    private val read = Instant.parse("2026-10-27T13:00:00.123456Z")

    @Test
    fun stepsReportIsWhatThePcReads() {
        val json = stepsReport(
            listOf(LocalDate.parse("2026-10-27") to 312L, LocalDate.parse("2026-10-26") to 12_345L),
            read,
        )
        val o = Json.parseToJsonElement(json).jsonObject
        assertEquals(1, o["v"]!!.jsonPrimitive.int)
        assertEquals("2026-10-27T13:00:00Z", o["at"]!!.jsonPrimitive.content)   // whole seconds
        val days = o["days"]!!.jsonArray.map { it.jsonObject }
        assertEquals(listOf("2026-10-26", "2026-10-27"), days.map { it["date"]!!.jsonPrimitive.content })
        assertEquals(listOf(12_345L, 312L), days.map { it["steps"]!!.jsonPrimitive.long })
    }

    @Test
    fun negativeCountsBecomeZero() {
        val json = stepsReport(listOf(LocalDate.parse("2026-10-26") to -5L), read)
        val day = Json.parseToJsonElement(json).jsonObject["days"]!!.jsonArray[0].jsonObject
        assertEquals(0L, day["steps"]!!.jsonPrimitive.long)
    }

    @Test
    fun aWeekOfStepsFitsAsAReport() {
        val week = (0L until 8L).map { LocalDate.parse("2026-10-20").plusDays(it) to 25_000L }
        val state = AgentState(deviceId = "pixel", coreUrl = "http://127.0.0.1:47801", corePublicKey = "AAAA", highestVersion = 1)
            .withReport(STEPS_SOURCE, stepsReport(week, read), read)
        assertEquals(1, state.reports.size)
    }
}
