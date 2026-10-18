package com.fortress.agent.core

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import java.time.Instant
import java.time.LocalTime
import java.time.ZoneId

/** The rules document (docs/rules_format.md §2). */
data class Rules(
    val lists: Map<String, Items>,
    val schedules: List<Schedule>,
    val allow: Items,
) {
    companion object {
        fun parse(obj: JsonObject): Rules = Rules(
            lists = (obj["lists"] as? JsonObject ?: JsonObject(emptyMap()))
                .mapValues { (_, v) -> Items.parse(v as JsonObject) },
            schedules = (obj["schedules"] as? JsonArray ?: JsonArray(emptyList()))
                .map { Schedule.parse(it as JsonObject) },
            allow = Items.parse(obj["allow"] as? JsonObject ?: JsonObject(emptyMap())),
        )
    }
}

data class Items(
    val domains: List<String> = emptyList(),
    val androidPackages: List<String> = emptyList(),
    val windowsPrograms: List<String> = emptyList(),
) {
    operator fun get(kind: Kind): List<String> = when (kind) {
        Kind.DOMAINS -> domains
        Kind.ANDROID_PACKAGES -> androidPackages
        Kind.WINDOWS_PROGRAMS -> windowsPrograms
    }

    companion object {
        fun parse(obj: JsonObject) = Items(
            domains = strings(obj["domains"]),
            androidPackages = strings(obj["android_packages"]),
            windowsPrograms = strings(obj["windows_programs"]),
        )
    }
}

enum class Kind(val key: String) {
    DOMAINS("domains"),
    ANDROID_PACKAGES("android_packages"),
    WINDOWS_PROGRAMS("windows_programs");

    companion object {
        fun of(key: String): Kind = entries.first { it.key == key }
    }
}

sealed class Schedule {
    abstract val id: String
    abstract val list: String
    abstract val devices: List<String>

    fun appliesTo(deviceId: String): Boolean = "all" in devices || deviceId in devices

    /** Repeats each week on [days], [from] until [to], local to [zone]. */
    data class Weekly(
        override val id: String,
        override val list: String,
        override val devices: List<String>,
        val days: Set<Int>, // 0 = Monday … 6 = Sunday
        val from: LocalTime,
        val to: LocalTime,
        val zone: ZoneId,
    ) : Schedule()

    /** One-off, e.g. "Block now for 2 hours". */
    data class Once(
        override val id: String,
        override val list: String,
        override val devices: List<String>,
        val start: Instant,
        val end: Instant,
    ) : Schedule()

    companion object {
        val DAYS = listOf("mon", "tue", "wed", "thu", "fri", "sat", "sun")

        fun parse(obj: JsonObject): Schedule {
            val id = text(obj["id"])
            val list = text(obj["list"])
            val devices = strings(obj["devices"])
            return when (text(obj["kind"])) {
                "weekly" -> Weekly(
                    id, list, devices,
                    days = strings(obj["days"]).map { DAYS.indexOf(it) }.filter { it >= 0 }.toSet(),
                    from = LocalTime.parse(text(obj["from"])),
                    to = LocalTime.parse(text(obj["to"])),
                    zone = ZoneId.of(text(obj["tz"])),
                )
                "once" -> Once(id, list, devices, parseUtc(text(obj["start"])), parseUtc(text(obj["end"])))
                else -> throw IllegalArgumentException("unknown schedule kind in $id")
            }
        }
    }
}

internal fun parseUtc(s: String): Instant = Instant.parse(s)

private fun text(e: Any?): String =
    (e as? JsonPrimitive)?.takeIf { it.isString }?.contentOrNull ?: throw IllegalArgumentException("expected text")

private fun strings(e: Any?): List<String> = (e as? JsonArray)?.map { text(it) } ?: emptyList()
