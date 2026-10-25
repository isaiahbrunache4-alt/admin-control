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
 * App stores Android will not suspend are hidden instead, and installs only come from a
 * computer over USB (adb), so nothing new arrives without going through the PC.
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

    /** App stores that Android refuses to let a device owner suspend (the Play Store is
     * the system's install verifier). While one is blocked it is hidden instead: it is
     * gone from the device until the block ends, so nothing can be browsed or installed. */
    private val hideInstead = setOf(PLAY_STORE)

    /** Kept on while enrolled; all lifted when the device is released. */
    private val lockdown = listOf(
        // No app (Chrome, Files, Drive) may install an APK. adb from a computer is exempt,
        // so the only ways in are USB from the PC or a store the Console has unblocked.
        UserManager.DISALLOW_INSTALL_UNKNOWN_SOURCES_GLOBALLY,
        // No reset from Settings. A reset from the boot menu cannot be stopped by any app;
        // the device then stops checking in, which Core and the Beeminder check notice.
        UserManager.DISALLOW_FACTORY_RESET,
        // Safe mode starts the device with Fortress switched off.
        UserManager.DISALLOW_SAFE_BOOT,
        // A second user profile would have no Fortress on it.
        UserManager.DISALLOW_ADD_USER,
    )

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
        lockDown()

        val deviceId = state.deviceId
        val want = if (payload != null && deviceId != null) {
            Evaluator.packagesToBlock(payload.rules, deviceId, now, neverBlock)
        } else {
            emptySet()
        }
        val hideWant = want intersect hideInstead
        val suspendWant = want - hideWant
        val had = suspended
        val lift = had - suspendWant
        if (lift.isNotEmpty()) dpm.setPackagesSuspended(admin, lift.toTypedArray(), false)
        // Re-assert every wanted package each time: it is cheap, and it catches an app
        // installed since the last run.
        val failed = if (suspendWant.isNotEmpty()) dpm.setPackagesSuspended(admin, suspendWant.toTypedArray(), true).toSet() else emptySet()
        val suspendedNow = suspendWant - failed
        prefs.edit().putStringSet(KEY_SUSPENDED, suspendedNow).apply()
        val hiddenBefore = hideInstead.filter { isHidden(it) }.toSet()
        val hiddenNow = syncHidden(hideWant)
        val blocked = suspendedNow + hiddenNow
        val notBlockable = failed + (hideWant - hiddenNow)

        if (suspendedNow != had || hiddenNow != hiddenBefore) {
            val added = (suspendedNow - had) + (hiddenNow - hiddenBefore)
            val removed = (had - suspendedNow) + (hiddenBefore - hiddenNow)
            if (added.isNotEmpty()) agent.log("apps_blocked", added.sorted().joinToString(", "))
            if (removed.isNotEmpty()) agent.log("apps_unblocked", removed.sorted().joinToString(", "))
        }
        val ids = if (payload != null && deviceId != null) Evaluator.activeBlocks(payload.rules, deviceId, now).scheduleIds else emptyList()
        val next = if (payload != null && deviceId != null) Evaluator.nextChange(payload.rules, deviceId, now) else null
        // `notBlockable` includes apps that are not installed here, which is normal.
        return Applied(true, blocked, notBlockable, ids, next)
    }

    private fun isHidden(pkg: String): Boolean =
        try { dpm.isApplicationHidden(admin, pkg) } catch (e: Exception) { false }

    /** Hide each store in [wanted], unhide the others. Returns the ones hidden now. */
    private fun syncHidden(wanted: Set<String>): Set<String> {
        val hidden = mutableSetOf<String>()
        for (pkg in hideInstead) {
            val want = pkg in wanted
            if (isHidden(pkg) != want) {
                try {
                    dpm.setApplicationHidden(admin, pkg, want)
                } catch (e: Exception) {
                    Log.w(TAG, "hide $pkg", e)
                }
            }
            if (want && isHidden(pkg)) hidden += pkg
        }
        return hidden
    }

    /** Installs only via the PC; no reset, safe mode or new users while enrolled. */
    private fun lockDown() {
        for (r in lockdown) dpm.addUserRestriction(admin, r)
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
        syncHidden(emptySet())
        for (r in lockdown) dpm.clearUserRestriction(admin, r)
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
        const val PLAY_STORE = "com.android.vending"
        const val CHROME_DOH_POLICY = "DnsOverHttpsMode"
    }
}
