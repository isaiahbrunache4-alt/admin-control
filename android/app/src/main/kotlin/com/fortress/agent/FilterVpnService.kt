package com.fortress.agent

import android.content.Context
import android.content.Intent
import android.net.ConnectivityManager
import android.net.VpnService
import android.os.ParcelFileDescriptor
import android.util.Log
import com.fortress.agent.core.DnsPackets
import com.fortress.agent.core.DnsQuery
import com.fortress.agent.core.SiteFilter
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.IOException
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress
import java.util.concurrent.Executors

/**
 * The website filter (Spec 01 §8.1): a VPN that stays on the device. It gives Android
 * one DNS server address and routes only that address into itself, so it sees DNS
 * lookups and nothing else; web traffic itself never passes through it. Blocked names
 * get "no such domain"; every other lookup is passed to the network's own DNS server
 * and the answer handed back unchanged. Fortress's own traffic is left out of the VPN.
 *
 * Set as the always-on VPN by the device owner (Enforcer), so Android starts it at boot
 * and restarts it if it stops.
 */
class FilterVpnService : VpnService() {
    private var tun: ParcelFileDescriptor? = null
    private var reader: Thread? = null
    private val upstream = Executors.newFixedThreadPool(4)

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopFilter()
            stopSelf()
            return START_NOT_STICKY
        }
        if (tun == null) startFilter()
        return START_STICKY
    }

    private fun startFilter() {
        Runtime.refreshFilter(this)
        val builder = Builder()
            .setSession("Fortress website filter")
            .addAddress(ADDRESS_V4, 32)
            .addDnsServer(DNS_V4)
            .addRoute(DNS_V4, 32)
            .addAddress(ADDRESS_V6, 128)
            .addDnsServer(DNS_V6)
            .addRoute(DNS_V6, 128)
            .setBlocking(true)
            .setMetered(false)
        try {
            builder.addDisallowedApplication(packageName) // Fortress talks to Core directly
        } catch (e: Exception) {
            Log.w(TAG, "could not exclude self", e)
        }
        val fd = try {
            builder.establish()
        } catch (e: Exception) {
            Log.w(TAG, "establish failed", e)
            null
        } ?: return // not authorised yet: the device owner's always-on setting authorises it
        tun = fd
        running = true
        Runtime.agent(this).log("filter_started")
        reader = Thread({ readLoop(fd) }, "fortress-dns").apply { start() }
    }

    private fun readLoop(fd: ParcelFileDescriptor) {
        val input = FileInputStream(fd.fileDescriptor)
        val output = FileOutputStream(fd.fileDescriptor)
        val buf = ByteArray(32767)
        while (tun === fd) {
            val n = try {
                input.read(buf)
            } catch (e: IOException) {
                break
            }
            if (n <= 0) continue
            val query = DnsPackets.parse(buf, n) ?: continue
            if (filter.check(query.name) != null) {
                write(output, DnsPackets.reply(query, DnsPackets.nxdomain(query.message)))
            } else {
                upstream.execute { forward(query, output) }
            }
        }
    }

    /** Ask the network's own DNS server and hand its answer back as it came. */
    private fun forward(query: DnsQuery, output: FileOutputStream) {
        for (server in upstreamServers()) {
            try {
                DatagramSocket().use { s ->
                    protect(s)
                    s.soTimeout = 5000
                    s.send(DatagramPacket(query.message, query.message.size, InetSocketAddress(server, 53)))
                    val buf = ByteArray(65535)
                    val p = DatagramPacket(buf, buf.size)
                    s.receive(p)
                    write(output, DnsPackets.reply(query, buf.copyOf(p.length)))
                }
                return
            } catch (e: IOException) {
                // Try the next server; if none answer, the asker retries.
            }
        }
    }

    /** DNS servers of the real network. Fortress is outside its own VPN, so the
     * default network it sees is the real one. */
    private fun upstreamServers(): List<InetAddress> {
        val cm = getSystemService(ConnectivityManager::class.java)
        val servers = cm.activeNetwork?.let { cm.getLinkProperties(it)?.dnsServers }.orEmpty()
            .filter { it.hostAddress != DNS_V4 && it.hostAddress?.startsWith("fd00:f0f7") != true }
        return servers.ifEmpty { FALLBACK.map(InetAddress::getByName) }
    }

    private fun write(output: FileOutputStream, packet: ByteArray) {
        synchronized(output) {
            try {
                output.write(packet)
            } catch (e: IOException) {
                // The interface closed under us; the filter is stopping.
            }
        }
    }

    private fun stopFilter() {
        val fd = tun ?: return
        tun = null
        running = false
        try {
            fd.close()
        } catch (e: IOException) {
            // already closed
        }
        reader?.interrupt()
        reader = null
        Runtime.agent(this).log("filter_stopped")
    }

    override fun onRevoke() {
        stopFilter()
        super.onRevoke()
    }

    override fun onDestroy() {
        stopFilter()
        upstream.shutdownNow()
        super.onDestroy()
    }

    companion object {
        private const val TAG = "FortressFilter"
        const val ACTION_STOP = "com.fortress.agent.STOP_FILTER"

        // A private address pair for the filter's own interface and DNS server.
        const val ADDRESS_V4 = "10.111.222.1"
        const val DNS_V4 = "10.111.222.2"
        const val ADDRESS_V6 = "fd00:f0f7::1"
        const val DNS_V6 = "fd00:f0f7::2"

        /** Only if the network reports no DNS server of its own. */
        private val FALLBACK = listOf("1.1.1.1", "9.9.9.9")

        /** What is blocked right now. Shared with Runtime, which updates it on new rules. */
        val filter = SiteFilter()

        @Volatile var running = false
            private set

        fun stop(context: Context) {
            try {
                context.startService(Intent(context, FilterVpnService::class.java).setAction(ACTION_STOP))
            } catch (e: Exception) {
                Log.w(TAG, "stop", e)
            }
        }
    }
}
