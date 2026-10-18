package com.fortress.agent.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.bouncycastle.crypto.params.Ed25519PublicKeyParameters
import org.bouncycastle.crypto.signers.Ed25519Signer

const val BUNDLE_FORMAT = 1

/** An Agent must refuse this bundle; the message says why. */
class BundleRejected(message: String) : Exception(message)

/** A verified bundle payload (docs/rules_format.md §2). */
data class Payload(
    val version: Long,
    val issuedAt: String,
    val rules: Rules,
    val released: List<String>,
)

/** Ed25519 verification of Core's signatures. */
fun verifyEd25519(publicKey: ByteArray, data: ByteArray, signature: ByteArray): Boolean {
    if (publicKey.size != 32 || signature.size != 64) return false
    return Ed25519Signer().run {
        init(false, Ed25519PublicKeyParameters(publicKey, 0))
        update(data, 0, data.size)
        verifySignature(signature)
    }
}

/**
 * What an Agent does with an incoming bundle (Agent contract A2), in the same order as
 * core/fortress_core/bundle.py: pinned to Core's key at enrolment, it accepts only a valid
 * signature over the exact payload bytes and a version strictly higher than it holds.
 */
class BundleVerifier(private val pinnedKey: ByteArray, var highestVersion: Long = 0) {

    fun accept(envelope: String): Payload {
        val env = try {
            Json.parseToJsonElement(envelope).jsonObject
        } catch (e: Exception) {
            throw BundleRejected("envelope is not JSON")
        }
        return accept(env)
    }

    fun accept(env: JsonObject): Payload {
        val format = (env["format"] as? JsonPrimitive)?.takeIf { !it.isString }?.contentOrNull
        if (format != BUNDLE_FORMAT.toString()) throw BundleRejected("unknown bundle format $format")
        val claimedKey = (env["key_id"] as? JsonPrimitive)?.takeIf { it.isString }?.contentOrNull
        if (claimedKey != keyId(pinnedKey)) throw BundleRejected("signed by a different Fortress")
        val data: ByteArray
        val sig: ByteArray
        try {
            data = b64d(stringField(env, "payload"))
            sig = b64d(stringField(env, "sig"))
        } catch (e: IllegalArgumentException) {
            throw BundleRejected("malformed envelope")
        }
        if (!verifyEd25519(pinnedKey, data, sig)) throw BundleRejected("bad signature")

        val payload = try {
            Json.parseToJsonElement(data.toString(Charsets.UTF_8)).jsonObject
        } catch (e: Exception) {
            throw BundleRejected("payload is not JSON")
        }
        val v = payload["version"] as? JsonPrimitive
        val version = v?.takeIf { !it.isString && WHOLE.matches(it.content) }?.content?.toLongOrNull()
            ?: throw BundleRejected("payload has no version")
        if (version <= highestVersion) {
            throw BundleRejected("version $version is not newer than $highestVersion")
        }
        val parsed = try {
            Payload(
                version = version,
                issuedAt = payload["issued_at"]?.jsonPrimitive?.contentOrNull ?: "",
                rules = Rules.parse(payload["rules"]!!.jsonObject),
                released = payload["released"]?.jsonArray?.map { it.jsonPrimitive.content } ?: emptyList(),
            )
        } catch (e: Exception) {
            throw BundleRejected("rules could not be read: ${e.message}")
        }
        highestVersion = version
        return parsed
    }

    private fun stringField(obj: JsonObject, name: String): String =
        (obj[name] as? JsonPrimitive)?.takeIf { it.isString }?.content
            ?: throw IllegalArgumentException("missing $name")

    private companion object {
        val WHOLE = Regex("-?[0-9]+")
    }
}
