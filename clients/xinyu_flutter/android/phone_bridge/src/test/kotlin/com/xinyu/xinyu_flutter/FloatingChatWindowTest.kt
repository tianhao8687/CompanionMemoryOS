package com.xinyu.xinyu_flutter

import android.content.Context
import android.view.*
import android.widget.*
import org.junit.*
import org.junit.Assert.*
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.util.ReflectionHelpers

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28, 36], manifest = Config.NONE)
class FloatingChatWindowTest {
    private val context: Context get() = RuntimeEnvironment.getApplication()
    private lateinit var window: FloatingChatWindow
    private lateinit var root: FrameLayout
    private val events = mutableListOf<Pair<String, Map<String, Any?>>>()
    private fun state(text: String = "", ack: Int = 0, reply: String = "reply-1") = mapOf(
        "conversation" to "synthetic-chat", "name" to "小禾", "composer" to text, "editAck" to ack,
        "canSend" to true, "canRetry" to false, "messages" to listOf(mapOf("id" to reply, "user" to false, "text" to "合成回复")),
    )
    @Before fun setup() {
        context.getSharedPreferences("floating_chat_position", Context.MODE_PRIVATE).edit().clear().commit()
        FloatingChatSession.host = object : FloatingChatSession.Host {
            override fun event(method: String, args: Map<String, Any?>, done: (Boolean) -> Unit) {
                events += method to args; done(true)
            }
            override fun stopped() {}
            override fun changed() {}
        }
        window = FloatingChatWindow(context, {}, {})
        root = ReflectionHelpers.getField(window, "root")
        window.show(); window.render(state())
    }
    @After fun cleanup() { window.dispose(); FloatingChatSession.host = null; FloatingChatSession.clear() }

    private fun all(view: View): List<View> = listOf(view) + if (view is android.view.ViewGroup)
        (0 until view.childCount).flatMap { all(view.getChildAt(it)) } else emptyList()

    @Test fun collapsedWindowIsBoundedAndDoesNotConsumeOutsideTouchesOrKeyboard() {
        val flags = window.params.flags
        assertEquals(WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY, window.params.type)
        assertTrue(flags and WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE != 0)
        assertTrue(flags and WindowManager.LayoutParams.FLAG_ALT_FOCUSABLE_IM != 0)
        assertTrue(flags and WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL != 0)
        assertEquals(0, flags and WindowManager.LayoutParams.FLAG_DIM_BEHIND)
        assertEquals(0, flags and WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE)
        val expected = (48 * context.resources.displayMetrics.density).toInt()
        assertEquals(expected, window.params.width); assertEquals(expected, window.params.height)
    }

    @Test fun typingIsExplicitAndOutsideTapReturnsFocus() {
        window.expand()
        assertFalse(window.editing)
        assertTrue(window.expanded)
        window.beginEditing()
        assertTrue(window.editing)
        assertEquals(0, window.params.flags and WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE)
        assertEquals(0, window.params.flags and WindowManager.LayoutParams.FLAG_ALT_FOCUSABLE_IM)
        assertTrue(window.params.flags and WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL != 0)
        val outside = MotionEvent.obtain(0, 0, MotionEvent.ACTION_OUTSIDE, 0f, 0f, 0)
        root.dispatchTouchEvent(outside); outside.recycle()
        assertFalse(window.editing)
        assertFalse(window.expanded)
        assertTrue(window.params.flags and WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE != 0)
        assertTrue(window.params.flags and WindowManager.LayoutParams.FLAG_ALT_FOCUSABLE_IM != 0)
    }

    @Test @Config(sdk = [36]) fun keyboardInsetsKeepTheWindowInsideUsableSpace() {
        window.expand(); window.beginEditing()
        val height = window.params.height
        val y = window.params.y
        val keyboard = WindowInsets.Builder().setInsets(WindowInsets.Type.ime(), android.graphics.Insets.of(0, 0, 0, 200)).build()
        root.dispatchApplyWindowInsets(keyboard)
        assertTrue(window.params.height <= height)
        assertTrue(window.params.y < y)
        root.dispatchApplyWindowInsets(WindowInsets.Builder().setInsets(WindowInsets.Type.ime(), android.graphics.Insets.NONE).build())
        assertEquals(height, window.params.height)
        assertEquals(y, window.params.y)
        assertTrue(window.editing)
    }

    @Test fun replyDoesNotExpandOrStealFocusAndCollapseKeepsDraft() {
        window.expand(); window.beginEditing()
        val input = all(root).filterIsInstance<EditText>().single()
        input.setText("合成草稿")
        window.collapse()
        window.render(state("合成草稿", 1, "reply-2"))
        assertFalse(window.expanded); assertFalse(window.editing)
        assertEquals("合成草稿", input.text.toString())
        assertTrue(all(root).any { it.contentDescription?.contains("有新回复") == true })
        val edits = events.count { it.first == "edit" }
        window.dispose()
        assertEquals(edits, events.count { it.first == "edit" })
    }

