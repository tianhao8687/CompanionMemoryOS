@file:Suppress("DEPRECATION")
package com.xinyu.xinyu_flutter

import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28, 36], manifest = Config.NONE)
class FloatingScreenReaderTest {
    private fun node(text: String, visible: Boolean = true, password: Boolean = false) = AccessibilityNodeInfo.obtain().apply {
        this.text = text; isVisibleToUser = visible; isPassword = password
        setBoundsInScreen(Rect(0, 0, 300, 100))
    }
    @Test fun onlyVisibleTextIsCollectedAndPasswordsBlockImages() {
        val root = node("")
        shadowOf(root).addChild(node("合成页面的对话"))
        shadowOf(root).addChild(node("隐藏文字", visible = false))
        shadowOf(root).addChild(node("秘密密码", password = true))
        shadowOf(root).addChild(node("合成页面的对话"))
        val result = FloatingScreenReader.visibleText(root)
        assertEquals("合成页面的对话", result.text)
        assertTrue(result.sensitive)
        root.recycle()
    }
    @Test fun longScreenIsBoundedAndMarkedIncomplete() {
        val root = node("字".repeat(5000))
        val result = FloatingScreenReader.visibleText(root)
        assertEquals(4000, result.text.length); assertTrue(result.truncated)
        root.recycle()
    }
    @Test fun ownAndSystemWindowsCannotBecomeExternalEvidence() {
        assertFalse(FloatingScreenReader.allowedPackage("com.xinyu", "com.xinyu"))
        assertFalse(FloatingScreenReader.allowedPackage("com.android.systemui", "com.xinyu"))
        assertFalse(FloatingScreenReader.allowedPackage(null, "com.xinyu"))
        assertTrue(FloatingScreenReader.allowedPackage("com.tencent.mobileqq", "com.xinyu"))
    }
}
