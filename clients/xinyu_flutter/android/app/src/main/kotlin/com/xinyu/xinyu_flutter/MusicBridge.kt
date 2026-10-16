package com.xinyu.xinyu_flutter

import android.app.Activity
import android.app.NotificationManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.media.MediaMetadata
import android.media.session.MediaController
import android.media.session.MediaSessionManager
import android.media.session.PlaybackState
import android.net.Uri
import android.os.Build
import android.os.SystemClock
import android.provider.Settings
import android.service.notification.NotificationListenerService
import java.lang.ref.WeakReference
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import org.json.JSONObject

// The OS grant enables media-session discovery. Notification contents are never
// processed, stored or forwarded; no onNotificationPosted implementation exists.
class MusicNotificationListener : NotificationListenerService()

object MusicBridge {
    private class NoMediaSession : IllegalStateException("网易云尚未开始播放。")
    private const val PACKAGE = "com.netease.cloudmusic"
    @Volatile private var foreground = WeakReference<Activity>(null)

    fun resumed(activity: Activity) { foreground = WeakReference(activity) }
    fun paused(activity: Activity) {
        if (foreground.get() === activity) foreground.clear()
    }

    private fun allowed(context: Context): Boolean {
        val component = ComponentName(context, MusicNotificationListener::class.java)
        return if (Build.VERSION.SDK_INT >= 27) {
            context.getSystemService(NotificationManager::class.java)
                .isNotificationListenerAccessGranted(component)
        } else {
            Settings.Secure.getString(context.contentResolver, "enabled_notification_listeners")
                ?.split(':')?.mapNotNull(ComponentName::unflattenFromString)
                ?.contains(component) == true
        }
    }

    fun openPermissionSettings(activity: Activity) {
        activity.startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
    }

    private fun session(context: Context): MediaController {
        check(allowed(context)) { "请先在系统设置中允许心隅的通知使用权。" }
        val manager = context.getSystemService(MediaSessionManager::class.java)
        val matches = manager.getActiveSessions(
            ComponentName(context, MusicNotificationListener::class.java)
        ).filter { it.packageName == PACKAGE }
        if (matches.isEmpty()) throw NoMediaSession()
        check(matches.size == 1) { "发现多个网易云媒体会话，请保留一个播放器后重试。" }
        return matches.single()
    }

    private val controls = mapOf(
        "play" to PlaybackState.ACTION_PLAY,
        "pause" to PlaybackState.ACTION_PAUSE,
        "next" to PlaybackState.ACTION_SKIP_TO_NEXT,
        "previous" to PlaybackState.ACTION_SKIP_TO_PREVIOUS
    )

