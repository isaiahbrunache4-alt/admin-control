package com.fortress.agent

import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.os.UserManager
import com.fortress.agent.core.Agent
import com.fortress.agent.core.Evaluator
import java.time.Instant

data class Applied(
    val deviceOwner: Boolean,
    val blocked: Set<String>,
    val notBlockable: Set<String>,
    val scheduleIds: List<String>,
    val nextChange: Instant?,
)

/**
 * Turns the rules into Android policy (Spec 01 §8.2). As device owner, blocked apps are
 * suspended: they stay installed but will not open, and the suspension survives reboots.
 */
class Enforcer(private val context: Context) {
    private val dpm = context.getSystemService(DevicePolicyManager::class.java)
    private val admin = ComponentName(context, FortressAdminReceiver::class.java)
    private val prefs = context.bootStorage().getSharedPreferences("enforcer", Context.MODE_PRIVATE)

    val isDeviceOwner: Boolean get() = dpm.isDeviceOwnerApp(context.packageName)

    /** Never suspended, whatever the rules say: Fortress itself, and Settings (so the
     * network can always be fixed). Android also refuses to suspend the launcher,
     * dialer, SMS app and installer. */
    private val neverBlock = setOf(context.packageName, "com.android.settings")

    /** Currently suspended by Fortress. */
    val suspended: Set<String> get() = prefs.getStringSet(KEY_SUSPENDED, emptySet())!!.toSet()

    fun apply(agent: Agent, now: Instant = Instant.now()): Applied {
        val state = agent.state
        val payload = agent.currentPayload()
        if (!isDeviceOwner) {
            return Applied(false, emptySet(), emptySet(), emptyList(), null)
        }
        if (state.released) {
            standDown(agent)
            return Applied(true, emptySet(), emptySet(), emptyList(), null)
        }
        hardenClock()

        val deviceId = state.deviceId
        val want = if (payload != null && deviceId != null) {
            Evaluator.packagesToBlock(payload.rules, deviceId, now, neverBlock)
        } else {
            emptySet()
        }
        val had = suspended
        val lift = had - want
        if (lift.isNotEmpty()) dpm.setPackagesSuspended(admin, lift.toTypedArray(), false)
        // Re-assert every wanted package each time: it is cheap, and it catches an app
        // installed since the last run.
        val failed = if (want.isNotEmpty()) dpm.setPackagesSuspended(admin, want.toTypedArray(), true).toSet() else emptySet()
        val blocked = want - failed
        prefs.edit().putStringSet(KEY_SUSPENDED, blocked).apply()

        if (blocked != had) {
            val added = blocked - had
            val removed = had - blocked
            if (added.isNotEmpty()) agent.log("apps_blocked", added.sorted().joinToString(", "))
            if (removed.isNotEmpty()) agent.log("apps_unblocked", removed.sorted().joinToString(", "))
        }
        val ids = if (payload != null && deviceId != null) Evaluator.activeBlocks(payload.rules, deviceId, now).scheduleIds else emptyList()
        val next = if (payload != null && deviceId != null) Evaluator.nextChange(payload.rules, deviceId, now) else null
        // `failed` includes apps that are not installed here, which is normal.
        return Applied(true, blocked, failed, ids, next)
    }

    /** Blocks must follow real time: keep network time on and the clock out of reach. */
    private fun hardenClock() {
        if (!dpm.getAutoTimeEnabled(admin)) dpm.setAutoTimeEnabled(admin, true)
        dpm.addUserRestriction(admin, UserManager.DISALLOW_CONFIG_DATE_TIME)
    }

    /** A signed release names this device (contract A6): lift everything and step down. */
    @Suppress("DEPRECATION")
    private fun standDown(agent: Agent) {
        val had = suspended
        if (had.isNotEmpty()) dpm.setPackagesSuspended(admin, had.toTypedArray(), false)
        prefs.edit().remove(KEY_SUSPENDED).apply()
        dpm.clearUserRestriction(admin, UserManager.DISALLOW_CONFIG_DATE_TIME)
        agent.log("released", "lifted ${had.size} app blocks; no longer device owner")
        // Deprecated for third parties, but still how a device owner removes itself.
        dpm.clearDeviceOwnerApp(context.packageName)
    }

    private companion object {
        const val KEY_SUSPENDED = "suspended"
    }
}
