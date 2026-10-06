package com.xinyu.xinyu_flutter

import android.Manifest
import android.app.Activity
import android.app.ActivityManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.job.JobInfo
import android.app.job.JobScheduler
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel

object ChatNotifications {
    private const val CHANNEL = "xinyu_messages"
    private const val JOB_ID = 4207
    private const val PREFIX = "xinyu_chat:"
    const val PERMISSION_REQUEST = 4208
    @Volatile var visibleConversation: String? = null

    private fun manager(context: Context) = context.getSystemService(NotificationManager::class.java)
    fun allowed(context: Context): Boolean = manager(context).areNotificationsEnabled() &&
        (Build.VERSION.SDK_INT < 33 || context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) &&
        (Build.VERSION.SDK_INT < 26 || manager(context).getNotificationChannel(CHANNEL)?.importance != NotificationManager.IMPORTANCE_NONE)

    private fun channel(context: Context) {
        if (Build.VERSION.SDK_INT >= 26) {
            manager(context).createNotificationChannel(NotificationChannel(CHANNEL, "聊天消息", NotificationManager.IMPORTANCE_HIGH).apply {
                description = "聊天、纪念日与约定提醒"
                lockscreenVisibility = Notification.VISIBILITY_PRIVATE
            })
        }
    }

    fun configure(context: Context, enabled: Boolean): Boolean {
        channel(context)
        val scheduler = context.getSystemService(JobScheduler::class.java)
        if (!enabled || !allowed(context)) {
            scheduler.cancel(JOB_ID)
            if (!enabled) reconcile(context, emptySet())
            return false
        }
        // Upgrade the persisted 0.2.3 network-only job so date reminders can run
        // offline. Keep an already compatible job without resetting its interval.
        @Suppress("DEPRECATION")
        val compatible = scheduler.getPendingJob(JOB_ID)?.networkType == JobInfo.NETWORK_TYPE_NONE
        if (compatible) return true
        val job = JobInfo.Builder(JOB_ID, ComponentName(context, OutreachJobService::class.java))
            .setPersisted(true)
            .setPeriodic(15 * 60 * 1000L)
            .build()
        return scheduler.schedule(job) == JobScheduler.RESULT_SUCCESS
    }

    fun post(context: Context, conversation: String, title: String, text: String): Boolean {
        if (!allowed(context) || visibleConversation == conversation) return false
        channel(context)
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP
            data = Uri.Builder().scheme("xinyu").authority("chat").appendPath(conversation).build()
            putExtra("conversation_id", conversation)
        }
        val pending = PendingIntent.getActivity(context, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        @Suppress("DEPRECATION")
        fun builder(): Notification.Builder = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(context, CHANNEL) else Notification.Builder(context)
        val public = builder().setSmallIcon(R.drawable.ic_chat_notification)
            .setContentTitle("心隅").setContentText("收到一条新消息").build()
        @Suppress("DEPRECATION")
        val notification = builder().setSmallIcon(R.drawable.ic_chat_notification)
            .setContentTitle(title).setContentText(text).setStyle(Notification.BigTextStyle().bigText(text))
            .setCategory(Notification.CATEGORY_MESSAGE).setPriority(Notification.PRIORITY_HIGH)
            .setVisibility(Notification.VISIBILITY_PRIVATE).setPublicVersion(public)
            .setContentIntent(pending).setAutoCancel(true).setOnlyAlertOnce(true)
            .setDefaults(Notification.DEFAULT_ALL).build()
        return try {
            manager(context).notify(PREFIX + conversation, 1, notification)
            true
        } catch (_: SecurityException) { false }
    }

    fun read(context: Context, conversation: String) { manager(context).cancel(PREFIX + conversation, 1) }
    fun reconcile(context: Context, valid: Set<String>) {
        for (notice in manager(context).activeNotifications) {
            val tag = notice.tag ?: continue
            if (tag.startsWith(PREFIX) && tag.removePrefix(PREFIX) !in valid) manager(context).cancel(tag, notice.id)
        }
    }

    fun status(context: Context): Map<String, Any> = mapOf(
        "supported" to true,
        "allowed" to allowed(context),
        "scheduled" to (context.getSystemService(JobScheduler::class.java).getPendingJob(JOB_ID) != null),
        "restricted" to (Build.VERSION.SDK_INT >= 28 && context.getSystemService(ActivityManager::class.java).isBackgroundRestricted)
    )

    private fun openSettings(activity: Activity) {
        val intent = if (Build.VERSION.SDK_INT >= 26) Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, activity.packageName)
            else Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + activity.packageName))
        activity.startActivity(intent)
    }

    fun call(activity: Activity, call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "status" -> result.success(status(activity))
            "configure" -> result.success(configure(activity, call.argument<Boolean>("enabled") == true))
            "openSettings" -> { openSettings(activity); result.success(null) }
            "requestPermission" -> {
                channel(activity)
                if (Build.VERSION.SDK_INT >= 33 && activity.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                    activity.requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), PERMISSION_REQUEST)
                } else if (!allowed(activity)) {
                    openSettings(activity)
                }
                result.success(null)
            }
            "visible" -> { visibleConversation = call.argument<String>("conversation"); result.success(null) }
            "read" -> { call.argument<String>("conversation")?.let { read(activity, it) }; result.success(null) }
            "reconcile" -> { reconcile(activity, (call.argument<List<String>>("valid") ?: emptyList()).toSet()); result.success(null) }
            "test" -> { result.success(post(activity, "test", "心隅", "消息提醒已开启")) }
            else -> result.notImplemented()
        }
    }
}
