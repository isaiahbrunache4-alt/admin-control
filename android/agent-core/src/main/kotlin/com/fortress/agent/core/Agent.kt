package com.fortress.agent.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.addJsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import kotlinx.serialization.json.putJsonObject
import java.time.Instant
import java.time.temporal.ChronoUnit

const val MAX_EVENTS = 200
const val MAX_REPORTS = 8
const val MAX_REPORT_BYTES = 30 * 1024
private val REPORT_SOURCE = Regex("^[a-z][a-z0-9_]{0,31}$")

/** The latest summary another app on this device handed over, e.g. Block Trainer's
 * logged workouts. [data] is a JSON object, kept as text. Sent at every check-in. */
data class Report(val at: String, val data: String)

/** Everything an Agent keeps between runs. Nothing here is secret: the device key lives
 * in the platform keystore, and the bundle is signed. */
data class AgentState(
    val deviceId: String? = null,
    val coreUrl: String? = null,
    val corePublicKey: String? = null, // base64 raw Ed25519, pinned at enrolment
    val envelope: String? = null, // the latest accepted bundle, as received
    val highestVersion: Long = 0,
    val released: Boolean = false,
    val events: List<Event> = emptyList(),
    val lastSync: String? = null,
    val lastError: String? = null,
    val reports: Map<String, Report> = emptyMap(),
) {
    val enrolled: Boolean get() = deviceId != null && coreUrl != null && corePublicKey != null

    fun withEvent(kind: String, detail: String, now: Instant): AgentState =
        copy(events = (events + Event(stamp(now), kind, detail.take(500))).takeLast(MAX_EVENTS))

    /** Keep [json] as [source]'s latest report. Throws IllegalArgumentException if it's
     * not a small JSON object from a well-named source. */
    fun withReport(source: String, json: String, now: Instant): AgentState {
        require(REPORT_SOURCE.matches(source)) { "report sources are a-z, 0-9 and _, starting with a letter" }
        require(json.toByteArray(Charsets.UTF_8).size <= MAX_REPORT_BYTES) { "report is larger than $MAX_REPORT_BYTES bytes" }
        val obj = try {
            Json.parseToJsonElement(json)
        } catch (e: Exception) {
            throw IllegalArgumentException("report is not JSON")
        }
        require(obj is JsonObject) { "report must be a JSON object" }
        require(source in reports || reports.size < MAX_REPORTS) { "at most $MAX_REPORTS report sources" }
        return copy(reports = reports + (source to Report(stamp(now), obj.toString())))
    }

    fun toJson(): String = buildJsonObject {
        deviceId?.let { put("device_id", it) }
        coreUrl?.let { put("core_url", it) }
        corePublicKey?.let { put("core_public_key", it) }
        envelope?.let { put("envelope", it) }
        put("highest_version", highestVersion)
        put("released", released)
        putJsonArray("events") {
            for (e in events) addJsonObject { put("at", e.at); put("kind", e.kind); put("detail", e.detail) }
        }
        lastSync?.let { put("last_sync", it) }
        lastError?.let { put("last_error", it) }
        putJsonObject("reports") {
            for ((source, r) in reports) putJsonObject(source) { put("at", r.at); put("data", r.data) }
        }
    }.toString()

    companion object {
        fun fromJson(text: String): AgentState {
            val o = Json.parseToJsonElement(text).jsonObject
            fun s(k: String) = o[k]?.jsonPrimitive?.contentOrNull
            return AgentState(
                deviceId = s("device_id"),
                coreUrl = s("core_url"),
                corePublicKey = s("core_public_key"),
                envelope = s("envelope"),
                highestVersion = o["highest_version"]?.jsonPrimitive?.long ?: 0,
                released = o["released"]?.jsonPrimitive?.boolean ?: false,
                events = o["events"]?.jsonArray?.map {
                    val e = it.jsonObject
                    Event(e["at"]!!.jsonPrimitive.content, e["kind"]!!.jsonPrimitive.content, e["detail"]!!.jsonPrimitive.content)
                } ?: emptyList(),
                lastSync = s("last_sync"),
                lastError = s("last_error"),
                reports = o["reports"]?.jsonObject?.mapValues { (_, v) ->
                    val r = v.jsonObject
                    Report(r["at"]!!.jsonPrimitive.content, r["data"]!!.jsonPrimitive.content)
                } ?: emptyMap(),
            )
        }
    }
}

