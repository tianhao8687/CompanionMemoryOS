package com.xinyu.xinyu_flutter

/** In-memory projections only. The Flutter controller and SQLite own all chat data. */
object FloatingChatSession {
    interface Host {
        fun event(method: String, args: Map<String, Any?>, done: (Boolean) -> Unit = {})
        fun stopped()
        fun changed()
    }
    var host: Host? = null
    var service: FloatingChatService? = null
    var state: Map<String, Any?> = emptyMap()
        private set

    fun update(value: Map<String, Any?>) {
        state = value
        service?.render()
    }

    fun clear() { state = emptyMap() }
}

/** Pixel geometry, independent of Android window callbacks and orientation. */
class FloatingChatPosition(var right: Boolean = true, var fraction: Float = 0.3f) {
    var x = 0
    var y = 0
    fun layout(width: Int, height: Int, availableWidth: Int, availableHeight: Int, anchorHeight: Int = height) {
        x = if (right) (availableWidth - width).coerceAtLeast(0) else 0
        y = ((availableHeight - anchorHeight).coerceAtLeast(0) * fraction.coerceIn(0f, 1f)).toInt()
            .coerceAtMost((availableHeight - height).coerceAtLeast(0))
    }
    fun drag(x: Int, y: Int, width: Int, height: Int, availableWidth: Int, availableHeight: Int) {
        this.x = x.coerceIn(0, (availableWidth - width).coerceAtLeast(0))
        this.y = y.coerceIn(0, (availableHeight - height).coerceAtLeast(0))
    }
    fun snap(width: Int, height: Int, availableWidth: Int, availableHeight: Int, anchorHeight: Int = height) {
        right = x + width / 2 >= availableWidth / 2
        fraction = if (availableHeight > anchorHeight) y.toFloat() / (availableHeight - anchorHeight) else 0f
        layout(width, height, availableWidth, availableHeight, anchorHeight)
    }
}
