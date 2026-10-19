package com.xinyu.xinyu_flutter

import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.graphics.Rect
import android.media.AudioManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.view.WindowInsets
import android.view.WindowManager
import io.droidmcp.accessibility.*
import io.droidmcp.alarms.*
import io.droidmcp.apps.AppsTools
import io.droidmcp.core.McpTool
import io.droidmcp.core.ToolRegistry
import io.droidmcp.core.transport.InProcessTransport
import io.droidmcp.device.DeviceTools
import io.droidmcp.dnd.*
import io.droidmcp.screen.ScreenTools
import io.droidmcp.sensors.GetLightLevelTool
import io.droidmcp.sensors.GetProximityTool
import io.droidmcp.settings.*
import io.droidmcp.vibration.VibrateTool
import io.droidmcp.vibration.VibratePatternTool
import io.droidmcp.vibration.CancelVibrationTool
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject

/** Private JNI boundary. No HTTP listener and no Flutter method for executing tools. */
object PhoneBridge {
    @Volatile internal var foreground = false
        private set

    @JvmStatic fun setForeground(value: Boolean) { foreground = value }
    @JvmStatic fun isForeground(): Boolean = foreground
    fun canReadScreen(): Boolean = AccessibilityTools.isAccessibilityEnabled()

    @JvmStatic
    fun exchange(context: Context, operation: String, payload: String, timeoutMs: Int): String {
        if (Build.VERSION.SDK_INT < 28) return JSONObject(mapOf(
            "supported" to false, "status" to "failed",
            "message" to "手机能力需要 Android 9 或更高版本，其他功能可继续使用。",
        )).toString()
        return try {
            when (operation) {
                "state" -> state(context)
                "catalog" -> PhoneSdk.catalog(context)
                "call" -> PhoneSdk.call(context, JSONObject(payload), timeoutMs.coerceIn(1, 20000))
                else -> failure("不支持的手机操作。")
            }.toString()
        } catch (_: Exception) {
            // Platform exception messages can contain paths or screen data.
            JSONObject(mapOf("status" to "uncertain", "message" to "手机操作结果未确认，请先核对；不会自动重试。")).toString()
        }
    }

    private fun state(context: Context) = JSONObject(mapOf(
        "supported" to true,
        "permissions" to mapOf(
            "accessibility" to AccessibilityTools.isAccessibilityEnabled(),
            "dnd" to (context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
                .isNotificationPolicyAccessGranted,
            "write_settings" to Settings.System.canWrite(context),
            "overlay" to Settings.canDrawOverlays(context),
            "chat_notifications" to CompanionNotificationListener.allowed(context),
        ),
    ))

    fun openPermissionSettings(context: Context, permission: String) {
        require(Build.VERSION.SDK_INT >= 28)
        val intent = when (permission) {
            "accessibility" -> Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)
            "chat_notifications" -> Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)
            "dnd" -> Intent(Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS)
            "write_settings" -> Intent(Settings.ACTION_MANAGE_WRITE_SETTINGS,
                Uri.parse("package:${context.packageName}"))
            "overlay" -> Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                Uri.parse("package:${context.packageName}"))
            else -> throw IllegalArgumentException("Unknown permission")
        }
        context.startActivity(intent)
    }

    internal fun failure(message: String) = JSONObject(mapOf("status" to "failed", "message" to message))
}

/** Upstream tools with XinYu preconditions, readback and brightness-mode restoration. */
private object PhoneSdk {
    private val names = setOf(
        "get_device_info", "get_battery_info", "get_connectivity", "get_screen_state",
        "get_settings", "set_volume", "set_brightness", "vibrate", "get_next_alarm",
        "create_alarm", "create_timer", "list_installed_apps", "get_app_info", "launch_app",
        "get_dnd_status", "set_dnd_mode", "query_screen", "find_node", "click_node",
        "set_node_text", "scroll_node", "get_active_window_info", "tap", "global_action",
        "long_click_node", "gesture",
        "get_light_level", "get_proximity",
        "vibrate_pattern", "cancel_vibration",
        "read_chat_notifications",
    )
    private val uiNames = setOf("query_screen", "find_node", "click_node", "set_node_text",
        "scroll_node", "get_active_window_info", "tap", "global_action", "long_click_node", "gesture")

