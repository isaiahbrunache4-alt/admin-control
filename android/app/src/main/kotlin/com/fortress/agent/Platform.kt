package com.fortress.agent

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import com.fortress.agent.core.AgentState
import com.fortress.agent.core.DeviceSigner
import com.fortress.agent.core.StateStore
import java.io.File
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.Signature
import java.security.spec.ECGenParameterSpec

/**
 * The device key (docs/agent_protocol.md §2): ECDSA P-256 in the Android Keystore, in
 * StrongBox where the device has it (the Pixel 8a's Titan M2). It never leaves the
 * hardware, so a copy of this device's files cannot pretend to be it.
 */
class KeystoreSigner : DeviceSigner {
    private val keyStore = KeyStore.getInstance(PROVIDER).apply { load(null) }

    private fun entry(): KeyStore.PrivateKeyEntry {
        (keyStore.getEntry(ALIAS, null) as? KeyStore.PrivateKeyEntry)?.let { return it }
        try {
            generate(strongBox = true)
        } catch (e: Exception) {
            // No StrongBox on this device: the TEE-backed Keystore is the next best.
            generate(strongBox = false)
        }
        return keyStore.getEntry(ALIAS, null) as KeyStore.PrivateKeyEntry
    }

    private fun generate(strongBox: Boolean) {
        val spec = KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_SIGN)
            .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
            .setDigests(KeyProperties.DIGEST_SHA256)
            .setIsStrongBoxBacked(strongBox)
            .build()
        KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, PROVIDER).apply { initialize(spec) }.generateKeyPair()
    }

    override val publicKey: ByteArray get() = entry().certificate.publicKey.encoded

    override fun sign(data: ByteArray): ByteArray =
        Signature.getInstance("SHA256withECDSA").run {
            initSign(entry().privateKey)
            update(data)
            sign()
        }

    /** A fresh key for a fresh enrolment. */
    fun reset() = keyStore.deleteEntry(ALIAS)

    private companion object {
        const val PROVIDER = "AndroidKeyStore"
        const val ALIAS = "fortress-device-key"
    }
}

/** Device-protected storage, so blocks are re-applied at boot before the first unlock. */
fun Context.bootStorage(): Context = createDeviceProtectedStorageContext()

class FileStateStore(context: Context) : StateStore {
    private val file = AtomicFile(File(context.bootStorage().filesDir, "agent_state.json"))

    override fun load(): AgentState =
        if (file.baseFile.exists()) AgentState.fromJson(file.readFully().toString(Charsets.UTF_8)) else AgentState()

    override fun save(state: AgentState) {
        val out = file.startWrite()
        try {
            out.write(state.toJson().toByteArray(Charsets.UTF_8))
            file.finishWrite(out)
        } catch (e: Exception) {
            file.failWrite(out)
            throw e
        }
    }
}
