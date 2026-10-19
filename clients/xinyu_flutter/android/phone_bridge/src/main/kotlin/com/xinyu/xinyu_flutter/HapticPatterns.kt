package com.xinyu.xinyu_flutter

/** Bounds XinYu's gestures; waveform playback remains in the pinned droid-mcp SDK. */
internal object HapticPatterns {
    private val patterns = listOf(
        listOf(0, 80, 200, 80),
        listOf(0, 80, 2200, 80, 2200, 80),
    )

    fun valid(args: Map<String, Any>): Boolean {
        if (args.keys.any { it !in setOf("timings", "repeat") }) return false
        if (args.containsKey("repeat") && (args["repeat"] as? Number)?.toDouble() != -1.0) return false
        val timings = args["timings"] as? List<*> ?: return false
        return patterns.any { pattern ->
            timings.size == pattern.size && timings.indices.all { index ->
                (timings[index] as? Number)?.toDouble() == pattern[index].toDouble()
            }
        }
    }
}
