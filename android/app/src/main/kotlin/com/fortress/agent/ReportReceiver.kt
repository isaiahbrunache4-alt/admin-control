package com.fortress.agent

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

/**
 * Other apps on this device hand Fortress a small summary to pass on to Core, for the
 * PC's Beeminder check. Block Trainer sends its logged workouts and bodyweight:
 *
 *   Intent("com.fortress.agent.REPORT")
 *       .setComponent(ComponentName("com.fortress.agent", "com.fortress.agent.ReportReceiver"))
 *       .putExtra("source", "block_trainer").putExtra("json", "{...}")
 *
 * Only the latest report per source is kept, and it goes out with each check-in. Fortress
 * never acts on a report itself.
 */
class ReportReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != ACTION_REPORT) return
        val source = intent.getStringExtra(EXTRA_SOURCE) ?: return
        val json = intent.getStringExtra(EXTRA_JSON) ?: return
        val done = goAsync()
        Runtime.worker.execute {
            try {
                Runtime.agent(context).report(source, json)
            } catch (e: Exception) {
                Log.w("Fortress", "report from $source refused: ${e.message}")
            } finally {
                done.finish()
            }
        }
    }

    companion object {
        const val ACTION_REPORT = "com.fortress.agent.REPORT"
        const val EXTRA_SOURCE = "source"
        const val EXTRA_JSON = "json"
    }
}
