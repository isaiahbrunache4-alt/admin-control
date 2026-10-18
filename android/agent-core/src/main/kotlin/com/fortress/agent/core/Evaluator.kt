package com.fortress.agent.core

import java.time.Instant
import java.time.LocalTime
import java.time.ZonedDateTime

/** Which blocks are in force on a device at a moment. Mirrors core/fortress_core/schedule.py;
 * the cases in testdata/fortress_vectors.json must give the same answers. */
data class ActiveBlocks(
    val domains: Set<String>,
    val androidPackages: Set<String>,
    val windowsPrograms: Set<String>,
    val scheduleIds: List<String>,
)

object Evaluator {

    fun isActive(s: Schedule, now: Instant): Boolean = when (s) {
        is Schedule.Once -> !now.isBefore(s.start) && now.isBefore(s.end)
        is Schedule.Weekly -> {
            val local = now.atZone(s.zone)
            val t = local.hour * 60 + local.minute
            val today = local.dayOfWeek.value - 1
            val yesterday = (today + 6) % 7
            val start = minutes(s.from)
            val end = minutes(s.to)
            when {
                start == end -> today in s.days                              // all of each listed day
                start < end -> today in s.days && t in start until end       // e.g. 08:00–15:00
                // Overnight, e.g. 22:00–06:00: belongs to the day it starts on.
                else -> (today in s.days && t >= start) || (yesterday in s.days && t < end)
            }
        }
    }

    fun activeBlocks(rules: Rules, deviceId: String, now: Instant): ActiveBlocks {
        val domains = mutableSetOf<String>()
        val packages = mutableSetOf<String>()
        val programs = mutableSetOf<String>()
        val ids = mutableListOf<String>()
        for (s in rules.schedules) {
            if (s.appliesTo(deviceId) && isActive(s, now)) {
                val items = rules.lists[s.list] ?: continue
                domains += items.domains
                packages += items.androidPackages
                programs += items.windowsPrograms
                ids += s.id
            }
        }
        return ActiveBlocks(domains, packages, programs, ids)
    }

    /** '*.example.com' and 'example.com' both match example.com and every subdomain. */
    fun domainMatches(host: String, pattern: String): Boolean {
        val h = host.lowercase().trimEnd('.')
        val base = pattern.removePrefix("*.")
        return h == base || h.endsWith(".$base")
    }

    /** The always-allowed list wins over every block (Spec 01 §8.3, §10). */
    fun isDomainBlocked(rules: Rules, deviceId: String, host: String, now: Instant): Boolean {
        if (rules.allow.domains.any { domainMatches(host, it) }) return false
        return activeBlocks(rules, deviceId, now).domains.any { domainMatches(host, it) }
    }

    fun isAppBlocked(rules: Rules, deviceId: String, kind: Kind, name: String, now: Instant): Boolean {
        val n = if (kind == Kind.WINDOWS_PROGRAMS) name.lowercase() else name
        if (n in rules.allow[kind]) return false
        val active = activeBlocks(rules, deviceId, now)
        return n in when (kind) {
            Kind.DOMAINS -> active.domains
            Kind.ANDROID_PACKAGES -> active.androidPackages
            Kind.WINDOWS_PROGRAMS -> active.windowsPrograms
        }
    }

    /** Android packages to suspend now: active blocks less the allowed list and [never]. */
    fun packagesToBlock(rules: Rules, deviceId: String, now: Instant, never: Set<String> = emptySet()): Set<String> =
        activeBlocks(rules, deviceId, now).androidPackages - rules.allow.androidPackages.toSet() - never

    /**
     * The next moment at which what is blocked on [deviceId] may change, or null if no
     * schedule will ever change it. An Agent re-evaluates then, so blocks start and end on
     * time without polling. Errs early (extra wake-ups at midnight are harmless).
     */
    fun nextChange(rules: Rules, deviceId: String, now: Instant): Instant? {
        var best: Instant? = null
        fun consider(t: Instant) {
            if (t.isAfter(now) && (best == null || t.isBefore(best))) best = t
        }
        for (s in rules.schedules) {
            if (!s.appliesTo(deviceId)) continue
            when (s) {
                is Schedule.Once -> {
                    consider(s.start); consider(s.end)
                }
                is Schedule.Weekly -> {
                    val today = now.atZone(s.zone).toLocalDate()
                    for (d in 0L..8L) {
                        val date = today.plusDays(d)
                        consider(date.atStartOfDay(s.zone).toInstant())
                        for (t in listOf(s.from, s.to)) consider(ZonedDateTime.of(date, t, s.zone).toInstant())
                    }
                }
            }
        }
        return best
    }

    private fun minutes(t: LocalTime) = t.hour * 60 + t.minute
}
