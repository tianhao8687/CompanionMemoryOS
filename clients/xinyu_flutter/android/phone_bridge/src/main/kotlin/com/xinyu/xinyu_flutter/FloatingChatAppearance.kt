package com.xinyu.xinyu_flutter

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.widget.Button

/** Small native views: no remote assets or second Flutter surface. */
internal object FloatingChatPalette {
    val ink = Color.rgb(23, 33, 50)
    val muted = Color.rgb(100, 113, 136)
    val accent = Color.rgb(74, 96, 125)
    val canvas = Color.rgb(247, 246, 244)
    val line = Color.rgb(224, 229, 235)
    val soft = Color.rgb(231, 237, 245)
    val unread = Color.rgb(182, 99, 80)

    fun shape(context: Context, color: Int, radius: Float, stroke: Boolean = false) = GradientDrawable().apply {
        setColor(color)
        cornerRadius = radius * context.resources.displayMetrics.density
        if (stroke) setStroke((context.resources.displayMetrics.density + .5f).toInt(), line)
    }
}

internal class FloatingChatIconButton(context: Context, private val icon: String, description: String,
    action: () -> Unit) : Button(context) {
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeWidth = 1.7f; strokeCap = Paint.Cap.ROUND; strokeJoin = Paint.Join.ROUND
    }
    init {
        text = ""; contentDescription = description
        minimumWidth = 0; minWidth = 0; minimumHeight = 0; minHeight = 0
        setPadding(0, 0, 0, 0)
        background = RippleDrawable(ColorStateList.valueOf(0x194A607D), null,
            FloatingChatPalette.shape(context, Color.WHITE, 14f))
        setOnClickListener { action() }
    }
    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val density = resources.displayMetrics.density
        canvas.save()
        canvas.translate(width / 2f, height / 2f)
        canvas.scale(density, density)
        if (icon == "send") {
            paint.style = Paint.Style.FILL
            paint.color = if (isEnabled) FloatingChatPalette.accent else FloatingChatPalette.soft
            canvas.drawRoundRect(-18f, -18f, 18f, 18f, 12f, 12f, paint)
        }
        paint.style = Paint.Style.STROKE
        paint.color = if (icon == "send" && isEnabled) Color.WHITE else FloatingChatPalette.accent
        paint.alpha = if (isEnabled) 255 else 110
        when (icon) {
            "open" -> {
                canvas.drawLine(-7f, -1f, -7f, 7f, paint); canvas.drawLine(-7f, 7f, 1f, 7f, paint)
                canvas.drawLine(-2f, 2f, 7f, -7f, paint)
                canvas.drawLine(1f, -7f, 7f, -7f, paint); canvas.drawLine(7f, -7f, 7f, -1f, paint)
            }
            "collapse" -> canvas.drawLine(-7f, 3f, 7f, 3f, paint)
            "close" -> {
                canvas.drawLine(-5f, -5f, 5f, 5f, paint); canvas.drawLine(5f, -5f, -5f, 5f, paint)
            }
            "send" -> {
                canvas.drawLine(0f, 7f, 0f, -7f, paint)
                canvas.drawLine(-6f, -1f, 0f, -7f, paint); canvas.drawLine(0f, -7f, 6f, -1f, paint)
            }
        }
        canvas.restore()
    }
}

internal class FloatingChatBadge(context: Context, action: () -> Unit) : Button(context) {
    var unread = false
        set(value) { field = value; invalidate() }
    private val dot = Paint(Paint.ANTI_ALIAS_FLAG)
    init {
        text = ""
        minimumWidth = 0; minWidth = 0; minimumHeight = 0; minHeight = 0
        setPadding(0, 0, 0, 0)
        background = null
        setOnClickListener { action() }
    }
    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val density = resources.displayMetrics.density
        val x = width / 2f; val y = height / 2f
        dot.color = Color.WHITE
        canvas.drawCircle(x, y, 11f * density, dot)
        dot.color = FloatingChatPalette.accent
        canvas.drawCircle(x, y, 8f * density, dot)
        if (unread) {
            dot.color = Color.WHITE
            canvas.drawCircle(x + 6 * density, y - 6 * density, 4.5f * density, dot)
            dot.color = FloatingChatPalette.unread
            canvas.drawCircle(x + 6 * density, y - 6 * density, 3f * density, dot)
        } else if (isPressed || isFocused) {
            dot.color = Color.WHITE
            canvas.drawCircle(x, y, 2f * density, dot)
        }
    }
}
