package com.xinyu.xinyu_flutter

import android.content.Intent
import android.util.Log
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.embedding.android.FlutterActivity
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private val worker = EngineBridge.worker
    private val localFiles = LocalFiles(this, worker)
    private var notifications: MethodChannel? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        notifications = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "xinyu/notifications").also { channel ->
            channel.setMethodCallHandler { call, result ->
                if (call.method == "openedConversation") {
                    result.success(intent?.getStringExtra("conversation_id"))
                    intent?.removeExtra("conversation_id")
                } else ChatNotifications.call(this, call, result)
            }
        }
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "xinyu/local-files")
            .setMethodCallHandler { call, result -> localFiles.call(call, result) }
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "xinyu/local-runtime")
            .setMethodCallHandler { call, result ->
                if (call.method != "start" && call.method != "stop") {
                    result.notImplemented()
                    return@setMethodCallHandler
                }
                worker.execute {
                    var stage = "engine_runtime"
                    try {
                        stage = if (call.method == "stop") "engine_stop" else "engine_start"
                        if (call.method == "stop") {
                            EngineBridge.detach(this)
                            runOnUiThread { result.success(null) }
                        } else {
                            EngineBridge.attach(this)
                            val value = EngineBridge.start(applicationContext)
                            val response = mapOf(
                                "protocol" to value.getInt("protocol"),
                                "endpoint" to value.getString("endpoint"),
                                "token" to value.getString("token")
                            )
                            runOnUiThread { result.success(response) }
                        }
                    } catch (error: Exception) {
                        engineFailure(result, stage, error)
                    } catch (error: LinkageError) {
                        engineFailure(result, stage, error)
                    }
                }
            }
    }

    private fun engineFailure(result: MethodChannel.Result, stage: String, error: Throwable) {
        // Only fixed stages and code locations: never log exception messages,
        // Python arguments, file paths, database contents, or credentials.
        val safeName = Regex("[A-Za-z0-9_.$<>]+")
        val frames = error.stackTrace.filter {
            safeName.matches(it.className) && safeName.matches(it.methodName)
        }.take(12).joinToString(" > ") {
            "${it.className}.${it.methodName}:${it.lineNumber}"
        }
        Log.e("XinYuEngine", "$stage ${error.javaClass.simpleName} $frames")
        runOnUiThread { result.error(stage, "手机内置记忆引擎未能启动。", null) }
    }

    override fun onDestroy() {
        worker.execute {
            try { EngineBridge.detach(this) } catch (_: Exception) { }
        }
        super.onDestroy()
    }

    override fun onPause() {
        ChatNotifications.visibleConversation = null
        super.onPause()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        intent.getStringExtra("conversation_id")?.let {
            notifications?.invokeMethod("openConversation", it)
            intent.removeExtra("conversation_id")
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (!localFiles.result(requestCode, resultCode, data)) {
            super.onActivityResult(requestCode, resultCode, data)
        }
    }
}
