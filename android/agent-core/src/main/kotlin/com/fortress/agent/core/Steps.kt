package com.fortress.agent.core

import kotlinx.serialization.json.addJsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import java.time.Instant
import java.time.LocalDate
import java.time.temporal.ChronoUnit

/** Report source for daily step totals, read on the device from Health Connect. */
const val STEPS_SOURCE = "steps"

/**
 * The "steps" report the PC's Beeminder check reads: daily totals in the device's local
 * days, oldest first, and when they were read.
 *
 *   {"v":1,"at":"2026-10-27T13:00:00Z","days":[{"date":"2026-10-26","steps":12345}, ...]}
 */
fun stepsReport(days: List<Pair<LocalDate, Long>>, at: Instant): String = buildJsonObject {
    put("v", 1)
    put("at", at.truncatedTo(ChronoUnit.SECONDS).toString())
    putJsonArray("days") {
        days.sortedBy { it.first }.forEach { (day, steps) ->
            addJsonObject {
                put("date", day.toString())
                put("steps", maxOf(0L, steps))
            }
        }
    }
}.toString()
