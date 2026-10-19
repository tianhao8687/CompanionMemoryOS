package com.xinyu.xinyu_flutter

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)
class EnvironmentSensorsTest {
    @Test fun binaryProximityRespectsDeviceRange() {
        assertEquals(false, EnvironmentSensors.isNear(1.0, 1.0))
        assertEquals(true, EnvironmentSensors.isNear(0.0, 1.0))
        assertEquals(false, EnvironmentSensors.isNear(3.0, 3.0))
        assertEquals(false, EnvironmentSensors.isNear(5.0, 10.0))
        assertEquals(true, EnvironmentSensors.isNear(2.0, 10.0))
        assertNull(EnvironmentSensors.isNear(6.0, 5.0))
        assertNull(EnvironmentSensors.isNear(Double.NaN, 5.0))
        assertNull(EnvironmentSensors.isNear(0.0, 0.0))
    }

    @Test fun backgroundReadsAndProactiveWritesAreRejected() {
        PhoneBridge.setForeground(false)
        for (name in listOf("get_light_level", "get_proximity", "set_brightness")) {
            val args = if (name == "set_brightness") mapOf("level" to 100, "require_foreground" to true) else emptyMap()
            val payload = JSONObject().put("name", name).put("arguments", JSONObject(args))
            val result = JSONObject(PhoneBridge.exchange(RuntimeEnvironment.getApplication(), "call", payload.toString(), 2000))
            assertEquals("failed", result.getString("status"))
            assertTrue(result.getString("message").contains("前台"))
        }
    }
}
