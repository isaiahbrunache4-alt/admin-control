package com.fortress.agent.core

import java.security.MessageDigest
import java.util.Base64
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/** Standard, padded base64, as Core writes it. Decoding is strict, like Core's. */
internal fun b64e(data: ByteArray): String = Base64.getEncoder().encodeToString(data)

internal fun b64d(text: String): ByteArray = Base64.getDecoder().decode(text)

internal fun sha256(data: ByteArray): ByteArray = MessageDigest.getInstance("SHA-256").digest(data)

internal fun hex(data: ByteArray): String = data.joinToString("") { "%02x".format(it) }

internal fun hmacSha256(key: ByteArray, data: ByteArray): ByteArray =
    Mac.getInstance("HmacSHA256").run {
        init(SecretKeySpec(key, "HmacSHA256"))
        doFinal(data)
    }

/** Compare secrets without leaking where they differ. */
internal fun constantTimeEquals(a: String, b: String): Boolean =
    MessageDigest.isEqual(a.toByteArray(Charsets.UTF_8), b.toByteArray(Charsets.UTF_8))

/** Core's key id: the first 16 hex characters of SHA-256 of the raw public key. */
fun keyId(publicKey: ByteArray): String = hex(sha256(publicKey)).substring(0, 16)
