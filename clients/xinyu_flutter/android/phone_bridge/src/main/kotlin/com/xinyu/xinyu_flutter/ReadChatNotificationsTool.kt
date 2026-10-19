package com.xinyu.xinyu_flutter

import android.app.Notification
import android.content.Context
import android.os.Process
import android.service.notification.StatusBarNotification
import io.droidmcp.core.*

/** XinYu adaptation using the same droid-mcp schema, registry and in-process transport.
 * Upstream's cross-app reply tool requires RemoteInput and retains a background cache;
 * WeChat/QQ previews need neither. Read the OS snapshot only after ToolHub confirmation.
 */
internal class ReadChatNotificationsTool(private val context: Context) : McpTool {
    override val name = "read_chat_notifications"
    override val description = "Read a bounded snapshot of current WeChat or QQ notification previews, after user confirmation. No message sending or notification dismissal."
    override val parameters = listOf(
        ToolParameter("package_name", "Requested chat app package.", ParameterType.STRING,
            required = true, enumValues = PACKAGES.toList()),
        ToolParameter("title_filter", "Optional exact substring of the notification title.", ParameterType.STRING),
        ToolParameter("limit", "Maximum previews, default 1, at most 3.", ParameterType.INTEGER, minimum = 1.0, maximum = 3.0),
    )
    override val annotations = ToolAnnotations(readOnlyHint = true, idempotentHint = true)

    override suspend fun execute(params: Map<String, Any>): ToolResult {
        val pkg = params["package_name"] as? String
        val filter = params["title_filter"] as? String
        val limitValue = params["limit"] ?: 1
        if (pkg !in PACKAGES || params.keys.any { it !in setOf("package_name", "title_filter", "limit") } ||
            (params.containsKey("title_filter") && (filter.isNullOrBlank() || filter.length > 80)) ||
            limitValue !is Number || limitValue.toDouble() !in setOf(1.0, 2.0, 3.0)) {
            return ToolResult.error("只能读取指定微信或 QQ 的 1 到 3 条通知预览。")
        }
        if (!EnvironmentSensors.canRead(context)) {
            return ToolResult.error("请回到心隅前台并解锁屏幕，再确认读取消息。")
        }
        return try {
            val rows = CompanionNotificationListener.snapshot(context)
            val data = project(rows, pkg!!, filter, limitValue.toInt())
            if (!EnvironmentSensors.canRead(context) || !CompanionNotificationListener.allowed(context)) {
                ToolResult.error("读取时已离开前台或撤销权限，本次内容已丢弃。")
            } else ToolResult.success(data)
        } catch (_: Exception) {
            ToolResult.error("通知读取未完成。请确认已单独授权「陪我看消息」且通知连接已就绪。")
        }
    }

    companion object {
        private val PACKAGES = setOf("com.tencent.mm", "com.tencent.mobileqq")

        internal fun project(rows: Array<StatusBarNotification>, pkg: String,
            filter: String?, limit: Int): Map<String, Any> {
            val previews = rows.asSequence().filter {
                it.packageName == pkg && it.user == Process.myUserHandle()
            }.sortedByDescending { it.postTime }.mapNotNull { sbn ->
                // Malformed app-provided extras must not crash chat or expose exception text.
                runCatching {
                    val n = sbn.notification
                    if (n.flags and (Notification.FLAG_ONGOING_EVENT or Notification.FLAG_FOREGROUND_SERVICE or
                            Notification.FLAG_GROUP_SUMMARY) != 0 ||
                        n.category in setOf(Notification.CATEGORY_CALL, Notification.CATEGORY_TRANSPORT,
                            Notification.CATEGORY_PROMO, Notification.CATEGORY_SERVICE)) return@runCatching null
                    val extras = n.extras
                    val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString().orEmpty()
                    if (filter != null && !title.contains(filter, ignoreCase = true)) return@runCatching null
                    val body = extras.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString()
                        ?.takeIf { it.isNotBlank() }
                        ?: extras.getCharSequence(Notification.EXTRA_TEXT)?.toString().orEmpty()
                    mapOf<String, Any>(
                        "title" to title.take(120), "text" to body.take(800),
                        "posted_at_ms" to sbn.postTime, "package_name" to pkg,
                        "truncated" to (title.length > 120 || body.length > 800),
                        "content_available" to body.isNotBlank(),
                    )
                }.getOrNull()
            }.take(limit + 1).toList()
            val selected = previews.take(limit)
            return mapOf(
                "notifications" to selected, "count" to selected.size,
                "more_available" to (previews.size > limit), "source" to "untrusted_notification_preview",
                "note" to "仅为当前通知预览，不是完整聊天记录；隐藏或被清除的内容无法读取。不能据此断定对方情绪或意图。",
            )
        }
    }
}
