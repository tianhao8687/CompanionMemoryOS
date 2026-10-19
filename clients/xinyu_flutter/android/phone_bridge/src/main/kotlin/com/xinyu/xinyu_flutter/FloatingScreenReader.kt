@file:Suppress("DEPRECATION")
package com.xinyu.xinyu_flutter

import android.app.KeyguardManager
import android.content.Context
import android.graphics.Rect
import android.os.Build
import android.os.PowerManager
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import io.droidmcp.accessibility.AccessibilityServiceHolder
import io.droidmcp.accessibility.TakeScreenshotViaA11yTool

/** One user-opened snapshot. Uses the existing droid-mcp service, never an event recorder. */
internal object FloatingScreenReader {
    private fun unlocked(context: Context) = context.getSystemService(PowerManager::class.java).isInteractive &&
        !context.getSystemService(KeyguardManager::class.java).isKeyguardLocked

    private fun root(context: Context): AccessibilityNodeInfo? {
        val service = AccessibilityServiceHolder.service ?: return null
        // Touching our dot may make the overlay the active accessibility window.
        // Pick the underlying application, excluding overlays, keyboards and system UI.
        val windows = service.windows
        try {
            for (window in windows.filter { it.type == AccessibilityWindowInfo.TYPE_APPLICATION }
                .sortedByDescending { it.layer }) {
                val node = window.root ?: continue
                if (allowedPackage(node.packageName?.toString(), context.packageName)) return node
                node.recycle()
            }
        } finally { windows.forEach { it.recycle() } }
        val active = service.rootInActiveWindow ?: return null
        if (allowedPackage(active.packageName?.toString(), context.packageName)) return active
        active.recycle()
        return null
    }

    internal fun allowedPackage(name: String?, own: String) = !name.isNullOrBlank() &&
        name !in setOf(own, "android", "com.android.systemui", "com.android.settings", "com.android.permissioncontroller")

    internal data class TextSnapshot(val text: String, val sensitive: Boolean, val truncated: Boolean)

    internal fun visibleText(root: AccessibilityNodeInfo): TextSnapshot {
        val queue = ArrayDeque<AccessibilityNodeInfo>()
        queue.add(root)
        val lines = linkedSetOf<String>()
        var length = 0; var count = 0; var sensitive = false; var truncated = false
        try {
            while (queue.isNotEmpty()) {
                val node = queue.removeFirst()
                try {
                    count++
                    val bounds = Rect().also { node.getBoundsInScreen(it) }
                    if (node.isVisibleToUser && !bounds.isEmpty) {
                        sensitive = sensitive || node.isPassword
                        if (!node.isPassword) {
                            val text = node.text?.toString()?.trim().orEmpty()
                                .ifEmpty { node.contentDescription?.toString()?.trim().orEmpty() }
                            if (text.isNotEmpty() && text !in lines) {
                                if (length < 4000 && lines.size < 80) {
                                    val part = text.take(4000 - length)
                                    lines.add(part); length += part.length + 1
                                    truncated = truncated || part.length < text.length
                                } else truncated = true
                            }
                        }
                    }
                    if (count < 512) {
                        for (i in 0 until node.childCount) node.getChild(i)?.let { queue.add(it) }
                    } else { truncated = true; break }
                } finally { if (node !== root) node.recycle() }
            }
        } finally { queue.forEach { if (it !== root) it.recycle() } }
        return TextSnapshot(lines.joinToString("\n"), sensitive, truncated)
    }

    suspend fun capture(context: Context, vision: Boolean): Map<String, Any?> {
        fun unavailable(message: String) = mapOf<String, Any?>("notice" to message)
        if (!unlocked(context)) return unavailable("屏幕已锁定，这次没有读屏。")
        if (!AccessibilityServiceHolder.isConnected()) return unavailable("还不能读屏。请回心隅开启无障碍读屏权限，也可以直接和我聊。")
        val node = root(context) ?: return unavailable("这页暂时读不到内容，你可以直接告诉我。")
        val name: String
        val snapshot: TextSnapshot
        try {
            name = node.packageName.toString()
            snapshot = visibleText(node)
        } finally { node.recycle() }
        val contextData = mutableMapOf<String, Any?>(
            "package_name" to name, "text" to snapshot.text, "truncated" to snapshot.truncated,
        )
        val appName = try { context.packageManager.getApplicationLabel(context.packageManager.getApplicationInfo(name, 0)).toString() }
            catch (_: Exception) { name }
        contextData["app_name"] = appName.take(100)
        if (vision && Build.VERSION.SDK_INT >= 30 && !snapshot.sensitive && !snapshot.truncated) {
            val image = TakeScreenshotViaA11yTool(context).execute(mapOf("format" to "jpeg", "quality" to 65, "max_dimension" to 1024))
            val base64 = image.data?.get("image_base64") as? String
            if (image.isSuccess && base64 != null && base64.length <= 700000) contextData["image_base64"] = base64
        }
        val current = root(context)
        val same = try { current?.packageName?.toString() == name } finally { current?.recycle() }
        if (!same || !unlocked(context)) return unavailable("页面刚刚切换了，这次没有用旧画面回复。")
        if (snapshot.text.isBlank() && contextData["image_base64"] == null) {
            return unavailable("这页没有可读取的文字，当前也未取得画面。你可以直接告诉我，或在完整对话发图。")
        }
        return mapOf("screen" to contextData)
    }
}
