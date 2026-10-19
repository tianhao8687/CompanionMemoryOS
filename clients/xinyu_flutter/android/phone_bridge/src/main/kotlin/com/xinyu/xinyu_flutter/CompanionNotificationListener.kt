package com.xinyu.xinyu_flutter

import android.app.NotificationManager
import android.content.ComponentName
import android.content.Context
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification

/** A separate system grant from music control. No event cache or background collection. */
class CompanionNotificationListener : NotificationListenerService() {
    override fun onListenerConnected() {
        super.onListenerConnected()
        current = this
    }

    override fun onListenerDisconnected() {
        if (current === this) current = null
        super.onListenerDisconnected()
    }

    override fun onDestroy() {
        if (current === this) current = null
        super.onDestroy()
    }

    companion object {
        @Volatile private var current: CompanionNotificationListener? = null

        fun allowed(context: Context): Boolean =
            context.getSystemService(NotificationManager::class.java)
                .isNotificationListenerAccessGranted(
                    ComponentName(context, CompanionNotificationListener::class.java))

        internal fun snapshot(context: Context): Array<StatusBarNotification> {
            check(allowed(context)) { "请在手机权限中单独授权「陪我看消息」。" }
            val listener = current ?: error("通知连接尚未就绪，请稍后再试。")
            val rows = listener.activeNotifications ?: error("系统没有返回通知快照。")
            check(current === listener && allowed(context)) { "读取时通知连接已断开。" }
            return rows
        }
    }
}
