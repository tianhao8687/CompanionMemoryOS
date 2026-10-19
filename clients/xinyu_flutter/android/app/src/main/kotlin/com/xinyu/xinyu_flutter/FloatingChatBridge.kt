package com.xinyu.xinyu_flutter

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.lang.ref.WeakReference

/** Retains exactly the Flutter engine already showing the original conversation. */
object FloatingChatBridge {
    private var engine: FlutterEngine? = null
    private var activity = WeakReference<Activity>(null)
    private var channel: MethodChannel? = null
    private val main = Handler(Looper.getMainLooper())
    private var generation = 0
    var retaining = false
        private set

    fun retainedEngine(): FlutterEngine? = if (retaining) engine else null

    fun install(host: Activity, flutterEngine: FlutterEngine) {
        val context = host.applicationContext
        activity = WeakReference(host)
        engine = flutterEngine
        val bridge = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "xinyu/floating-chat")
        channel = bridge
        FloatingChatSession.host = object : FloatingChatSession.Host {
            override fun event(method: String, args: Map<String, Any?>, done: (Boolean) -> Unit) {
                bridge.invokeMethod(method, args, object : MethodChannel.Result {
                    override fun success(result: Any?) { done(result == true) }
                    override fun error(code: String, message: String?, details: Any?) { done(false) }
                    override fun notImplemented() { done(false) }
                })
            }
            override fun changed() { bridge.invokeMethod("state", status(context)) }
            override fun stopped() {
                val ticket = generation
                var released = false
                fun release() {
                    if (released || ticket != generation) return
                    released = true
                    retaining = false
                    EngineBridge.worker.execute { EngineBridge.detach(this@FloatingChatBridge) }
                    if (activity.get() == null) {
                        channel?.setMethodCallHandler(null)
                        engine?.destroy()
                        channel = null; engine = null; FloatingChatSession.host = null
                    }
                }
                // Give the existing controller a chance to persist its current draft.
                bridge.invokeMethod("closed", null, object : MethodChannel.Result {
                    override fun success(result: Any?) { release() }
                    override fun error(code: String, message: String?, details: Any?) { release() }
                    override fun notImplemented() { release() }
                })
                main.postDelayed({ release() }, 2500)
            }
        }
        bridge.setMethodCallHandler { call, result ->
            try {
                when (call.method) {
                    "status" -> result.success(status(context))
                    "screen_mode" -> {
                        context.getSharedPreferences("floating_chat", Context.MODE_PRIVATE).edit()
                            .putBoolean("read_screen", call.arguments == true).apply()
                        result.success(status(context))
                    }
                    "screen_permission" -> {
                        val current = activity.get()
                        if (current == null || !PhoneBridge.isForeground()) {
                            result.error("foreground", "请回到心隅后开启读屏权限。", null)
                        } else { PhoneBridge.openPermissionSettings(current, "accessibility"); result.success(null) }
                    }
                    "permission" -> {
                        val current = activity.get()
                        if (current == null || !PhoneBridge.isForeground()) {
                            result.error("foreground", "请回到心隅后设置悬浮窗权限。", null)
                        } else {
                            current.startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                                Uri.parse("package:${context.packageName}")))
                            result.success(null)
                        }
                    }
                    "start" -> {
                        if (Build.VERSION.SDK_INT < 26 || !Settings.canDrawOverlays(context)) {
                            result.error("permission", "请先授予悬浮窗权限。", null)
                        } else if (!PhoneBridge.isForeground() || activity.get() == null) {
                            result.error("foreground", "请从心隅主界面开启小窗。", null)
                        } else {
                            val value = arguments(call.arguments)
                            if (value["conversation"] !is String) {
                                result.error("conversation", "请先打开一段对话。", null)
                            } else {
                                generation++
                                retaining = true
                                EngineBridge.worker.execute { EngineBridge.attach(this) }
                                FloatingChatSession.update(value)
                                context.startForegroundService(Intent(context, FloatingChatService::class.java))
                                result.success(status(context))
                            }
                        }
                    }
                    "update" -> { if (retaining) FloatingChatSession.update(arguments(call.arguments)); result.success(null) }
                    "stop" -> {
                        if (FloatingChatSession.service != null) context.startService(
                            Intent(context, FloatingChatService::class.java).setAction(FloatingChatService.CLOSE))
                        result.success(null)
                    }
                    else -> result.notImplemented()
                }
            } catch (_: RuntimeException) {
                if (call.method == "start") {
                    retaining = false
                    EngineBridge.worker.execute { EngineBridge.detach(this) }
                }
                result.error("floating_chat", "小窗操作未完成，请检查系统权限后重试。", null)
            }
        }
    }

    private fun arguments(value: Any?): Map<String, Any?> = (value as? Map<*, *>)
        ?.entries?.filter { it.key is String }?.associate { it.key as String to it.value } ?: emptyMap()

    private fun status(context: Context) = mapOf(
        "supported" to (Build.VERSION.SDK_INT >= 26),
        "permitted" to Settings.canDrawOverlays(context),
        "running" to retaining,
        "readScreen" to context.getSharedPreferences("floating_chat", Context.MODE_PRIVATE).getBoolean("read_screen", true),
        "screenPermitted" to PhoneBridge.canReadScreen(),
    )

    fun hostDestroyed(host: Activity) {
        if (activity.get() !== host) return
        activity.clear()
        if (!retaining) {
            channel?.setMethodCallHandler(null)
            channel = null; engine = null; FloatingChatSession.host = null
        }
    }
}
