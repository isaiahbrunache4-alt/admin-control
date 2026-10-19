package com.fortress.agent.core

import java.time.Instant
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger

/**
 * Answers "is this name blocked right now?" for the website filter, many times a second.
 * Which lists are in force is worked out at most once a minute (schedules are by the
 * minute). Blocked attempts are counted per block-list entry, not per name looked up, and
 * nothing is kept about names that were allowed.
 */
class SiteFilter(private val clock: () -> Instant = Instant::now) {
    private class Snapshot(val rules: Rules, val deviceId: String)

    @Volatile private var snapshot: Snapshot? = null
    @Volatile private var cachedMinute = Long.MIN_VALUE
    @Volatile private var cachedActive: ActiveBlocks? = null
    private val counts = ConcurrentHashMap<String, AtomicInteger>()

    /** New rules (or none, which blocks nothing). */
    fun update(rules: Rules?, deviceId: String?) {
        snapshot = if (rules != null && deviceId != null) Snapshot(rules, deviceId) else null
        cachedMinute = Long.MIN_VALUE
    }

    /** The block-list entry blocking [name] now, or null. Counts the attempt if blocked. */
    fun check(name: String): String? {
        val s = snapshot ?: return null
        val entry = Evaluator.blockingEntry(s.rules, active(s), name) ?: return null
        counts.getOrPut(entry) { AtomicInteger() }.incrementAndGet()
        return entry
    }

    private fun active(s: Snapshot): ActiveBlocks {
        val now = clock()
        val minute = now.epochSecond / 60
        val cached = cachedActive
        if (minute == cachedMinute && cached != null) return cached
        return Evaluator.activeBlocks(s.rules, s.deviceId, now).also {
            cachedActive = it
            cachedMinute = minute
        }
    }

    /** Blocked attempts since the last call, e.g. "tiktok.com 12, youtube.com 3"; null if none. */
    fun takeSummary(): String? {
        val taken = counts.keys.toList().mapNotNull { k -> counts.remove(k)?.get()?.takeIf { it > 0 }?.let { k to it } }
        if (taken.isEmpty()) return null
        return taken.sortedByDescending { it.second }.joinToString(", ") { "${it.first} ${it.second}" }
    }
}
