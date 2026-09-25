package com.xinyu.xinyu_flutter

import com.chaquo.python.Python
import android.content.Intent
import com.chaquo.python.android.AndroidPlatform
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.embedding.android.FlutterActivity
import io.flutter.plugin.common.MethodChannel
import org.json.JSONObject
import java.io.File
import java.util.concurrent.Executors

class MainActivity : FlutterActivity() {
    private val worker = Executors.newSingleThreadExecutor()
    private val localFiles = LocalFiles(this, worker)

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "xinyu/local-files")
            .setMethodCallHandler { call, result -> localFiles.call(call, result) }
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "xinyu/local-runtime")
            .setMethodCallHandler { call, result ->
                if (call.method != "start" && call.method != "stop") {
                    result.notImplemented()
                    return@setMethodCallHandler
                }
                worker.execute {
                    try {
                        if (!Python.isStarted()) Python.start(AndroidPlatform(applicationContext))
                        val module = Python.getInstance().getModule("companion_agent.local_runtime")
                        if (call.method == "stop") {
                            module.callAttr("stop_embedded")
                            runOnUiThread { result.success(null) }
                        } else {
                            val directory = File(filesDir, "xinyu-data").apply { mkdirs() }
                            val value = JSONObject(module.callAttr(
                                "start_embedded", directory.absolutePath, applicationContext
                            ).toString())
                            val response = mapOf(
                                "protocol" to value.getInt("protocol"),
                                "endpoint" to value.getString("endpoint"),
                                "token" to value.getString("token")
                            )
                            runOnUiThread { result.success(response) }
                        }
                    } catch (_: Exception) {
                        // Python/Java errors may contain paths or credentials. Do not log them.
                        runOnUiThread { result.error("engine_unavailable", "本机记忆引擎启动失败，请重启应用。", null) }
                    }
                }
            }
    }

    override fun onDestroy() {
        if (isFinishing) {
            worker.execute {
                try {
                    if (Python.isStarted()) {
                        Python.getInstance().getModule("companion_agent.local_runtime")
                            .callAttr("stop_embedded")
                    }
                } catch (_: Exception) { /* OS process teardown also releases the lease. */ }
            }
        }
        worker.shutdown()
        super.onDestroy()
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (!localFiles.result(requestCode, resultCode, data)) {
            super.onActivityResult(requestCode, resultCode, data)
        }
    }
}