    private fun tools(context: Context): List<McpTool> = (
        DeviceTools.all(context) + ScreenTools.all(context) + AppsTools.all(context) +
        listOf(GetSettingsTool(context), SetVolumeTool(context), SetBrightnessTool(context),
            VibrateTool(context), VibratePatternTool(context), CancelVibrationTool(context),
            GetNextAlarmTool(context), CreateAlarmTool(context),
            CreateTimerTool(context), GetDndStatusTool(context), SetDndModeTool(context)) +
        listOf(GetLightLevelTool(context), GetProximityTool(context), ReadChatNotificationsTool(context)) +
        AccessibilityTools.all(context)
    ).filter { it.name in names && (it.name != "gesture" || Build.VERSION.SDK_INT >= 30) }

    private fun transport(context: Context, timeoutMs: Int): InProcessTransport {
        val registry = ToolRegistry(toolTimeoutMs = timeoutMs.toLong())
        registry.registerAll(tools(context.applicationContext))
        return InProcessTransport(registry)
    }

    fun catalog(context: Context) = JSONObject().put("supported", true)
        .put("tools", JSONArray(transport(context, 20000).listToolsJson()))

    fun call(context: Context, payload: JSONObject, timeoutMs: Int): JSONObject {
        val deadline = System.nanoTime() + timeoutMs.toLong() * 1_000_000
        val name = payload.getString("name")
        if (name !in names) return PhoneBridge.failure("此手机能力未接入。")
        val args = objectMap(payload.getJSONObject("arguments")).toMutableMap()
        val sensorRead = name in setOf("get_light_level", "get_proximity")
        if ((sensorRead || args.remove("require_foreground") == true) &&
            !EnvironmentSensors.canRead(context)) {
            return PhoneBridge.failure("仅在心隅前台、屏幕解锁时感知环境或主动调暗。")
        }
        val audio = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        if (name == "vibrate_pattern" && (!HapticPatterns.valid(args) ||
            !EnvironmentSensors.canRead(context) || audio.mode != AudioManager.MODE_NORMAL)) {
            return PhoneBridge.failure("触感陪伴仅支持前台解锁、未通话时的两种短节奏，不循环。")
        }
        if (args.remove("require_idle_audio") == true && audio.mode != AudioManager.MODE_NORMAL) {
            return PhoneBridge.failure("手机正在通话或使用其他音频模式，保持现状。")
        }
        val expectedLevel = args.remove("expected_level") as? Number
        val expectedAutomatic = args.remove("expected_automatic") as? Boolean
        val automatic = args.remove("automatic") as? Boolean ?: false
        val expectedMode = args.remove("expected_mode") as? String
        if (name == "set_volume" && expectedLevel != null &&
            audio.getStreamVolume(AudioManager.STREAM_MUSIC) != expectedLevel.toInt()) {
            return PhoneBridge.failure("音量已变化，保留当前设置。")
        }
        if (name == "set_brightness") {
            val level = Settings.System.getInt(context.contentResolver, Settings.System.SCREEN_BRIGHTNESS, -1)
            val mode = Settings.System.getInt(context.contentResolver, Settings.System.SCREEN_BRIGHTNESS_MODE, -1)
            if ((expectedLevel != null && level != expectedLevel.toInt()) ||
                (expectedAutomatic != null && (mode == 1) != expectedAutomatic)) {
                return PhoneBridge.failure("亮度设置已变化，保留当前设置。")
            }
        }
        if (name == "set_dnd_mode" && expectedMode != null) {
            val filter = (context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
                .currentInterruptionFilter
            val expected = mapOf("off" to 1, "priority" to 2, "none" to 3, "alarms" to 4)[expectedMode]
            if (filter != expected) return PhoneBridge.failure("勿扰状态已变化，保留当前设置。")
        }
        if (name in uiNames) {
            if (!AccessibilityTools.isAccessibilityEnabled()) {
                return PhoneBridge.failure("请在连接的应用中开启无障碍权限。")
            }
            val expected = args.remove("expected_package") as? String
                ?: return PhoneBridge.failure("需要明确目标应用，未执行界面操作。")
            if (expected in setOf(context.packageName, "com.android.settings", "com.android.systemui", "android")) {
                return PhoneBridge.failure("此界面需要你亲自操作。")
            }
            if (activePackage() != expected) {
                return PhoneBridge.failure("当前界面与目标应用不同，请切回目标应用后重新读取；未执行操作。")
            }
            if (name in setOf("find_node", "click_node", "long_click_node", "set_node_text", "scroll_node")) {
                args["package_name"] = expected
            }
            if (name == "gesture" && !validGesture(context, args, expected)) {
                return PhoneBridge.failure("滑动路径必须位于当前目标应用窗口内，包含 2 到 16 个有效坐标。")
            }
        }
        if (name == "set_brightness" && !Settings.System.canWrite(context)) {
            return PhoneBridge.failure("请先在连接的应用中授予修改系统设置权限。")
        }
        if (name == "set_dnd_mode" && !(context.getSystemService(Context.NOTIFICATION_SERVICE)
                as NotificationManager).isNotificationPolicyAccessGranted) {
            return PhoneBridge.failure("请先在连接的应用中授予勿扰权限。")
        }
        if (name == "set_volume") {
            if (args["stream"] != null && args["stream"] != "media") {
                return PhoneBridge.failure("手机能力只调整媒体音量。")
            }
            args["stream"] = "media"
        }
        if (name == "set_brightness" && ((args["level"] as? Number)?.toInt() ?: -1) !in 10..255) {
            return PhoneBridge.failure("亮度需要在 10 到 255 之间。")
        }
        if (name == "global_action" && args["action"] !in setOf("back", "home", "recents")) {
            return PhoneBridge.failure("此系统操作未开放。")
        }
        if (name == "query_screen") args["max_nodes"] = ((args["max_nodes"] as? Number)?.toInt() ?: 30).coerceIn(1, 40)
        if (name == "find_node") args["limit"] = ((args["limit"] as? Number)?.toInt() ?: 10).coerceIn(1, 20)
        val result = runBlocking { transport(context, timeoutMs).callTool(name, args) }
        if (!result.isSuccess) {
            val timedOut = result.errorMessage?.startsWith("tool_timeout") == true
            return JSONObject(mapOf("status" to if (timedOut) "uncertain" else "failed",
                "message" to if (timedOut) "手机操作超时，请先核对结果，不要重复操作。"
                    else "手机未完成操作，请检查目标应用和系统权限。",
                "detail" to result.errorMessage?.take(500)))
        }
        val data = JSONObject(result.data ?: emptyMap<String, Any>())
        if (name in setOf("vibrate_pattern", "cancel_vibration")) {
            data.put("delivery", "submitted").put("physical_effect_verified", false)
                .put("message", if (name == "cancel_vibration") "已提交停止本应用震动的指令。"
                    else "已提交短节奏震动指令，实际触感取决于手机和系统设置。")
        }
        if (sensorRead) return EnvironmentSensors.normalize(context, name, data)
        if (name in setOf("long_click_node", "gesture")) {
            data.put("delivery", "completed").put("effect_verified", false)
                .put("message", "已完成界面操作，请重新读取界面核对结果。")
        }
        var status = if (data.optBoolean("applied", true)) "succeeded" else "uncertain"
        if (name in setOf("create_alarm", "create_timer", "launch_app")) {
            status = "uncertain"
            data.put("message", "请求已交给目标应用，请查看是否完成；不会自动重试。")
        }
        if (name == "launch_app" && AccessibilityTools.isAccessibilityEnabled()) {
            val target = args["package_name"] as? String
            val until = minOf(deadline, System.nanoTime() + 1_500_000_000)
            while (activePackage() != target && System.nanoTime() < until) Thread.sleep(50)
            if (activePackage() == target) {
                status = "succeeded"
                data.put("message", "已核对目标应用处于前台。")
            }
        }
        if (name in setOf("query_screen", "find_node", "get_active_window_info") &&
            activePackage() != payload.getJSONObject("arguments").optString("expected_package")) {
            return PhoneBridge.failure("读取期间目标界面已切换，本次内容已丢弃，请重新读取。")
        }
        if (name == "set_brightness") {
            if (automatic) {
                Settings.System.putInt(context.contentResolver, Settings.System.SCREEN_BRIGHTNESS_MODE,
                    Settings.System.SCREEN_BRIGHTNESS_MODE_AUTOMATIC)
            }
            val actual = Settings.System.getInt(context.contentResolver, Settings.System.SCREEN_BRIGHTNESS, -1)
            data.put("actual_brightness", actual)
            val mode = Settings.System.getInt(context.contentResolver, Settings.System.SCREEN_BRIGHTNESS_MODE, -1)
            data.put("brightness_mode", mode)
            if ((!automatic && actual != data.optInt("brightness")) || mode != if (automatic) 1 else 0) {
                status = "uncertain"
            }
        }
        if (name == "get_settings" || name == "set_volume") {
            data.put("volume_media", audio.getStreamVolume(AudioManager.STREAM_MUSIC))
            data.put("volume_media_max", audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC))
            if (name == "set_volume" && data.optInt("level") != data.optInt("volume_media")) status = "uncertain"
            // No Bluetooth permission is requested by XinYu. Upstream's fallback
            // false cannot be interpreted as evidence that Bluetooth is off.
            if (name == "get_settings") {
                data.put("bluetooth_enabled", JSONObject.NULL)
                data.put("audio_mode", audio.mode)
                data.put("music_active", audio.isMusicActive)
                data.put("brightness_mode", Settings.System.getInt(context.contentResolver,
                    Settings.System.SCREEN_BRIGHTNESS_MODE, -1))
            }
        }
        // Keep a valid, bounded JSON result; never cut a JSON string mid-node.
        for (key in listOf("nodes", "matches", "apps")) {
            val rows = data.optJSONArray(key) ?: continue
            while (rows.length() > 0 && data.toString().length > 9000) {
                rows.remove(rows.length() - 1)
                data.put("truncated", true).put("returned_count", rows.length())
            }
        }
        return data.put("status", status)
    }

