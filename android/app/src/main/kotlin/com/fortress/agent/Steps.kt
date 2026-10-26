package com.fortress.agent

import android.annotation.TargetApi
import android.content.Context
import android.content.pm.PackageManager
import android.health.connect.AggregateRecordsRequest
import android.health.connect.AggregateRecordsResponse
import android.health.connect.HealthConnectException
import android.health.connect.HealthConnectManager
import android.health.connect.LocalTimeRangeFilter
import android.health.connect.datatypes.StepsRecord
import android.os.Build
import android.os.OutcomeReceiver
import android.util.Log
import com.fortress.agent.core.STEPS_SOURCE
import com.fortress.agent.core.stepsReport
import java.time.Instant
import java.time.LocalDate
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/**
 * Daily step totals from Android's Health Connect (Android 14+), passed on to Core as the
 * "steps" report for the PC's Beeminder check. Gadgetbridge writes the watch's steps there;
 * Health Connect merges every source into one total per day. Read-only: Fortress never
 * writes health data, and reads nothing but the daily step count.
 */
object Steps {
    const val READ_STEPS = "android.permission.health.READ_STEPS"
    const val READ_IN_BACKGROUND = "android.permission.health.READ_HEALTH_DATA_IN_BACKGROUND"
    val PERMISSIONS = arrayOf(READ_STEPS, READ_IN_BACKGROUND)
    private const val DAYS = 8L
    private const val TAG = "Fortress"

    fun supported(): Boolean = Build.VERSION.SDK_INT >= 34

    fun allowed(context: Context): Boolean =
        supported() && context.checkSelfPermission(READ_STEPS) == PackageManager.PERMISSION_GRANTED

    fun allowedInBackground(context: Context): Boolean =
        supported() && context.checkSelfPermission(READ_IN_BACKGROUND) == PackageManager.PERMISSION_GRANTED

    /** Read the last [DAYS] local days and keep them as the "steps" report. Never throws. */
    fun report(context: Context) {
        if (!allowed(context)) return
        try {
            val today = LocalDate.now()
            val days = (DAYS - 1 downTo 0L).map { back ->
                val day = today.minusDays(back)
                day to total(context, day)
            }
            Runtime.agent(context).report(STEPS_SOURCE, stepsReport(days, Instant.now()))
        } catch (e: Exception) {
            Log.w(TAG, "steps not read: ${e.message}")
        }
    }

    @TargetApi(34)
    private fun total(context: Context, day: LocalDate): Long {
        val hc = context.getSystemService(HealthConnectManager::class.java)
            ?: throw IllegalStateException("Health Connect isn't available")
        val filter = LocalTimeRangeFilter.Builder()
            .setStartTime(day.atStartOfDay())
            .setEndTime(day.plusDays(1).atStartOfDay())
            .build()
        val request = AggregateRecordsRequest.Builder<Long>(filter)
            .addAggregationType(StepsRecord.STEPS_COUNT_TOTAL)
            .build()
        val done = CountDownLatch(1)
        val count = AtomicReference(0L)
        val failure = AtomicReference<Exception?>(null)
        hc.aggregate(request, Executor { it.run() },
            object : OutcomeReceiver<AggregateRecordsResponse<Long>, HealthConnectException> {
                override fun onResult(result: AggregateRecordsResponse<Long>) {
                    count.set(result.get(StepsRecord.STEPS_COUNT_TOTAL) ?: 0L)
                    done.countDown()
                }

                override fun onError(error: HealthConnectException) {
                    failure.set(error)
                    done.countDown()
                }
            })
        if (!done.await(20, TimeUnit.SECONDS)) throw IllegalStateException("Health Connect didn't answer")
        failure.get()?.let { throw it }
        return count.get()
    }
}