    @Test fun delayedProjectionDoesNotOverwriteNewTyping() {
        window.expand()
        val input = all(root).filterIsInstance<EditText>().single()
        input.setText("新内容")
        window.render(state("旧内容", 0))
        assertEquals("新内容", input.text.toString())
        window.render(state("", 1))
        assertEquals("", input.text.toString())
        assertEquals("synthetic-chat", events.single().second["conversation"])
    }

    @Test fun dragGestureSnapsAndNeverCrossesScreenBounds() {
        val bubble = all(root).filterIsInstance<FloatingChatBadge>().single()
        for ((action, x, y) in listOf(Triple(MotionEvent.ACTION_DOWN, 400f, 100f),
            Triple(MotionEvent.ACTION_MOVE, -900f, 10000f), Triple(MotionEvent.ACTION_UP, -900f, 10000f))) {
            val event = MotionEvent.obtain(0, 10, action, x, y, 0)
            bubble.dispatchTouchEvent(event); event.recycle()
        }
        assertFalse(window.position.right)
        assertEquals(0, window.params.x)
        assertTrue(window.position.fraction in 0f..1f)
        assertFalse(window.expanded)
    }

    @Test fun sendIsBoundToDisplayedConversationAndReturnsKeyboardFocus() {
        window.expand(); window.beginEditing()
        all(root).filterIsInstance<EditText>().single().setText("发送合成文字")
        all(root).single { it.contentDescription == "发送给心隅" }.performClick()
        val sent = events.single { it.first == "send" }.second
        assertEquals("synthetic-chat", sent["conversation"])
        assertEquals("发送合成文字", sent["text"])
        assertFalse(window.editing)
    }

    @Test fun sendAvailabilityFollowsTypingAndBusyState() {
        window.expand()
        val input = all(root).filterIsInstance<EditText>().single()
        val send = all(root).single { it.contentDescription == "发送给心隅" }
        assertFalse(send.isEnabled)
        input.setText("一条合成消息")
        assertTrue(send.isEnabled)
        window.render(state("一条合成消息", 1) + mapOf("canSend" to false, "busy" to true))
        assertFalse(send.isEnabled)
        window.render(state("   ", 2))
        assertFalse(send.isEnabled)
    }

    @Test fun edgeAndRelativeHeightSurviveResize() {
        val p = FloatingChatPosition()
        p.drag(0, 300, 48, 48, 360, 648)
        p.snap(48, 48, 360, 648)
        assertFalse(p.right); assertEquals(.5f, p.fraction, .001f)
        p.layout(336, 340, 800, 500)
        assertEquals(0, p.x); assertEquals(80, p.y)
        p.layout(336, 340, 200, 200)
        assertEquals(0, p.x); assertEquals(0, p.y)
    }

    @Test fun dotTogglesWithoutMovingAndOutsideTapPreservesDraft() {
        val bubble = all(root).filterIsInstance<FloatingChatBadge>().single()
        val y = window.params.y
        bubble.performClick()
        assertTrue(window.expanded); assertEquals(y, window.params.y)
        assertTrue(window.params.height < (300 * context.resources.displayMetrics.density).toInt())
        all(root).filterIsInstance<EditText>().single().setText("还没说完")
        val outside = MotionEvent.obtain(0, 0, MotionEvent.ACTION_OUTSIDE, 0f, 0f, 0)
        root.dispatchTouchEvent(outside); outside.recycle()
        assertFalse(window.expanded)
        assertEquals("还没说完", all(root).filterIsInstance<EditText>().single().text.toString())
        bubble.performClick(); bubble.performClick()
        assertFalse(window.expanded)
    }

    @Test fun dotKeepsLatestExchangeAndLongReplyCanScroll() {
        window.expand()
        window.render(state() + mapOf("messages" to listOf(
            mapOf("id" to "old", "user" to false, "text" to "旧回复"),
            mapOf("id" to "u", "user" to true, "text" to "现在这句"),
            mapOf("id" to "a", "user" to false, "text" to "较长的合成回复。".repeat(100)),
        )))
        assertFalse(all(root).filterIsInstance<TextView>().any { it.text.toString() == "旧回复" })
        assertTrue(all(root).filterIsInstance<TextView>().any { it.text.toString() == "现在这句" })
        assertTrue(window.params.height <= (240 * context.resources.displayMetrics.density).toInt())
    }
}
