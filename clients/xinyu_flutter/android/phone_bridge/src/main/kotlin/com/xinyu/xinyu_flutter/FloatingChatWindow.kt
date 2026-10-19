@file:Suppress("DEPRECATION")
package com.xinyu.xinyu_flutter

import android.content.Context
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Rect
import android.graphics.Typeface
import android.hardware.display.DisplayManager
import android.os.Build
import android.text.*
import android.view.*
import android.view.inputmethod.InputMethodManager
import android.widget.*
import kotlin.math.abs
import kotlinx.coroutines.*

/** One bounded touch window, never a transparent full-screen intercepting layer. */
class FloatingChatWindow(
    baseContext: Context,
    private val onClose: () -> Unit,
    private val onOpenMain: () -> Unit,
) {
    private val context = if (Build.VERSION.SDK_INT >= 30) {
        val display = baseContext.getSystemService(DisplayManager::class.java).getDisplay(Display.DEFAULT_DISPLAY)
        baseContext.createDisplayContext(display).createWindowContext(WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY, null)
    } else baseContext
    private val manager = context.getSystemService(WindowManager::class.java)
    private val keyboard = context.getSystemService(InputMethodManager::class.java)
    private val prefs = context.getSharedPreferences("floating_chat_position", Context.MODE_PRIVATE)
    val position = FloatingChatPosition(prefs.getBoolean("right", true), prefs.getFloat("fraction", .3f))
    val params = WindowManager.LayoutParams(0, 0, WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
        restingFlags, PixelFormat.TRANSLUCENT).apply {
        gravity = Gravity.TOP or Gravity.LEFT
        softInputMode = WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE
    }
    var expanded = false; private set
    var editing = false; private set
    private var attached = false
    private var updating = false
    private var pendingSend = false
    private var imeBottom = 0
    private var editId = 0L
    private var state: Map<String, Any?> = emptyMap()
    private var conversation: String? = null
    private var lastReply: String? = null
    private var unread = false
    private val screenScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var screenJob: Job? = null
    private var openGeneration = 0
    private val root = object : FrameLayout(context) {
        override fun dispatchKeyEventPreIme(event: KeyEvent): Boolean {
            if (event.keyCode == KeyEvent.KEYCODE_BACK && event.action == KeyEvent.ACTION_UP) {
                if (editing) endEditing() else collapse()
                return true
            }
            return super.dispatchKeyEventPreIme(event)
        }
        override fun dispatchTouchEvent(event: MotionEvent): Boolean {
            if (event.action == MotionEvent.ACTION_OUTSIDE) { if (expanded) collapse(); return false }
            return super.dispatchTouchEvent(event)
        }
    }.apply { clipToOutline = true }
    private val bubble = FloatingChatBadge(context) { if (expanded) collapse() else openFromDot() }
    private val panel = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL }
    private val header = LinearLayout(context).apply { gravity = Gravity.CENTER_VERTICAL }
    private val title = label("", 15f).apply {
        typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
        maxLines = 1; ellipsize = TextUtils.TruncateAt.END; includeFontPadding = false
    }
    private val subtitle = label("完整对话 ›", 10f).apply {
        setTextColor(muted); maxLines = 1; ellipsize = TextUtils.TruncateAt.END; includeFontPadding = false
    }
    private val lines = LinearLayout(context).apply {
        orientation = LinearLayout.VERTICAL; setPadding(dp(12), dp(4), dp(12), dp(4))
    }
    private val draftLine = messageBubble("", false)
    private val empty = LinearLayout(context).apply {
        orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER; setPadding(0, dp(8), 0, dp(8))
        addView(label("接着聊，我在。", 14f).apply { gravity = Gravity.CENTER; setTextColor(muted) })
    }
    private val scroll = ScrollView(context).apply {
        isFillViewport = false; isVerticalScrollBarEnabled = true; addView(lines)
    }
    private val status = label("", 12f).apply { setTextColor(muted); maxLines = 3 }
    private val noticeRow = LinearLayout(context).apply {
        gravity = Gravity.CENTER_VERTICAL; setPadding(dp(12), dp(6), dp(8), dp(2))
    }
    private val input = EditText(context).apply {
        hint = "说句话…"; contentDescription = "给心隅的消息"; textSize = 15f
        setTextColor(ink); setHintTextColor(muted); maxLines = 2; minHeight = dp(48)
        inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE
        filters = arrayOf(InputFilter.LengthFilter(6000))
        setPadding(dp(12), dp(8), dp(12), dp(8))
        background = FloatingChatPalette.shape(context, Color.WHITE, 14f, true)
        setOnTouchListener { _, event ->
            if (event.action == MotionEvent.ACTION_DOWN) beginEditing()
            false
        }
        setOnClickListener { beginEditing() }
        addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {
                if (!updating) {
                    editId++
                    event("edit", s.toString())
                    updateSend()
                }
            }
            override fun afterTextChanged(s: Editable?) {}
        })
    }
    private val send = FloatingChatIconButton(context, "send", "发送给心隅") { sendMessage() }
    private val retry = button("重试", "重试心隅的回复") {
        FloatingChatSession.host?.event("retry", mapOf("conversation" to conversation))
    }
    private val composer = LinearLayout(context).apply {
        gravity = Gravity.CENTER_VERTICAL; setPadding(dp(8), dp(4), dp(4), dp(8))
    }

    init {
        val identity = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER_VERTICAL
            contentDescription = "回到完整对话"; isFocusable = true
            setOnClickListener { onOpenMain() }
        }
        identity.addView(title); identity.addView(subtitle, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(2) })
        header.addView(identity, LinearLayout.LayoutParams(0, dp(48), 1f))
        header.addView(FloatingChatIconButton(context, "close", "关闭悬浮陪聊", onClose), LinearLayout.LayoutParams(dp(48), dp(48)))
        panel.addView(header)
        panel.addView(scroll, LinearLayout.LayoutParams(-1, 0, 1f))
        noticeRow.addView(status, LinearLayout.LayoutParams(0, -2, 1f))
        noticeRow.addView(retry, LinearLayout.LayoutParams(dp(48), dp(48)))
        panel.addView(noticeRow)
        composer.addView(input, LinearLayout.LayoutParams(0, -2, 1f))
        composer.addView(send, LinearLayout.LayoutParams(dp(48), dp(48)).apply { leftMargin = dp(4) })
        panel.addView(composer)
        root.addView(panel, FrameLayout.LayoutParams(-1, -1))
        root.addView(bubble, FrameLayout.LayoutParams(dp(48), dp(48)))
        drag(bubble); drag(identity)
        root.setOnApplyWindowInsetsListener { _, insets ->
            if (Build.VERSION.SDK_INT >= 30) {
                val ime = insets.getInsets(WindowInsets.Type.ime()).bottom
                if (ime != imeBottom) {
                    imeBottom = ime
                    reflow()
                }
            }
            insets
        }
    }

    fun show() {
        reflow()
        manager.addView(root, params)
        attached = true
    }

    fun expand() { expanded = true; unread = false; reflow(); render(state) }
    fun collapse() { openGeneration++; screenJob?.cancel(); endEditing(); expanded = false; reflow(); render(state) }

    private fun openFromDot() {
        if (screenJob?.isActive == true) return
        if (state["readScreen"] != true) { expand(); return }
        val ticket = ++openGeneration
        val active = conversation
        val vision = state["screenVision"] == true
        screenJob = screenScope.launch {
            val result = try {
                if (vision) { root.alpha = 0f; delay(48) }
                withTimeout(3000) { withContext(Dispatchers.IO) { FloatingScreenReader.capture(context, vision) } }
            } catch (error: CancellationException) {
                if (error !is TimeoutCancellationException) throw error
                mapOf("notice" to "这次读屏超时了，你可以先直接和我聊。")
            } catch (_: Exception) { mapOf("notice" to "这次没能读取页面，你可以先直接和我聊。") }
            finally { root.alpha = 1f }
            if (!attached || ticket != openGeneration || active != conversation) return@launch
            expand()
            FloatingChatSession.host?.event("screen_open", result + mapOf("conversation" to active))
        }
    }

    fun beginEditing() {
        if (!expanded || editing) return
        editing = true
        params.flags = restingFlags and (WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_ALT_FOCUSABLE_IM).inv()
        if (attached) manager.updateViewLayout(root, params)
        input.requestFocus()
        input.post { if (editing && attached) keyboard.showSoftInput(input, InputMethodManager.SHOW_IMPLICIT) }
    }

    fun endEditing() {
        if (!editing) return
        keyboard.hideSoftInputFromWindow(root.windowToken, 0)
        input.clearFocus()
        editing = false
        params.flags = restingFlags
        if (attached) manager.updateViewLayout(root, params)
    }

    fun reflow() {
        val area = bounds()
        val availableHeight = (area.height() - imeBottom).coerceAtLeast(dp(48))
        params.width = if (expanded) minOf(dp(248), area.width()) else dp(48)
        // Measure real text first: a short reply gets a short card; a long reply scrolls.
        val widthSpec = View.MeasureSpec.makeMeasureSpec(params.width, View.MeasureSpec.EXACTLY)
        val freeHeight = View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED)
        lines.measure(widthSpec, freeHeight)
        composer.measure(widthSpec, freeHeight)
        noticeRow.measure(widthSpec, freeHeight)
        val noticeHeight = if (noticeRow.visibility == View.GONE) 0 else noticeRow.measuredHeight
        val bodyHeight = lines.measuredHeight.coerceIn(dp(48), dp(128))
        params.height = if (expanded) minOf(dp(48) + bodyHeight + composer.measuredHeight + noticeHeight, availableHeight) else dp(48)
        position.layout(params.width, params.height, area.width(), availableHeight, dp(48))
        params.x = position.x
        params.y = position.y
        root.background = if (expanded) FloatingChatPalette.shape(context, canvas, 20f, true) else null
        root.elevation = if (expanded) dp(4).toFloat() else 0f
        bubble.layoutParams = FrameLayout.LayoutParams(dp(48), dp(48), Gravity.TOP or if (position.right) Gravity.RIGHT else Gravity.LEFT)
        header.setPadding(if (position.right) dp(12) else dp(48), 0, if (position.right) dp(48) else 0, 0)
        panel.visibility = if (expanded) View.VISIBLE else View.GONE
        if (attached) manager.updateViewLayout(root, params)
    }

    fun render(value: Map<String, Any?>) {
        val changedConversation = conversation != value["conversation"]
        state = value
        if (value["readScreen"] == false && screenJob?.isActive == true) {
            openGeneration++; screenJob?.cancel()
        }
        if (changedConversation) { openGeneration++; screenJob?.cancel(); endEditing(); unread = false; lastReply = null }
        conversation = value["conversation"] as? String
        title.text = (value["name"] as? String ?: "心隅").take(40)
        subtitle.text = (value["status"] as? String).orEmpty().ifEmpty {
            if (value["busy"] == true) "正在回复…" else "完整对话 ›"
        }
        val messages = (value["messages"] as? List<*>)?.filterIsInstance<Map<*, *>>() ?: emptyList()
        val latest = messages.lastOrNull { it["user"] != true }?.get("id") as? String
        if (!changedConversation && latest != null && latest != lastReply && !expanded) unread = true
        lastReply = latest
        bubble.unread = unread
        bubble.contentDescription = if (expanded) "收起悬浮小窗" else if (unread) "心隅有新回复，点此展开" else "展开悬浮陪聊，拖动可贴边"
        val ack = (value["editAck"] as? Number)?.toLong() ?: 0L
        val mayReplaceComposer = changedConversation || ack >= editId
        editId = maxOf(editId, ack)
        if (mayReplaceComposer) {
            val text = value["composer"] as? String ?: ""
            if (text != input.text.toString()) {
                updating = true
                input.setText(text); input.setSelection(text.length)
                updating = false
            }
        }
        updateSend()
        input.isEnabled = value["editable"] != false
        if (!input.isEnabled) endEditing()
        val notice = value["notice"] as? String ?: ""
        status.text = notice
        status.visibility = if (notice.isEmpty()) View.GONE else View.VISIBLE
        noticeRow.visibility = if (notice.isNotEmpty() || value["canRetry"] == true) View.VISIBLE else View.GONE
        retry.visibility = if (value["canRetry"] == true) View.VISIBLE else View.GONE
        if (!expanded) return
        val atBottom = !scroll.canScrollVertically(1)
        val signature = "${params.width}:$messages:${title.text}"
        if (lines.tag != signature) {
            lines.tag = signature
            lines.removeAllViews()
            lines.addView(empty, LinearLayout.LayoutParams(-1, -2))
            val lastUser = messages.indexOfLast { it["user"] == true }
            val recent = if (lastUser >= 0) messages.drop(lastUser) else messages.takeLast(1)
            for (message in recent) {
                val user = message["user"] == true
                val text = (message["text"] as? String ?: "").take(6000)
                lines.addView(messageBubble(text, user).apply {
                    contentDescription = (if (user) "我：" else "${title.text}：") + text
                }, messageLayout(user))
            }
            lines.addView(draftLine, messageLayout(false))
        }
        val draft = value["draft"] as? String ?: ""
        empty.visibility = if (messages.isEmpty() && draft.isEmpty() && value["busy"] != true) View.VISIBLE else View.GONE
        draftLine.text = draft.take(6000).ifEmpty { if (value["busy"] == true) "正在回复…" else "" }
        draftLine.maxWidth = (params.width - dp(24)).coerceAtLeast(dp(48))
        draftLine.visibility = if (draftLine.text.isEmpty()) View.GONE else View.VISIBLE
        reflow()
        if (atBottom) scroll.post { scroll.scrollTo(0, lines.height) }
    }

    private fun sendMessage() {
        if (pendingSend || state["canSend"] != true || input.text.toString().isBlank()) return
        if (android.view.inputmethod.BaseInputConnection.getComposingSpanStart(input.text) >= 0) return
        pendingSend = true; send.isEnabled = false
        val text = input.text.toString()
        event("send", text) { accepted ->
            pendingSend = false
            if (!accepted) {
                status.text = "消息未发送，请检查当前对话后重试。"
                status.visibility = View.VISIBLE; noticeRow.visibility = View.VISIBLE; reflow()
            }
            else endEditing()
            updateSend()
        }
    }

    private fun updateSend() {
        send.isEnabled = state["canSend"] == true && !pendingSend && input.text.toString().isNotBlank()
    }

    private fun messageLayout(user: Boolean) = LinearLayout.LayoutParams(-2, -2).apply {
        gravity = Gravity.LEFT
        bottomMargin = dp(6)
    }

    private fun messageBubble(text: String, user: Boolean) = label(text, 14f).apply {
        setTextColor(if (user) muted else ink)
        maxWidth = (params.width - dp(24)).coerceAtLeast(dp(48))
        setTextIsSelectable(true)
        if (user) { textSize = 12f; maxLines = 1; ellipsize = TextUtils.TruncateAt.END }
    }

    private fun event(method: String, text: String, done: (Boolean) -> Unit = {}) {
        FloatingChatSession.host?.event(method, mapOf("conversation" to conversation, "text" to text, "editId" to editId), done)
    }

    private fun drag(view: View) {
        var downX = 0f; var downY = 0f; var startX = 0; var startY = 0; var moved = false
        view.setOnTouchListener { target, event ->
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    downX = event.rawX; downY = event.rawY; startX = params.x; startY = params.y; moved = false
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = event.rawX - downX; val dy = event.rawY - downY
                    if (abs(dx) + abs(dy) > ViewConfiguration.get(context).scaledTouchSlop) moved = true
                    if (moved) {
                        val area = bounds()
                        val availableHeight = (area.height() - imeBottom).coerceAtLeast(dp(48))
                        position.drag(startX + dx.toInt(), startY + dy.toInt(), params.width, params.height, area.width(), availableHeight)
                        params.x = position.x; params.y = position.y
                        if (attached) manager.updateViewLayout(root, params)
                    }
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    if (moved) {
                        val area = bounds()
                        val availableHeight = (area.height() - imeBottom).coerceAtLeast(dp(48))
                        position.snap(params.width, params.height, area.width(), availableHeight, dp(48))
                        prefs.edit().putBoolean("right", position.right).putFloat("fraction", position.fraction).apply()
                        reflow()
                    } else if (event.actionMasked == MotionEvent.ACTION_UP) target.performClick()
                }
            }
            true
        }
    }

    private fun bounds(): Rect {
        if (Build.VERSION.SDK_INT >= 30) {
            val metrics = manager.maximumWindowMetrics
            val insets = metrics.windowInsets.getInsetsIgnoringVisibility(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
            return Rect(0, 0, metrics.bounds.width() - insets.left - insets.right, metrics.bounds.height() - insets.top - insets.bottom)
        }
        val metrics = android.util.DisplayMetrics()
        manager.defaultDisplay.getMetrics(metrics)
        return Rect(0, 0, metrics.widthPixels, metrics.heightPixels)
    }

    fun dispose() {
        openGeneration++; screenScope.cancel()
        if (editing) keyboard.hideSoftInputFromWindow(root.windowToken, 0)
        editing = false
        if (attached) {
            try { manager.removeViewImmediate(root) } catch (_: IllegalArgumentException) { /* System already removed it. */ }
            attached = false
        }
        state = emptyMap(); lines.removeAllViews()
        updating = true; input.setText(""); updating = false
    }
    private fun label(value: String, size: Float) = TextView(context).apply { text = value; textSize = size; setTextColor(ink); setLineSpacing(dp(3).toFloat(), 1f) }
    private fun button(value: String, description: String, click: () -> Unit) = Button(context).apply {
        text = value; textSize = 14f; isAllCaps = false; contentDescription = description
        setTextColor(accent); minWidth = 0; minimumWidth = 0; minHeight = dp(48); minimumHeight = dp(48)
        setPadding(0, 0, 0, 0); background = android.graphics.drawable.ColorDrawable(Color.TRANSPARENT)
        setOnClickListener { click() }
    }
    private fun dp(value: Int) = (value * context.resources.displayMetrics.density).toInt()
    companion object {
        val restingFlags = WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
            WindowManager.LayoutParams.FLAG_ALT_FOCUSABLE_IM or
            WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or WindowManager.LayoutParams.FLAG_WATCH_OUTSIDE_TOUCH
        private val ink = Color.rgb(23, 33, 50)
        private val muted = Color.rgb(100, 113, 136)
        private val accent = Color.rgb(74, 96, 125)
        private val canvas = Color.rgb(247, 246, 244)
    }
}
