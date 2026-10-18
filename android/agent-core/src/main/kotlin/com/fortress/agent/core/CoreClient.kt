package com.fortress.agent.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.addJsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URI
import java.net.URISyntaxException
import java.security.SecureRandom
import java.time.Instant

class HttpResponse(val status: Int, val body: ByteArray)

fun interface Transport {
    /** Throws IOException when Core cannot be reached. */
    fun send(method: String, url: String, headers: Map<String, String>, body: ByteArray?): HttpResponse
}

/** Plain HttpURLConnection: works on Android and on a desktop JVM. */
class HttpTransport(private val timeoutMs: Int = 10_000) : Transport {
    override fun send(method: String, url: String, headers: Map<String, String>, body: ByteArray?): HttpResponse {
        val c = URI(url).toURL().openConnection() as HttpURLConnection
        try {
            c.requestMethod = method
            c.connectTimeout = timeoutMs
            c.readTimeout = timeoutMs
            c.useCaches = false
            headers.forEach { (k, v) -> c.setRequestProperty(k, v) }
            if (body != null) {
                c.doOutput = true
                c.setFixedLengthStreamingMode(body.size)
                c.outputStream.use { it.write(body) }
            }
            val status = c.responseCode
            val stream = if (status >= 400) c.errorStream else c.inputStream
            return HttpResponse(status, stream?.use { it.readBytes() } ?: ByteArray(0))
        } finally {
            c.disconnect()
        }
    }
}

/** Core said no. [kind] is Core's error code, e.g. `bad_proof`, `not_enrolled`. */
class CoreError(val status: Int, val kind: String, message: String) : Exception(message)

data class Enrolled(val corePublicKey: ByteArray, val keyId: String, val envelope: JsonObject)

data class CheckInAnswer(val latestVersion: Long, val released: Boolean)

data class Event(val at: String, val kind: String, val detail: String)

/** Talks to Core's Agent API (docs/agent_protocol.md). */
class CoreClient(
    baseUrl: String,
    private val deviceId: String,
    private val signer: DeviceSigner,
    private val transport: Transport = HttpTransport(),
    private val clock: () -> Instant = Instant::now,
    private val random: SecureRandom = SecureRandom(),
) {
    val baseUrl: String = normalizeBaseUrl(baseUrl)

    /** Enrol with a one-time code. Checks Core's proof before trusting its key. */
    fun enrol(code: String): Enrolled {
        val key = Protocol.enrolKey(code)
        val pub = b64e(signer.publicKey)
        val nonce = b64e(ByteArray(16).also(random::nextBytes))
        val body = buildJsonObject {
            put("device_id", deviceId)
            put("public_key", pub)
            put("nonce", nonce)
            put("proof", Protocol.agentProof(key, deviceId, pub, nonce))
        }
        val answer = call("POST", Protocol.ENROL_PATH, body.toString().toByteArray(), signed = false)
        val corePub = answer["core_public_key"]!!.jsonPrimitive.content
        val expected = Protocol.coreProof(key, deviceId, pub, nonce, corePub)
        if (!constantTimeEquals(expected, answer["proof"]!!.jsonPrimitive.content)) {
            throw CoreError(0, "bad_core_proof", "this is not the Fortress that made the code")
        }
        val raw = b64d(corePub)
        val id = answer["key_id"]!!.jsonPrimitive.content
        if (id != keyId(raw)) throw CoreError(0, "bad_core_proof", "Core's key id does not match its key")
        return Enrolled(raw, id, answer["bundle"]!!.jsonObject)
    }

    fun fetchBundle(): JsonObject = call("GET", Protocol.BUNDLE_PATH, ByteArray(0), signed = true)

    fun checkIn(version: Long, agentVersion: String, enforcing: Boolean, events: List<Event>): CheckInAnswer {
        val body = buildJsonObject {
            put("version", version)
            put("agent_version", agentVersion)
            put("enforcing", enforcing)
            putJsonArray("events") {
                for (e in events) addJsonObject {
                    put("at", e.at); put("kind", e.kind); put("detail", e.detail)
                }
            }
        }
        val a = call("POST", Protocol.CHECKIN_PATH, body.toString().toByteArray(), signed = true)
        return CheckInAnswer(a["latest_version"]!!.jsonPrimitive.long, a["released"]!!.jsonPrimitive.boolean)
    }

    private fun call(method: String, path: String, body: ByteArray, signed: Boolean): JsonObject {
        val headers = mutableMapOf("Accept" to "application/json")
        if (method != "GET") headers["Content-Type"] = "application/json"
        if (signed) headers += signedHeaders(method, path, body)
        val res = try {
            transport.send(method, baseUrl + path, headers, if (method == "GET") null else body)
        } catch (e: IOException) {
            throw CoreError(0, "unreachable", "cannot reach Fortress Core at $baseUrl (${e.message})")
        }
        val json = try {
            Json.parseToJsonElement(res.body.toString(Charsets.UTF_8)).jsonObject
        } catch (e: Exception) {
            throw CoreError(res.status, "bad_answer", "Core answered ${res.status} with something unreadable")
        }
        if (res.status !in 200..299) {
            throw CoreError(
                res.status,
                json["error"]?.jsonPrimitive?.content ?: "http_${res.status}",
                json["message"]?.jsonPrimitive?.content ?: "Core answered ${res.status}",
            )
        }
        return json
    }

    fun signedHeaders(method: String, path: String, body: ByteArray): Map<String, String> {
        val time = clock().epochSecond.toString()
        val nonce = b64e(ByteArray(16).also(random::nextBytes))
        val sig = signer.sign(Protocol.requestMessage(method, path, deviceId, time, nonce, body))
        return mapOf(
            "X-Fortress-Device" to deviceId,
            "X-Fortress-Time" to time,
            "X-Fortress-Nonce" to nonce,
            "X-Fortress-Signature" to b64e(sig),
        )
    }

    companion object {
        /** "192.168.1.20" → "http://192.168.1.20:47801". */
        fun normalizeBaseUrl(address: String): String {
            var a = address.trim()
            if ("://" !in a) a = "http://$a"
            val uri = try {
                URI(a.trimEnd('/'))
            } catch (e: URISyntaxException) {
                throw IllegalArgumentException("not an address: $address")
            }
            require(uri.host != null) { "not an address: $address" }
            return if (uri.port == -1) "${uri.scheme}://${uri.host}:${Protocol.DEFAULT_PORT}" else "${uri.scheme}://${uri.host}:${uri.port}"
        }
    }
}
