package com.fortress.agent.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.io.File
import java.security.KeyFactory
import java.security.Signature
import java.security.spec.PKCS8EncodedKeySpec
import java.security.spec.X509EncodedKeySpec
import java.time.Instant
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue
import kotlin.test.fail

/** testdata/fortress_vectors.json, made by Core's reference code: this Agent must agree with it. */
class VectorsTest {
    private val v: JsonObject = Json.parseToJsonElement(
        File(System.getProperty("fortress.vectors") ?: error("fortress.vectors not set")).readText(),
    ).jsonObject

    private fun s(o: JsonObject, k: String) = o[k]!!.jsonPrimitive.content

    @Test
    fun bundles() {
        val pub = b64d(s(v["core_key"]!!.jsonObject, "public_key"))
        assertEquals(s(v["core_key"]!!.jsonObject, "key_id"), keyId(pub))
        for (c in v["bundle_cases"]!!.jsonArray.map { it.jsonObject }) {
            val name = s(c, "name")
            val verifier = BundleVerifier(pub, c["highest_held"]!!.jsonPrimitive.long)
            if (c["accept"]!!.jsonPrimitive.boolean) {
                val p = verifier.accept(c["envelope"]!!.jsonObject)
                assertEquals(c["version"]!!.jsonPrimitive.long, p.version, name)
                assertEquals(p.version, verifier.highestVersion, name)
            } else {
                assertFailsWith<BundleRejected>(name) { verifier.accept(c["envelope"]!!.jsonObject) }
            }
        }
    }

    @Test
    fun blocking() {
        val rules = Rules.parse(v["rules"]!!.jsonObject)
        for (c in v["match_cases"]!!.jsonArray.map { it.jsonObject }) {
            val at = Instant.parse(s(c, "at"))
            val kind = Kind.of(s(c, "kind"))
            val blocked = if (kind == Kind.DOMAINS) {
                Evaluator.isDomainBlocked(rules, s(c, "device"), s(c, "item"), at)
            } else {
                Evaluator.isAppBlocked(rules, s(c, "device"), kind, s(c, "item"), at)
            }
            assertEquals(c["blocked"]!!.jsonPrimitive.boolean, blocked, "${s(c, "why")} (${s(c, "at")})")
        }
    }

    @Test
    fun domains() {
        for (c in v["domain_cases"]!!.jsonArray.map { it.jsonObject }) {
            assertEquals(c["match"]!!.jsonPrimitive.boolean, Evaluator.domainMatches(s(c, "host"), s(c, "pattern")),
                "${s(c, "host")} vs ${s(c, "pattern")}")
        }
    }

    @Test
    fun enrolmentProofs() {
        val e = v["enrolment"]!!.jsonObject
        assertEquals(s(e, "normalized_code"), Protocol.normalizeCode(s(e, "code")))
        val k = Protocol.enrolKey(s(e, "code"))
        assertEquals(s(e, "key_hex"), hex(k))
        assertEquals(s(e, "agent_proof"), Protocol.agentProof(k, s(e, "device_id"), s(e, "public_key"), s(e, "nonce")))
        assertEquals(
            s(e, "core_proof"),
            Protocol.coreProof(k, s(e, "device_id"), s(e, "public_key"), s(e, "nonce"), s(e, "core_public_key")),
        )
    }

    @Test
    fun signedRequest() {
        val r = v["signed_request"]!!.jsonObject
        val msg = Protocol.requestMessage(
            s(r, "method"), s(r, "path"), s(r, "device_id"), s(r, "time"), s(r, "nonce"),
            s(r, "body").toByteArray(),
        )
        assertEquals(s(r, "message"), msg.toString(Charsets.UTF_8))

        val kf = KeyFactory.getInstance("EC")
        val pub = kf.generatePublic(X509EncodedKeySpec(b64d(s(r, "device_public_key"))))
        // Core's signature verifies here, so the encodings agree…
        val verify = Signature.getInstance("SHA256withECDSA").apply { initVerify(pub); update(msg) }
        assertTrue(verify.verify(b64d(s(r, "signature"))), "Python-made signature must verify in Java")
        // …and a Java-made signature over the same bytes verifies too (what Core will check).
        val priv = kf.generatePrivate(PKCS8EncodedKeySpec(b64d(s(r, "device_private_key_pkcs8"))))
        val sig = Signature.getInstance("SHA256withECDSA").apply { initSign(priv); update(msg) }.sign()
        val check = Signature.getInstance("SHA256withECDSA").apply { initVerify(pub); update(msg) }
        if (!check.verify(sig)) fail("Java signature did not verify")
    }
}
