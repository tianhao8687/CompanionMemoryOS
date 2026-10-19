package com.xinyu.xinyu_flutter

import android.app.KeyguardManager
import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorManager
import android.os.PowerManager
import android.os.SystemClock
import org.json.JSONObject

/** Validates upstream readings without changing the vendored SDK or retaining a listener. */
internal object EnvironmentSensors {
    fun canRead(context: Context): Boolean = PhoneBridge.foreground &&
        (context.getSystemService(Context.POWER_SERVICE) as PowerManager).isInteractive &&
        !(context.getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager).isKeyguardLocked

    fun isNear(distance: Double, maximum: Double): Boolean? {
        if (!distance.isFinite() || !maximum.isFinite() || maximum <= 0 || distance < 0 || distance > maximum) return null
        // Binary sensors report maximumRange when far; it is not always 5 cm.
        return distance < minOf(5.0, maximum)
    }

    fun normalize(context: Context, name: String, data: JSONObject): JSONObject {
        if (!canRead(context)) return PhoneBridge.failure("采样时已离开心隅前台，本次读数已丢弃。")
        val rows = data.optJSONArray("readings")
            ?: return PhoneBridge.failure("未收到有效传感器读数。")
        if (rows.length() !in 1..256) return PhoneBridge.failure("传感器读数数量无效。")
        val now = SystemClock.elapsedRealtimeNanos()
        val maximum = if (name == "get_proximity") {
            (context.getSystemService(Context.SENSOR_SERVICE) as SensorManager)
                .getDefaultSensor(Sensor.TYPE_PROXIMITY)?.maximumRange?.toDouble()
                ?: return PhoneBridge.failure("此设备没有可用的接近传感器。")
        } else 1_000_000.0
        for (i in 0 until rows.length()) {
            val row = rows.getJSONObject(i)
            val age = (now - row.optLong("timestamp", -1)) / 1_000_000.0
            val value = row.optDouble(if (name == "get_light_level") "lux" else "distance_cm", Double.NaN)
            if (age !in 0.0..6000.0 || !value.isFinite() || value !in 0.0..maximum) {
                return PhoneBridge.failure("传感器读数无效或已过期，保持现状。")
            }
            if (name == "get_proximity") row.put("is_near", isNear(value, maximum))
        }
        val latest = rows.getJSONObject(rows.length() - 1)
        if (name == "get_proximity") {
            data.put("is_near", latest.getBoolean("is_near")).put("maximum_range_cm", maximum)
        }
        return data.put("status", "succeeded").put("foreground", true)
            .put("age_ms", (now - latest.getLong("timestamp")) / 1_000_000)
    }
}
