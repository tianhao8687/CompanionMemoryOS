package com.xinyu.xinyu_flutter

import android.app.KeyguardManager
import android.app.Notification
import android.app.NotificationManager
import android.content.ComponentName
import android.os.PowerManager
import android.os.Process
import android.os.UserHandle
import android.service.notification.StatusBarNotification
import org.json.JSONObject
import org.junit.After
import org.junit.Before
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)
class ChatNotificationsTest {
    private val context get() = RuntimeEnvironment.getApplication()
    private val controller = Robolectric.buildService(CompanionNotificationListener::class.java)
    private val service get() = controller.get()
    private val manager get() = shadowOf(context.getSystemService(NotificationManager::class.java))
    private val component get() = ComponentName(context, CompanionNotificationListener::class.java)

    @Before fun start() {
        controller.create()
        service.onListenerConnected()
        manager.setNotificationListenerAccessGranted(component, true)
        PhoneBridge.setForeground(true)
        shadowOf(context.getSystemService(PowerManager::class.java)).setIsInteractive(true)
        shadowOf(context.getSystemService(KeyguardManager::class.java)).setKeyguardLocked(false)
    }
    @After fun stop() { controller.destroy(); PhoneBridge.setForeground(false) }

    private fun notification(id: Int, pkg: String = "com.tencent.mm", title: String = "小雨",
        text: String = "今天有点累，明天再聊吧", flags: Int = 0,
        user: UserHandle = Process.myUserHandle()): StatusBarNotification {
        val n = Notification.Builder(context, "chat").setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title).setContentText(text).setCategory(Notification.CATEGORY_MESSAGE).build()
        n.flags = flags
        return StatusBarNotification(pkg, pkg, id, "synthetic", 1, 1, 0, n, user, id.toLong())
    }
    private fun add(sbn: StatusBarNotification) { shadowOf(service).addActiveNotification(sbn) }
    private fun call(args: Map<String, Any> = mapOf("package_name" to "com.tencent.mm")) = JSONObject(
        PhoneBridge.exchange(context, "call", JSONObject().put("name", "read_chat_notifications")
            .put("arguments", JSONObject(args)).toString(), 2000))

    @Test fun sdkTransportReadsLatestPreviewWithoutRemoteInputAndDoesNotDismissIt() {
        add(notification(1)); add(notification(2, text = "合成测试第二条"))
        add(notification(3, pkg = "com.tencent.mobileqq", text = "其他应用不应读到"))
        val result = call()
        assertEquals("succeeded", result.getString("status"))
        assertEquals(1, result.getInt("count"))
        assertEquals("合成测试第二条", result.getJSONArray("notifications").getJSONObject(0).getString("text"))
        assertTrue(result.getBoolean("more_available"))
        assertEquals(3, service.activeNotifications.size)
    }

    @Test fun titleFilterDoesNotExpandToOtherPeopleAndBoundsText() {
        add(notification(1, text = "字".repeat(2000)))
        add(notification(2, title = "其他人"))
        val result = call(mapOf("package_name" to "com.tencent.mm", "title_filter" to "小雨", "limit" to 3))
        assertEquals(1, result.getInt("count"))
        val preview = result.getJSONArray("notifications").getJSONObject(0)
        assertEquals(800, preview.getString("text").length)
        assertTrue(preview.getBoolean("truncated"))
        assertEquals(0, call(mapOf("package_name" to "com.tencent.mm", "title_filter" to "不存在" )).getInt("count"))
    }

    @Test fun ignoresOtherProfilesSummaryServiceAndCallNotifications() {
        add(notification(1, flags = Notification.FLAG_GROUP_SUMMARY))
        add(notification(2, flags = Notification.FLAG_ONGOING_EVENT))
        add(notification(3, user = UserHandle.getUserHandleForUid(1000000)))
        val call = notification(4)
        call.notification.category = Notification.CATEGORY_CALL
        add(call)
        assertEquals(0, call().getInt("count"))
    }

    @Test fun emptyOrClearedPreviewIsNotInventedOrRetained() {
        val sbn = notification(1, text = "")
        add(sbn)
        val result = call()
        assertFalse(result.getJSONArray("notifications").getJSONObject(0).getBoolean("content_available"))
        service.cancelNotification(sbn.key) // Synthetic user clearing a notification.
        assertEquals(0, call().getInt("count"))
    }

    @Test fun noPermissionNoConnectionBackgroundAndLockFailClosed() {
        add(notification(1))
        manager.setNotificationListenerAccessGranted(component, false)
        manager.setNotificationListenerAccessGranted(ComponentName(context.packageName,
            "com.xinyu.xinyu_flutter.MusicNotificationListener"), true)
        assertEquals("failed", call().getString("status"))
        manager.setNotificationListenerAccessGranted(component, true)
        service.onListenerDisconnected()
        assertEquals("failed", call().getString("status"))
        service.onListenerConnected()
        PhoneBridge.setForeground(false)
        assertEquals("failed", call().getString("status"))
        PhoneBridge.setForeground(true)
        shadowOf(context.getSystemService(KeyguardManager::class.java)).setKeyguardLocked(true)
        assertEquals("failed", call().getString("status"))
        shadowOf(context.getSystemService(KeyguardManager::class.java)).setKeyguardLocked(false)
        shadowOf(context.getSystemService(PowerManager::class.java)).setIsInteractive(false)
        assertEquals("failed", call().getString("status"))
    }

    @Test fun nativeBoundaryRejectsOtherAppsExpandedLimitsAndInvalidFilters() {
        for (args in listOf(mapOf("package_name" to "com.android.mms"),
            mapOf("package_name" to "com.tencent.mm", "limit" to 4),
            mapOf("package_name" to "com.tencent.mm", "limit" to true),
            mapOf("package_name" to "com.tencent.mm", "title_filter" to " "),
            mapOf("package_name" to "com.tencent.mm", "send" to "hello"))) {
            assertEquals("failed", call(args).getString("status"))
        }
    }

    @Test fun callbacksDoNotCacheMessagesAndReadAfterDestroyFails() {
        service.onNotificationPosted(notification(1))
        assertEquals(0, call().getInt("count"))
        service.onDestroy()
        assertEquals("failed", call().getString("status"))
    }
}
