package com.fortress.agent

import android.app.Activity
import android.os.Bundle
import android.widget.TextView

/**
 * Health Connect only lets an app ask for health permissions if it explains what it does
 * with them. Shown from Health Connect's permission screens.
 */
class HealthPrivacyActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val pad = (24 * resources.displayMetrics.density).toInt()
        setContentView(TextView(this).apply {
            setPadding(pad, pad, pad, pad)
            textSize = 16f
            text = "Fortress Agent reads one thing from Health Connect: your step total for each of " +
                "the last 8 days. It sends those totals to Fortress Core on your own PC at each " +
                "check-in, where the Beeminder check uses them. It reads nothing else, writes " +
                "nothing, and sends nothing anywhere but your PC."
        })
    }
}
