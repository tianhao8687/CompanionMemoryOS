package com.xinyu.xinyu_flutter

import android.content.Context
import android.media.AudioManager
import android.view.accessibility.AccessibilityNodeInfo
import io.droidmcp.accessibility.DroidMcpAccessibilityService
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Robolectric
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)
class PhoneBridgeTest {
    private val context get() = RuntimeEnvironment.getApplication()
    private fun exchange(operation: String, payload: JSONObject = JSONObject()) =
        JSONObject(PhoneBridge.exchange(context, operation, payload.toString(), 2000))
    private fun call(name: String, args: Map<String, Any> = emptyMap()) = exchange("call",
        JSONObject().put("name", name).put("arguments", JSONObject(args)))

    @Test fun catalogContainsOnlySelectedSdkToolsAndNoImplicitActions() {
        val tools = exchange("catalog").getJSONArray("tools")
        val names = (0 until tools.length()).map { tools.getJSONObject(it).getString("name") }.toSet()
        assertEquals(30, names.size)
        assertTrue(names.contains("read_chat_notifications"))
        assertTrue(names.containsAll(setOf("vibrate_pattern", "cancel_vibration")))
        assertTrue(names.containsAll(setOf("get_light_level", "get_proximity")))
        assertTrue(names.containsAll(setOf("set_volume", "create_alarm", "query_screen", "click_node", "long_click_node")))
        assertFalse(names.contains("gesture"))
        assertFalse(names.any { it.contains("shell") || it.contains("sms") || it.contains("screenshot") })
        assertTrue(exchange("state").getBoolean("supported"))
    }

    @Test @Config(sdk = [24]) fun olderAndroidKeepsFeatureDisabled() {
        assertFalse(exchange("state").getBoolean("supported"))
        assertFalse(exchange("catalog").getBoolean("supported"))
        assertEquals("failed", call("set_volume", mapOf("level" to 2)).getString("status"))
    }

    @Test fun volumeUsesActualSdkAndReadsBackTheResult() {
        val audio = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        val alarm = audio.getStreamVolume(AudioManager.STREAM_ALARM)
        val result = call("set_volume", mapOf("level" to 2))
        assertEquals("succeeded", result.getString("status"))
        assertEquals(2, audio.getStreamVolume(AudioManager.STREAM_MUSIC))
        assertEquals(2, result.getInt("volume_media"))
        assertEquals(alarm, audio.getStreamVolume(AudioManager.STREAM_ALARM))
        assertEquals("failed", call("set_volume", mapOf("stream" to "alarm", "level" to 0)).getString("status"))
        assertEquals(alarm, audio.getStreamVolume(AudioManager.STREAM_ALARM))
    }

    @Test fun missingPermissionAndUnknownToolFailWithoutDispatch() {
        assertEquals("failed", call("query_screen", mapOf("expected_package" to "synthetic.app")).getString("status"))
        assertEquals("failed", call("execute_shell", mapOf("command" to "ignored")).getString("status"))
        assertEquals("failed", call("set_brightness", mapOf("level" to 0)).getString("status"))
    }

    @Test fun companionshipDoesNotOverwriteChangedVolumeOrInterruptCalls() {
        val audio = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        audio.setStreamVolume(AudioManager.STREAM_MUSIC, 5, 0)
        assertEquals("failed", call("set_volume", mapOf("level" to 2,
            "expected_level" to 4)).getString("status"))
        assertEquals(5, audio.getStreamVolume(AudioManager.STREAM_MUSIC))
        audio.mode = AudioManager.MODE_IN_CALL
        assertEquals("failed", call("set_volume", mapOf("level" to 2,
            "expected_level" to 5, "require_idle_audio" to true)).getString("status"))
        assertEquals(5, audio.getStreamVolume(AudioManager.STREAM_MUSIC))
        audio.mode = AudioManager.MODE_NORMAL
        assertEquals("succeeded", call("set_volume", mapOf("level" to 3,
            "expected_level" to 5, "require_idle_audio" to true)).getString("status"))
        val state = call("get_settings")
        assertEquals(0, state.getInt("audio_mode"))
        assertTrue(state.has("brightness_mode"))
        assertTrue(state.has("music_active"))
    }

    @Test fun screenReadsRequireTheTargetAndMaskPasswordNodes() {
        val lifecycle = Robolectric.buildService(SyntheticScreenService::class.java).create()
        val service = lifecycle.get()
        service.connect()
        try {
            assertEquals("failed", call("query_screen", mapOf("expected_package" to "other.app")).getString("status"))
            val result = call("query_screen", mapOf("expected_package" to "synthetic.app"))
            assertEquals("succeeded", result.getString("status"))
            assertTrue(result.getJSONArray("nodes").length() > 0)
            assertFalse(result.toString().contains("SYNTHETIC_PASSWORD"))
            service.target = "com.android.settings"
            assertEquals("failed", call("query_screen", mapOf("expected_package" to service.target)).getString("status"))
        } finally { lifecycle.destroy() }
    }

    @Test fun screenContentIsDiscardedIfForegroundChangesDuringTheRead() {
        val lifecycle = Robolectric.buildService(SyntheticScreenService::class.java).create()
        val service = lifecycle.get()
        service.switchAfterFirstRead = true
        service.connect()
        try {
            val result = call("query_screen", mapOf("expected_package" to "synthetic.app"))
            assertEquals("failed", result.getString("status"))
            assertFalse(result.has("nodes"))
        } finally { lifecycle.destroy() }
    }

    @Test fun gesturesRequireSupportedOsAndLongPressRequiresTargetApp() {
        val lifecycle = Robolectric.buildService(SyntheticScreenService::class.java).create()
        val service = lifecycle.get()
        service.connect()
        try {
            for (args in listOf(
                mapOf("expected_package" to "other.app", "points" to listOf(listOf(40, 200), listOf(40, 300))),
                mapOf("expected_package" to "synthetic.app", "points" to listOf(listOf(40, 20), listOf(40, 300))),
                mapOf("expected_package" to "synthetic.app", "points" to listOf(listOf(40, 200))),
                mapOf("expected_package" to "synthetic.app", "points" to List(17) { listOf(40, 200) }),
            )) assertEquals("failed", call("gesture", args).getString("status"))
            assertEquals("failed", call("long_click_node", mapOf("expected_package" to "other.app", "text" to "target")).getString("status"))
        } finally { lifecycle.destroy() }
    }
}

/** Synthetic tree only; never binds to a real device or collects window events. */
class SyntheticScreenService : DroidMcpAccessibilityService() {
    var target = "synthetic.app"
    var switchAfterFirstRead = false
    private var reads = 0
    fun connect() { super.onServiceConnected() }

    @Suppress("DEPRECATION")
    override fun getRootInActiveWindow(): AccessibilityNodeInfo = AccessibilityNodeInfo.obtain().apply {
        packageName = if (switchAfterFirstRead && reads++ > 0) "other.app" else target
        text = "SYNTHETIC_PASSWORD"
        isPassword = true
        setBoundsInScreen(android.graphics.Rect(0, 100, 1080, 1800))
    }
}
