package com.xinyu.xinyu_flutter

import android.content.Context
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File
import java.util.concurrent.Executors
import org.json.JSONObject

/** UI and JobService serialize ownership of the same embedded engine and database. */
object EngineBridge {
    val worker = Executors.newSingleThreadExecutor()
    private val owners = mutableSetOf<Any>() // Access only on worker.

    fun attach(owner: Any) { owners.add(owner) }
    fun detach(owner: Any) { owners.remove(owner); stopIfIdle() }

    fun start(context: Context): JSONObject {
        if (!Python.isStarted()) Python.start(AndroidPlatform(context.applicationContext))
        val directory = File(context.filesDir, "xinyu-data").apply { mkdirs() }
        return JSONObject(Python.getInstance().getModule("companion_agent.local_runtime")
            .callAttr("start_embedded", directory.absolutePath, context.applicationContext).toString())
    }

    fun stopIfIdle() {
        if (owners.isEmpty() && Python.isStarted()) {
            Python.getInstance().getModule("companion_agent.local_runtime").callAttr("stop_embedded")
        }
    }

    fun tick(): JSONObject = JSONObject(Python.getInstance()
        .getModule("companion_agent.local_runtime").callAttr("embedded_outreach_tick").toString())

    fun delivered(ids: String) {
        Python.getInstance().getModule("companion_agent.local_runtime")
            .callAttr("embedded_notifications_delivered", ids)
    }
}
