package com.xinyu.xinyu_flutter

import android.graphics.Bitmap
import android.graphics.Canvas
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import android.widget.LinearLayout
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import org.robolectric.util.ReflectionHelpers
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36], manifest = Config.NONE, qualifiers = "w360dp-h800dp-mdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class FloatingChatLayoutTest {
    @Test fun expandedControlsFitAndCollapsedWindowLeavesTheScreenAvailable() {
        val window = FloatingChatWindow(RuntimeEnvironment.getApplication(), {}, {})
        try {
            window.show(); window.expand()
            window.render(mapOf(
                "conversation" to "synthetic-layout", "name" to "小禾", "composer" to "陪我聊一会儿",
                "canSend" to true, "messages" to listOf(
                    mapOf("id" to "u", "user" to true, "text" to "刚忙完，想歇一会儿。"),
                    mapOf("id" to "a", "user" to false, "text" to "好啊，我在这里。今天有什么想慢慢说的？"),
                ), "status" to "与完整对话同步",
            ))
            val root = ReflectionHelpers.getField<ViewGroup>(window, "root")
            fun layout() {
                root.measure(View.MeasureSpec.makeMeasureSpec(window.params.width, View.MeasureSpec.EXACTLY),
                    View.MeasureSpec.makeMeasureSpec(window.params.height, View.MeasureSpec.EXACTLY))
                root.layout(0, 0, window.params.width, window.params.height)
            }
            fun descendants(view: View): List<View> = listOf(view) + if (view is ViewGroup)
                (0 until view.childCount).flatMap { descendants(view.getChildAt(it)) } else emptyList()
            layout()
            val userBubble = descendants(root).filterIsInstance<TextView>().single { it.text.toString() == "刚忙完，想歇一会儿。" }
            val replyBubble = descendants(root).filterIsInstance<TextView>().single { it.text.toString() == "好啊，我在这里。今天有什么想慢慢说的？" }
            assertEquals(android.view.Gravity.LEFT, (userBubble.layoutParams as LinearLayout.LayoutParams).gravity)
            assertEquals(android.view.Gravity.LEFT, (replyBubble.layoutParams as LinearLayout.LayoutParams).gravity)
            assertTrue(userBubble.width <= root.width - 24)
            assertTrue(replyBubble.width <= root.width - 24)
            assertTrue(root.width <= 248); assertTrue(root.height <= 240)
            for (description in listOf("回到完整对话", "收起悬浮小窗", "关闭悬浮陪聊", "给心隅的消息", "发送给心隅")) {
                val control = descendants(root).single { it.contentDescription == description }
                assertTrue("$description remains usable", control.width >= 48 && control.height >= 48)
                val bounds = android.graphics.Rect(0, 0, control.width, control.height)
                root.offsetDescendantRectToMyCoords(control, bounds)
                assertTrue("$description is inside the window", android.graphics.Rect(0, 0, root.width, root.height).contains(bounds))
            }
            fun capture(name: String) {
                val output = System.getProperty("xinyu.visual.output") ?: return
                val file = File(output, "$name.png")
                file.parentFile?.mkdirs()
                val bitmap = Bitmap.createBitmap(root.width, root.height, Bitmap.Config.ARGB_8888)
                root.draw(Canvas(bitmap))
                file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
                bitmap.recycle()
            }
            capture("floating-chat-native-expanded")
            window.render(mapOf("conversation" to "synthetic-layout", "name" to "小禾", "composer" to "",
                "canSend" to false, "canRetry" to true, "messages" to emptyList<Map<String, Any?>>(),
                "notice" to "回复暂时中断，可以重试。"))
            layout(); capture("floating-chat-native-retry")
            window.collapse(); layout()
            assertEquals(48, root.width); assertEquals(48, root.height)
            val dotBitmap = Bitmap.createBitmap(48, 48, Bitmap.Config.ARGB_8888)
            root.draw(Canvas(dotBitmap))
            for (y in 0 until 48) for (x in 0 until 48) {
                if (x !in 12..35 || y !in 12..35) assertEquals(0, android.graphics.Color.alpha(dotBitmap.getPixel(x, y)))
            }
            dotBitmap.recycle()
            capture("floating-chat-native-dot")
            window.render(mapOf("conversation" to "synthetic-layout", "messages" to listOf(
                mapOf("id" to "new-reply", "user" to false, "text" to "合成新回复"))))
            capture("floating-chat-native-unread")
        } finally { window.dispose() }
    }
}
