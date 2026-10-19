package com.fortress.agent

import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.os.Bundle
import android.os.UserManager
import android.util.Log
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
        keepFilterOn()

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

    /**
     * The website filter (Spec 01 §8.1): Fortress is the always-on VPN, so Android starts
     * it at boot and restarts it, and VPN settings cannot be changed on the device.
     * Ways around a DNS filter are closed: Private DNS stays on "automatic" (strict mode
     * would send lookups past it), and Chrome's own secure DNS is turned off.
     */
    private fun keepFilterOn() {
        if (dpm.getAlwaysOnVpnPackage(admin) != context.packageName) {
            try {
                // Not lockdown: if the filter ever fails, the network keeps working
                // unfiltered rather than not at all. Android restarts it either way.
                dpm.setAlwaysOnVpnPackage(admin, context.packageName, false)
            } catch (e: Exception) {
                Log.w(TAG, "always-on VPN", e)
            }
        }
        dpm.addUserRestriction(admin, UserManager.DISALLOW_CONFIG_VPN)
        dpm.addUserRestriction(admin, UserManager.DISALLOW_CONFIG_PRIVATE_DNS)
        if (dpm.getGlobalPrivateDnsMode(admin) != DevicePolicyManager.PRIVATE_DNS_MODE_OPPORTUNISTIC) {
            dpm.setGlobalPrivateDnsModeOpportunistic(admin)
        }
        val current = dpm.getApplicationRestrictions(admin, CHROME)
        if (current.getString(CHROME_DOH_POLICY) != "off") {
            dpm.setApplicationRestrictions(admin, CHROME, Bundle().apply { putString(CHROME_DOH_POLICY, "off") })
        }
    }

    /** A signed release names this device (contract A6): lift everything and step down. */
    @Suppress("DEPRECATION")
    private fun standDown(agent: Agent) {
        val had = suspended
        if (had.isNotEmpty()) dpm.setPackagesSuspended(admin, had.toTypedArray(), false)
        prefs.edit().remove(KEY_SUSPENDED).apply()
        dpm.clearUserRestriction(admin, UserManager.DISALLOW_CONFIG_DATE_TIME)
        // The website filter and what kept it on.
        try {
            dpm.setAlwaysOnVpnPackage(admin, null, false)
        } catch (e: Exception) {
            Log.w(TAG, "clear always-on VPN", e)
        }
        FilterVpnService.stop(context)
        dpm.clearUserRestriction(admin, UserManager.DISALLOW_CONFIG_VPN)
        dpm.clearUserRestriction(admin, UserManager.DISALLOW_CONFIG_PRIVATE_DNS)
        dpm.setApplicationRestrictions(admin, CHROME, Bundle())
        agent.log("released", "lifted ${had.size} app blocks and the website filter; no longer device owner")
        // Deprecated for third parties, but still how a device owner removes itself.
        dpm.clearDeviceOwnerApp(context.packageName)
    }

    private companion object {
        const val TAG = "Fortress"
        const val KEY_SUSPENDED = "suspended"
        const val CHROME = "com.android.chrome"
        const val CHROME_DOH_POLICY = "DnsOverHttpsMode"
    }
}
