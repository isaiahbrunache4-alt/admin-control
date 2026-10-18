package com.fortress.agent

import android.annotation.SuppressLint
import android.app.AlarmManager
import android.app.PendingIntent
import android.app.admin.DeviceAdminReceiver
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.SystemClock
import android.util.Log
import com.fortress.agent.core.Agent
import com.fortress.agent.core.SyncResult
import java.time.Instant
import java.util.concurrent.Executors

/** One Agent per process, wired to the Keystore, boot storage and device policy. */
object Runtime {
    private const val TAG = "Fortress"
    private const val SYNC_EVERY_MS = 15 * 60 * 1000L
    const val ACTION_APPLY = "com.fortress.agent.APPLY"
    const val ACTION_SYNC = "com.fortress.agent.SYNC"

    /** Network and Keystore work happens here, one job at a time. */
    val worker = Executors.newSingleThreadExecutor()

    @Volatile private var agent: Agent? = null

    fun agent(context: Context): Agent = agent ?: synchronized(this) {
        agent ?: Agent(
            FileStateStore(context.applicationContext),
            KeystoreSigner(),
            BuildConfig.VERSION_NAME,
        ).also { agent = it }
    }

    /** Enforce the rules now and wake again at the next schedule boundary (A3, A4). */
    fun apply(context: Context): Applied {
        val enforcer = Enforcer(context)
        val applied = enforcer.apply(agent(context), Instant.now())
        scheduleApply(context, applied.nextChange)
        scheduleSync(context)
        Log.i(TAG, "applied: owner=${applied.deviceOwner} blocked=${applied.blocked} next=${applied.nextChange}")
        return applied
    }

    /** Check in with Core; apply at once if the rules changed (A2, A5). Off the main thread. */
    fun sync(context: Context): SyncResult {
        val result = agent(context).sync(enforcing = Enforcer(context).isDeviceOwner)
        if (result.rulesChanged || result.state.released) apply(context)
        result.error?.let { Log.w(TAG, "sync: $it") }
        return result
    }

    private fun pending(context: Context, action: String, code: Int): PendingIntent =
        PendingIntent.getBroadcast(
            context, code,
            Intent(context, AlarmReceiver::class.java).setAction(action),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

    // USE_EXACT_ALARM (manifest) is granted at install on Android 13+; lint only knows
    // SCHEDULE_EXACT_ALARM. canScheduleExactAlarms() guards the call either way.
    @SuppressLint("MissingPermission")
    private fun scheduleApply(context: Context, at: Instant?) {
        val alarms = context.getSystemService(AlarmManager::class.java)
        val pi = pending(context, ACTION_APPLY, 1)
        if (at == null) {
            alarms.cancel(pi)
            return
        }
        // A second late is fine; a minute late is not: wake exactly at the boundary.
        val ms = at.toEpochMilli() + 1000
        if (alarms.canScheduleExactAlarms()) {
            alarms.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, ms, pi)
        } else {
            alarms.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, ms, pi)
        }
    }

    private fun scheduleSync(context: Context) {
        context.getSystemService(AlarmManager::class.java).setInexactRepeating(
            AlarmManager.ELAPSED_REALTIME_WAKEUP,
            SystemClock.elapsedRealtime() + 60_000,
            SYNC_EVERY_MS,
            pending(context, ACTION_SYNC, 2),
        )
    }

    /** Apply on the main thread (fast, local), then sync in the background. */
    fun applyThenSync(receiver: BroadcastReceiver, context: Context, sync: Boolean = true) {
        apply(context)
        if (!sync) return
        val done = receiver.goAsync()
        worker.execute {
            try {
                sync(context)
            } catch (e: Exception) {
                Log.w(TAG, "sync failed", e)
            } finally {
                done.finish()
            }
        }
    }
}

class AlarmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        Runtime.applyThenSync(this, context, sync = intent.action == Runtime.ACTION_SYNC)
    }
}

/** Boot (including before the first unlock), app update, and clock or time-zone changes. */
class SystemEventsReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        // Before the first unlock the network and Keystore may not be ready: just enforce.
        val locked = intent.action == Intent.ACTION_LOCKED_BOOT_COMPLETED
        Runtime.applyThenSync(this, context, sync = !locked)
    }
}

class FortressAdminReceiver : DeviceAdminReceiver() {
    override fun onEnabled(context: Context, intent: Intent) {
        Runtime.apply(context)
    }
}