fun stamp(t: Instant): String = t.truncatedTo(ChronoUnit.SECONDS).toString()

interface StateStore {
    fun load(): AgentState
    fun save(state: AgentState)
}

class MemoryStateStore(var state: AgentState = AgentState()) : StateStore {
    override fun load() = state
    override fun save(state: AgentState) { this.state = state }
}

data class SyncResult(val state: AgentState, val rulesChanged: Boolean, val error: String?)

/**
 * The Agent's decisions, independent of the platform. The platform supplies the device
 * key, where state is kept, and how blocks are enforced.
 */
class Agent(
    private val store: StateStore,
    private val signer: DeviceSigner,
    private val agentVersion: String,
    private val transport: Transport = HttpTransport(),
    private val clock: () -> Instant = Instant::now,
) {
    val state: AgentState @Synchronized get() = store.load()

    /** Enrol once (contract A1): verify Core's proof, pin its key, accept its bundle. */
    @Synchronized
    fun enrol(address: String, deviceId: String, code: String): AgentState {
        val client = CoreClient(address, deviceId, signer, transport, clock)
        val got = client.enrol(code)
        val payload = BundleVerifier(got.corePublicKey).accept(got.envelope)
        val now = clock()
        val s = AgentState(
            deviceId = deviceId,
            coreUrl = client.baseUrl,
            corePublicKey = b64e(got.corePublicKey),
            envelope = got.envelope.toString(),
            highestVersion = payload.version,
            released = deviceId in payload.released,
            lastSync = stamp(now),
        ).withEvent("enrolled", "key ${got.keyId}, rules version ${payload.version}", now)
        store.save(s)
        return s
    }

    /** The rules this device enforces: the stored bundle, signature checked again. */
    @Synchronized
    fun currentPayload(): Payload? {
        val s = store.load()
        if (!s.enrolled || s.envelope == null) return null
        return try {
            BundleVerifier(b64d(s.corePublicKey!!)).accept(s.envelope)
        } catch (e: BundleRejected) {
            null
        }
    }

    /** Keep another app's latest report; it goes to Core at the next check-in. */
    @Synchronized
    fun report(source: String, json: String) {
        store.save(store.load().withReport(source, json, clock()))
    }

    @Synchronized
    fun log(kind: String, detail: String = "") {
        store.save(store.load().withEvent(kind, detail, clock()))
    }

    /** Check in, upload events, and fetch a newer bundle if Core has one (A2, A5). */
    @Synchronized
    fun sync(enforcing: Boolean): SyncResult {
        var s = store.load()
        if (!s.enrolled) return SyncResult(s, false, "not enrolled")
        val now = clock()
        val client = CoreClient(s.coreUrl!!, s.deviceId!!, signer, transport, clock)
        val sending = s.events
        var changed = false
        try {
            val answer = client.checkIn(s.highestVersion, agentVersion, enforcing, sending, s.reports)
            s = s.copy(events = s.events.drop(sending.size))
            if (answer.latestVersion > s.highestVersion) {
                val env = client.fetchBundle()
                try {
                    val p = BundleVerifier(b64d(s.corePublicKey!!), s.highestVersion).accept(env)
                    s = s.copy(envelope = env.toString(), highestVersion = p.version, released = s.deviceId in p.released)
                        .withEvent("bundle_accepted", "version ${p.version}", now)
                    changed = true
                } catch (e: BundleRejected) {
                    s = s.withEvent("bundle_rejected", e.message ?: "", now)
                }
            }
            s = s.copy(lastSync = stamp(now), lastError = null)
            store.save(s)
            return SyncResult(s, changed, null)
        } catch (e: CoreError) {
            s = s.copy(lastError = e.message)
            store.save(s)
            return SyncResult(s, false, e.message)
        }
    }
}
