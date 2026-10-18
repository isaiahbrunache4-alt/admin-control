package com.fortress.agent.core

/** The Agent protocol's crypto (docs/agent_protocol.md §2, §3). */
object Protocol {
    const val ENROL_PATH = "/agent/v1/enrol"
    const val BUNDLE_PATH = "/agent/v1/bundle"
    const val CHECKIN_PATH = "/agent/v1/checkin"
    const val DEFAULT_PORT = 47801

    /** Upper-case, letters and digits only: "mfa4d 52anu" → "MFA4D52ANU". */
    fun normalizeCode(code: String): String = code.uppercase().filter { it.isLetterOrDigit() }

    fun enrolKey(code: String): ByteArray = sha256("fortress-enrol-v1:${normalizeCode(code)}".toByteArray(Charsets.UTF_8))

    private fun mac(key: ByteArray, vararg parts: String): String =
        b64e(hmacSha256(key, (listOf("fortress-enrol-v1") + parts).joinToString("\n").toByteArray(Charsets.UTF_8)))

    fun agentProof(key: ByteArray, deviceId: String, publicKey: String, nonce: String): String =
        mac(key, "agent", deviceId, publicKey, nonce)

    fun coreProof(key: ByteArray, deviceId: String, publicKey: String, nonce: String, corePublicKey: String): String =
        mac(key, "core", deviceId, publicKey, nonce, corePublicKey)

    /** The exact bytes a device signs for each request. */
    fun requestMessage(method: String, path: String, deviceId: String, time: String, nonce: String, body: ByteArray): ByteArray =
        listOf("fortress-agent-v1", method.uppercase(), path, deviceId, time, nonce, hex(sha256(body)))
            .joinToString("\n")
            .toByteArray(Charsets.UTF_8)
}

/** The device's own key: ECDSA P-256. On Android it lives in the Keystore and never leaves it. */
interface DeviceSigner {
    /** X.509 SubjectPublicKeyInfo, DER. */
    val publicKey: ByteArray

    /** DER-encoded ECDSA signature over SHA-256 of [data]. */
    fun sign(data: ByteArray): ByteArray
}