    private fun snapshot(controller: MediaController): JSONObject {
        val metadata = controller.metadata
        val playback = controller.playbackState
        val actions = playback?.actions ?: 0L
        fun text(key: String) = metadata?.getText(key)?.toString()?.take(200) ?: ""
        return JSONObject().put("status", "succeeded").put("available", true)
            .put("source", PACKAGE)
            .put("title", text(MediaMetadata.METADATA_KEY_TITLE))
            .put("artist", text(MediaMetadata.METADATA_KEY_ARTIST))
            .put("album", text(MediaMetadata.METADATA_KEY_ALBUM))
            .put("playback", when (playback?.state) {
                PlaybackState.STATE_PLAYING -> "playing"
                PlaybackState.STATE_PAUSED -> "paused"
                PlaybackState.STATE_STOPPED -> "stopped"
                PlaybackState.STATE_BUFFERING -> "changing"
                else -> "unknown"
            })
            .put("controls", JSONObject().apply {
                controls.forEach { (name, flag) -> put(name, actions and flag != 0L) }
                put("seek", actions and PlaybackState.ACTION_SEEK_TO != 0L)
            })
            .apply {
                val mediaId = text(MediaMetadata.METADATA_KEY_MEDIA_ID)
                val identifier = if (Regex("[1-9][0-9]{0,17}").matches(mediaId)) mediaId else {
                    val uri = Uri.parse(mediaId)
                    when {
                        uri.scheme == "orpheus" && uri.host == "song" -> uri.lastPathSegment
                        uri.scheme in listOf("https", "http") && uri.host == "music.163.com" &&
                            uri.path == "/song" -> uri.getQueryParameter("id")
                        else -> null
                    }
                }
                if (identifier != null && Regex("[1-9][0-9]{0,17}").matches(identifier)) {
                    put("song_id", identifier)
                }
                val duration = metadata?.getLong(MediaMetadata.METADATA_KEY_DURATION) ?: 0L
                if (duration in 1..86_400_000L) {
                    put("duration_ms", duration)
                    if (playback != null && playback.position >= 0 &&
                        playback.lastPositionUpdateTime > 0 && playback.playbackSpeed.isFinite() &&
                        playback.playbackSpeed in 0f..4f) {
                        val elapsed = (SystemClock.elapsedRealtime() -
                            playback.lastPositionUpdateTime).coerceAtLeast(0)
                        val advance = if (playback.state == PlaybackState.STATE_PLAYING)
                            (elapsed * playback.playbackSpeed).toLong() else 0L
                        put("position_ms", (playback.position + advance).coerceIn(0, duration))
                        put("playback_rate", playback.playbackSpeed.toDouble())
                        put("sampled_at_ms", System.currentTimeMillis())
                    }
                }
            }
    }

    private fun state(context: Context): JSONObject = try {
        snapshot(session(context)).put("permission", true)
    } catch (error: NoMediaSession) {
        JSONObject().put("status", "succeeded").put("available", false)
            .put("permission", true).put("idle", true).put("reason", "no_session")
            .put("message", error.message)
    } catch (error: IllegalStateException) {
        failure(error.message ?: "网易云播放器尚未就绪。")
            .put("available", false).put("permission", allowed(context))
    }

    private fun control(context: Context, action: String): JSONObject {
        val flag = controls[action] ?: return failure("不支持这项播放操作。")
        val target = session(context)
        val before = snapshot(target)
        if ((target.playbackState?.actions ?: 0L) and flag == 0L) {
            return failure("网易云当前不支持这项操作。")
        }
        var dispatched = false
        try {
            when (action) {
                "play" -> target.transportControls.play()
                "pause" -> target.transportControls.pause()
                "next" -> target.transportControls.skipToNext()
                "previous" -> target.transportControls.skipToPrevious()
            }
            dispatched = true
            repeat(6) {
                SystemClock.sleep(150)
                // Recheck the grant and the exact app; never use the default session.
                val after = snapshot(session(context))
                val verified = when (action) {
                    "play" -> after.optString("playback") == "playing"
                    "pause" -> after.optString("playback") == "paused"
                    else -> listOf("title", "artist", "album").any {
                        before.optString(it) != after.optString(it)
                    }
                }
                if (verified) return JSONObject().put("status", "succeeded")
                    .put("verified", true).put("state", after)
            }
        } catch (_: Exception) {
            if (!dispatched) return failure("播放操作未能提交，请查看网易云。")
        }
        return JSONObject().put("status", "uncertain").put("verified", false)
            .put("message", "已提交播放操作，结果尚未确认。请查看网易云，不要连续重试。")
    }

