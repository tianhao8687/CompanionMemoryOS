package com.xinyu.xinyu_flutter

import android.app.KeyguardManager
import android.content.Context
import android.media.AudioManager
import android.os.Vibrator
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)
class HapticPatternsTest {
    private val context get() = RuntimeEnvironment.getApplication()
    @Suppress("DEPRECATION")
    private val vibrator get() = context.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
    private fun call(name: String, args: Map<String, Any> = emptyMap()): JSONObject =
        JSONObject(PhoneBridge.exchange(context, "call", JSONObject()
            .put("name", name).put("arguments", JSONObject(args)).toString(), 2000))

    @Before fun ready() {
        PhoneBridge.setForeground(true)
        shadowOf(vibrator).setHasVibrator(true)
    }

    @After fun reset() {
        call("cancel_vibration")
        PhoneBridge.setForeground(false)
    }

    @Test fun playsUpstreamWaveformsOnceAndStopsWithoutForegroundRequirement() {
        for (pattern in listOf(listOf(0, 80, 200, 80), listOf(0, 80, 2200, 80, 2200, 80))) {
            val result = call("vibrate_pattern", mapOf("timings" to pattern, "repeat" to -1))
            assertEquals("succeeded", result.getString("status"))
            assertEquals(pattern.sum(), result.getInt("total_duration_ms"))
            assertFalse(result.getBoolean("physical_effect_verified"))
            assertTrue(shadowOf(vibrator).isVibrating)
            assertArrayEquals(pattern.map { it.toLong() }.toLongArray(), shadowOf(vibrator).pattern)
            assertEquals(-1, shadowOf(vibrator).repeat)
        }
        PhoneBridge.setForeground(false)
        assertEquals("succeeded", call("cancel_vibration").getString("status"))
        assertFalse(shadowOf(vibrator).isVibrating)
        assertTrue(shadowOf(vibrator).isCancelled)
    }

    @Test fun rejectsLoopingLongAndMalformedInputsWithoutVibrating() {
        for (args in listOf(
            mapOf("timings" to listOf(0, 80, 200, 80), "repeat" to 0),
            mapOf("timings" to listOf(0, 10000)),
            mapOf("timings" to listOf(0, 80.5, 200, 80)),
            mapOf("timings" to listOf(0, "80", 200, 80)),
            mapOf("timings" to emptyList<Int>()),
        )) assertEquals("failed", call("vibrate_pattern", args).getString("status"))
        assertFalse(shadowOf(vibrator).isVibrating)
    }

    @Test fun backgroundLockedOrCallingPhoneDoesNotStartHaptics() {
        val args = mapOf("timings" to listOf(0, 80, 200, 80))
        PhoneBridge.setForeground(false)
        assertEquals("failed", call("vibrate_pattern", args).getString("status"))
        PhoneBridge.setForeground(true)
        val keyguard = context.getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager
        shadowOf(keyguard).setKeyguardLocked(true)
        assertEquals("failed", call("vibrate_pattern", args).getString("status"))
        shadowOf(keyguard).setKeyguardLocked(false)
        val audio = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        audio.mode = AudioManager.MODE_IN_CALL
        assertEquals("failed", call("vibrate_pattern", args).getString("status"))
        assertFalse(shadowOf(vibrator).isVibrating)
    }

    @Test fun missingVibratorIsReportedAsFailure() {
        shadowOf(vibrator).setHasVibrator(false)
        assertEquals("failed", call("vibrate_pattern", mapOf("timings" to listOf(0, 80, 200, 80)))
            .getString("status"))
    }
}
