package com.xinyu.xinyu_flutter

import android.app.job.JobParameters
import android.app.job.JobService
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean
import org.json.JSONArray

class OutreachJobService : JobService() {
    private var cancellation: AtomicBoolean? = null

    override fun onStartJob(params: JobParameters): Boolean {
        val stopped = AtomicBoolean(false)
        cancellation = stopped
        EngineBridge.worker.execute {
            try {
                // A pending import is applied only when the user reopens the app.
                if (stopped.get() || !ChatNotifications.allowed(this) ||
                    File(filesDir, "xinyu-data/restore-pending.sqlite").exists()) return@execute
                EngineBridge.start(applicationContext)
                if (stopped.get()) return@execute
                val update = EngineBridge.tick()
                if (stopped.get()) return@execute
                if (!update.optBoolean("enabled")) ChatNotifications.configure(this, false)
                val valid = update.getJSONArray("valid")
                ChatNotifications.reconcile(this, (0 until valid.length()).map { valid.getString(it) }.toSet())
                val notices = update.getJSONArray("notifications")
                val delivered = JSONArray()
                for (i in 0 until notices.length()) {
                    if (stopped.get()) break
                    val notice = notices.getJSONObject(i)
                    if (ChatNotifications.post(this, notice.getString("conversation_id"), notice.getString("title"), notice.getString("body"))) delivered.put(notice.getString("id"))
                }
                EngineBridge.delivered(delivered.toString())
            } catch (_: Exception) {
                // No credentials, generated messages or Python exception bodies in OS logs.
            } catch (_: LinkageError) {
                // An unavailable engine must not crash the foreground Activity.
            } finally {
                try { EngineBridge.stopIfIdle() } catch (_: Exception) { }
                if (!stopped.get()) mainExecutorCompat { jobFinished(params, false) }
            }
        }
        return true
    }

    private fun mainExecutorCompat(action: () -> Unit) {
        android.os.Handler(mainLooper).post(action)
    }

    override fun onStopJob(params: JobParameters): Boolean {
        cancellation?.set(true)
        return false // The periodic schedule will run again; no immediate retry loop.
    }
}