    private fun seek(context: Context, args: JSONObject): JSONObject {
        val target = session(context)
        val before = snapshot(target)
        val keys = listOf("title", "artist", "album")
        if (keys.any { before.optString(it) != args.optString(it) }) {
            return failure("歌曲已变化，请重新调整进度。")
        }
        val position = args.optLong("position_ms", -1)
        val duration = before.optLong("duration_ms", 0)
        if (!before.getJSONObject("controls").optBoolean("seek") || duration <= 0) {
            return failure("网易云未开放进度跳转，请在网易云内调整播放位置。")
        }
        if (position !in 0..duration) return failure("播放位置超出当前歌曲范围。")
        var dispatched = false
        try {
            dispatched = true
            target.transportControls.seekTo(position)
            repeat(6) {
                SystemClock.sleep(150)
                val after = snapshot(session(context))
                if (keys.any { after.optString(it) != before.optString(it) }) {
                    return JSONObject().put("status", "uncertain")
                        .put("message", "歌曲已变化，请查看网易云确认播放位置。")
                }
                if (after.has("position_ms") &&
                    kotlin.math.abs(after.getLong("position_ms") - position) <= 2000) {
                    return JSONObject().put("status", "succeeded")
                        .put("verified", true).put("state", after)
                }
            }
        } catch (_: Exception) {
            if (!dispatched) return failure("进度跳转未能提交。")
        }
        return JSONObject().put("status", "uncertain").put("verified", false)
            .put("message", "跳转请求已提交，但未收到位置确认，请查看网易云，勿连续重试。")
    }

    private fun openSong(songId: String): JSONObject {
        if (!Regex("[0-9]{1,18}").matches(songId) || songId.all { it == '0' }) {
            return failure("请提供有效的歌曲 ID。")
        }
        return launch(songId) {
            Intent(Intent.ACTION_VIEW, Uri.parse("orpheus://song/$songId")).setPackage(PACKAGE)
        }
    }

    private fun openApp(): JSONObject = launch(null) {
        it.packageManager.getLaunchIntentForPackage(PACKAGE)
    }

    private fun launch(songId: String?, intent: (Activity) -> Intent?): JSONObject {
        val activity = foreground.get() ?: return failure("请回到心隅前台，再打开网易云。")
        val latch = CountDownLatch(1)
        val expired = AtomicBoolean(false)
        var opened = false
        activity.runOnUiThread {
            try {
                if (!expired.get() && foreground.get() === activity && !activity.isFinishing) {
                    intent(activity)?.let {
                        activity.startActivity(it)
                        opened = true
                    }
                }
            } catch (_: Exception) { } finally { latch.countDown() }
        }
        if (!latch.await(2, TimeUnit.SECONDS)) {
            expired.set(true)
            return JSONObject().put("status", "uncertain")
                .put("message", "打开结果尚未确认，请查看网易云。")
        }
        if (!opened) return failure("无法打开网易云，请确认已安装网易云音乐。")
        return JSONObject().put("status", "succeeded").apply {
                if (songId != null) put("song_id", songId)
            }
            .put("delivery", "requested").put("playback_verified", false)
            .put("message", if (songId == null) "已请求打开网易云，没有选歌或开始播放。"
                else "已交给网易云打开，实际播放及歌曲权限请在客户端确认。")
    }

    private fun failure(message: String) = JSONObject()
        .put("status", "failed").put("message", message)

    /** Called by the embedded Python worker, never Flutter's main/UI thread. */
    @JvmStatic fun call(context: Context, name: String, raw: String): String {
        return try {
            val arguments = JSONObject(raw)
            when (name) {
                "netease_account" -> NetEaseAccount.current()
                "netease_status" -> JSONObject().put("status", "succeeded")
                    .put("platform", "android").put("media", state(context))
                    .put("installed", try {
                        context.packageManager.getApplicationInfo(PACKAGE, 0); true
                    } catch (_: Exception) { false })
                "netease_playback_state" -> state(context)
                "netease_control" -> control(context, arguments.optString("action"))
                "netease_seek" -> seek(context, arguments)
                "netease_open_song" -> openSong(arguments.optString("song_id"))
                "netease_open_app" -> openApp()
                else -> failure("不支持这项音乐操作。")
            }.toString()
        } catch (error: IllegalStateException) {
            failure(error.message ?: "网易云播放器尚未就绪。").toString()
        } catch (_: SecurityException) {
            failure("媒体控制权限已变化，请重新检查系统授权。").toString()
        } catch (_: Exception) {
            failure("音乐连接暂不可用，请在网易云核对播放状态。").toString()
        }
    }
}
