package com.fortress.agent

import android.app.Activity
import android.content.Intent
import android.net.VpnService
import android.graphics.Typeface
import android.os.Bundle
import android.text.InputType
import android.view.View
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import com.fortress.agent.core.CoreError
import com.fortress.agent.core.keyId
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/**
 * What this device is doing, read-only. There is deliberately no unlock or edit here:
 * every change is made in the Console on the PC (Spec 01 §6.2). Before enrolment it
 * asks for the Core address, the device id and the one-time enrolment code.
 */
class MainActivity : Activity() {
    private lateinit var status: TextView
    private lateinit var enrolForm: LinearLayout
    private lateinit var address: EditText
    private lateinit var deviceId: EditText
    private lateinit var code: EditText
    private lateinit var message: TextView
    private lateinit var startFilter: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val pad = (16 * resources.displayMetrics.density).toInt()
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad * 2, pad, pad)
        }
        column.addView(TextView(this).apply {
            text = getString(R.string.app_name)
            textSize = 26f
            setTypeface(typeface, Typeface.BOLD)
        })
        status = TextView(this).apply {
            textSize = 16f
            setTextIsSelectable(true)
            setPadding(0, pad, 0, pad)
        }
        column.addView(status)

        enrolForm = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        enrolForm.addView(TextView(this).apply {
            text = "Enrol this device. In the Console on the PC: Devices → Enrol. It shows the address, the device id and a one-time code."
            setPadding(0, 0, 0, pad / 2)
        })
        address = field("Core address, e.g. 192.168.1.20", InputType.TYPE_TEXT_VARIATION_URI)
        deviceId = field("Device id, e.g. tablet", InputType.TYPE_CLASS_TEXT)
        code = field("Enrolment code, e.g. MFA4D-52ANU", InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS)
        listOf(address, deviceId, code).forEach(enrolForm::addView)
        enrolForm.addView(Button(this).apply {
            text = "Enrol"
            setOnClickListener { enrol() }
        })
        column.addView(enrolForm)

        // Normally Android starts the filter itself (always-on VPN). If this device asks
        // for the one-time VPN approval instead, this gives it.
        startFilter = Button(this).apply {
            text = "Start website filter"
            visibility = View.GONE
            setOnClickListener { startWebsiteFilter() }
        }
        column.addView(startFilter)
        column.addView(Button(this).apply {
            text = "Check in now"
            setOnClickListener { syncNow() }
        })
        message = TextView(this).apply { setPadding(0, pad / 2, 0, 0) }
        column.addView(message)

        setContentView(ScrollView(this).apply { addView(column, MATCH_PARENT, WRAP_CONTENT) })
    }

    override fun onResume() {
        super.onResume()
        refresh()
    }

    private fun field(hint: String, type: Int) = EditText(this).apply {
        this.hint = hint
        inputType = InputType.TYPE_CLASS_TEXT or type
        isSingleLine = true
    }

    private fun refresh() {
        Runtime.worker.execute {
            val applied = Runtime.apply(this)
            val agent = Runtime.agent(this)
            val s = agent.state
            val payload = agent.currentPayload()
            val text = buildString {
                appendLine(
                    if (applied.deviceOwner) "✓ Device owner: blocking is enforced."
                    else "✗ Not device owner: nothing is blocked yet.\n   Set up from the PC:\n   adb shell dpm set-device-owner com.fortress.agent/.FortressAdminReceiver",
                )
                appendLine()
                if (!s.enrolled) {
                    appendLine("Not enrolled with Fortress yet.")
                } else {
                    appendLine("Device: ${s.deviceId}")
                    appendLine("Core: ${s.coreUrl}")
                    appendLine("Core key: ${keyId(android.util.Base64.decode(s.corePublicKey, android.util.Base64.DEFAULT))}")
                    appendLine("Rules version: ${s.highestVersion}")
                    if (s.released) appendLine("Released by the Console: Fortress has stood down.")
                    appendLine()
                    appendLine(
                        if (applied.scheduleIds.isEmpty()) "No blocks in force now."
                        else "Blocks in force now: " + applied.scheduleIds.joinToString { id ->
                            payload?.rules?.schedules?.firstOrNull { it.id == id }?.list ?: id
                        },
                    )
                    appendLine(if (applied.blocked.isEmpty()) "No apps blocked." else "Apps blocked: " + applied.blocked.sorted().joinToString())
                    appendLine(
                        if (FilterVpnService.running) "Website filter: on"
                        else "Website filter: off (Android starts it as the always-on VPN)",
                    )
                    applied.nextChange?.let { appendLine("Next change: ${local(it)}") }
                    appendLine()
                    appendLine("Last check-in: ${s.lastSync?.let { local(Instant.parse(it)) } ?: "never"}")
                    s.lastError?.let { appendLine("Last problem: $it") }
                }
            }
            runOnUiThread {
                status.text = text
                enrolForm.visibility = if (s.enrolled) View.GONE else View.VISIBLE
                startFilter.visibility =
                    if (applied.deviceOwner && s.enrolled && !s.released && !FilterVpnService.running) View.VISIBLE else View.GONE
            }
        }
    }

    private fun enrol() {
        val a = address.text.toString()
        val d = deviceId.text.toString().trim()
        val c = code.text.toString()
        say("Enrolling…")
        Runtime.worker.execute {
            val outcome = try {
                Runtime.agent(this).enrol(a, d, c)
                Runtime.apply(this)
                "Enrolled. This device now follows Fortress."
            } catch (e: CoreError) {
                when (e.kind) {
                    "bad_proof" -> "Wrong code. Check it against the Console (5 wrong tries cancel it)."
                    "no_enrolment" -> "No enrolment is waiting for \"$d\". Check the device id, or make a new code."
                    "expired" -> "That code has expired. Make a new one in the Console."
                    "bad_core_proof" -> "The PC at that address could not prove it made this code. Not enrolled."
                    else -> e.message ?: "Enrolment failed."
                }
            } catch (e: IllegalArgumentException) {
                e.message ?: "Check the address."
            }
            runOnUiThread { say(outcome); refresh() }
        }
    }

    private fun syncNow() {
        say("Checking in…")
        Runtime.worker.execute {
            val r = Runtime.sync(this)
            runOnUiThread {
                say(r.error ?: if (r.rulesChanged) "New rules received and applied." else "Up to date.")
                refresh()
            }
        }
    }

    private fun startWebsiteFilter() {
        val consent = VpnService.prepare(this)
        if (consent != null) {
            @Suppress("DEPRECATION")
            startActivityForResult(consent, REQUEST_VPN)
        } else {
            onVpnApproved()
        }
    }

    @Deprecated("Activity result API needs AndroidX; this app has no dependencies")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        @Suppress("DEPRECATION")
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQUEST_VPN && resultCode == RESULT_OK) onVpnApproved()
    }

    private fun onVpnApproved() {
        startService(Intent(this, FilterVpnService::class.java))
        message.postDelayed({ refresh() }, 1500)
    }

    private fun say(text: String) {
        message.text = text
    }

    private fun local(t: Instant): String = FORMAT.format(t.atZone(ZoneId.systemDefault()))

    private companion object {
        const val REQUEST_VPN = 1
        val FORMAT: DateTimeFormatter = DateTimeFormatter.ofPattern("EEE d MMM HH:mm")
    }
}