    @Suppress("DEPRECATION")
    private fun validGesture(context: Context, args: Map<String, Any>, expected: String): Boolean {
        // Android 11 supplies reliable display insets, including edge-to-edge
        // system gesture areas. Older devices keep node-based scrolling.
        if (Build.VERSION.SDK_INT < 30) return false
        val points = args["points"] as? List<*> ?: return false
        if (points.size !in 2..16) return false
        val duration = args["duration_ms"] as? Number
        if (duration != null && duration.toDouble() !in 10.0..3000.0) return false
        val root = AccessibilityServiceHolder.service?.rootInActiveWindow ?: return false
        try {
            if (root.packageName?.toString() != expected) return false
            val bounds = Rect().also(root::getBoundsInScreen)
            val metrics = context.getSystemService(WindowManager::class.java).maximumWindowMetrics
            val insets = metrics.windowInsets.getInsetsIgnoringVisibility(
                WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout() or
                    WindowInsets.Type.systemGestures()
            )
            val usable = Rect(metrics.bounds).apply {
                left += insets.left; top += insets.top
                right -= insets.right; bottom -= insets.bottom
            }
            if (!bounds.intersect(usable)) return false
            return points.all { point ->
                val pair = point as? List<*> ?: return@all false
                if (pair.size != 2) return@all false
                val x = (pair[0] as? Number)?.toDouble() ?: return@all false
                val y = (pair[1] as? Number)?.toDouble() ?: return@all false
                x.isFinite() && y.isFinite() && x >= maxOf(0, bounds.left) &&
                    x < bounds.right && y >= maxOf(0, bounds.top) && y < bounds.bottom
            }
        } finally { root.recycle() }
    }

    @Suppress("DEPRECATION")
    private fun activePackage(): String? {
        val root = AccessibilityServiceHolder.service?.rootInActiveWindow ?: return null
        return try { root.packageName?.toString() } finally { root.recycle() }
    }

    private fun objectMap(value: JSONObject): Map<String, Any> = value.keys().asSequence()
        .filter { !value.isNull(it) }.associateWith { fromJson(value.get(it)) }

    private fun fromJson(value: Any): Any = when (value) {
        is JSONObject -> objectMap(value)
        is JSONArray -> (0 until value.length()).filter { !value.isNull(it) }.map { fromJson(value.get(it)) }
        else -> value
    }
}
