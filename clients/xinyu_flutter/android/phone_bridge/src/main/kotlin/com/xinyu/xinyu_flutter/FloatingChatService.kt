package com.xinyu.xinyu_flutter

import android.app.*
import android.content.*
import android.content.pm.ServiceInfo
import android.os.*
import android.provider.Settings

/** User-started, visible session; never restarted at boot or after process death. */
class FloatingChatService : Service() {
    private var window: FloatingChatWindow? = null
    private var closing = false
    private val handler = Handler(Looper.getMainLooper())
    private val screenOff = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) { closeWhenIdle() }
    }
    private val check = object : Runnable {
        override fun run() {
            val power = getSystemService(PowerManager::class.java)
            val lock = getSystemService(KeyguardManager::class.java)
            if (!Settings.canDrawOverlays(this@FloatingChatService) ||
                !power.isInteractive || lock.isKeyguardLocked) {
                closeWhenIdle()
            } else handler.postDelayed(this, 1500)
        }
    }

    override fun onCreate() {
        super.onCreate()
        if (Build.VERSION.SDK_INT >= 33) {
            registerReceiver(screenOff, IntentFilter(Intent.ACTION_SCREEN_OFF), RECEIVER_NOT_EXPORTED)
        } else {
            @Suppress("DEPRECATION")
            registerReceiver(screenOff, IntentFilter(Intent.ACTION_SCREEN_OFF))
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == CLOSE) {
            if (closing) FloatingChatSession.host?.event("cancel", mapOf("conversation" to FloatingChatSession.state["conversation"]))
            closeWhenIdle()
            return START_NOT_STICKY
        }
        if (FloatingChatSession.host == null ||
            !Settings.canDrawOverlays(this) || Build.VERSION.SDK_INT < 26) {
            stopSelf()
            return START_NOT_STICKY
        }
        try {
            val notification = notice()
            if (Build.VERSION.SDK_INT >= 34) {
                startForeground(7302, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
            } else startForeground(7302, notification)
            FloatingChatSession.service = this
            closing = false
            if (window == null) {
                window = FloatingChatWindow(this, onClose = { closeWhenIdle() }, onOpenMain = {
                    window?.collapse()
                    packageManager.getLaunchIntentForPackage(packageName)?.let {
                        it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
                        startActivity(it)
                    }
                })
                window?.show()
            }
            handler.removeCallbacks(check)
            handler.post(check)
            render()
            FloatingChatSession.host?.changed()
        } catch (_: RuntimeException) {
            stopSelf()
        }
        return START_NOT_STICKY
    }

    fun render() {
        if (closing) {
            if (FloatingChatSession.state["busy"] != true) stopSelf()
            return
        }
        try { window?.render(FloatingChatSession.state) }
        catch (_: RuntimeException) { stopSelf() }
    }

    private fun closeWhenIdle() {
        closing = true
        window?.dispose()
        window = null
        handler.removeCallbacks(check)
        if (FloatingChatSession.state["busy"] == true) {
            getSystemService(NotificationManager::class.java).notify(7302, notice(finishing = true))
        } else stopSelf()
    }

    override fun onConfigurationChanged(config: android.content.res.Configuration) {
        super.onConfigurationChanged(config)
        window?.reflow()
    }

    private fun notice(finishing: Boolean = false): Notification {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL, "悬浮陪聊", NotificationManager.IMPORTANCE_LOW))
        val close = PendingIntent.getService(this, 7302, Intent(this, FloatingChatService::class.java)
            .setAction(CLOSE), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val open = packageManager.getLaunchIntentForPackage(packageName)?.let {
            PendingIntent.getActivity(this, 7302, it, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        }
        return Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("心隅 · 悬浮陪聊")
            .setContentText(if (finishing) "正在完成这次回复，完成后结束小窗会话" else "小窗正在运行，点此回到完整对话")
            .setContentIntent(open).setOngoing(true).setOnlyAlertOnce(true)
            .setVisibility(Notification.VISIBILITY_PRIVATE)
            .addAction(Notification.Action.Builder(null, if (finishing) "停止回复并关闭" else "关闭小窗", close).build()).build()
    }

    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        unregisterReceiver(screenOff)
        window?.dispose()
        window = null
        if (FloatingChatSession.service === this) FloatingChatSession.service = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        FloatingChatSession.host?.stopped()
        FloatingChatSession.clear()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?) = null
    companion object {
        private const val CHANNEL = "xinyu_floating_chat"
        const val CLOSE = "com.xinyu.CLOSE_FLOATING_CHAT"
    }
}
